"""
Business-logic layer for JTP Training Tracker.
All views and API endpoints call these functions; no direct ORM in views.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from django.db import connection, transaction
from django.db.models import Count, Q
from django.conf import settings

from .models import (
    JTPPathway, EEJTPStatus, JTPAdminUser, JTPTeamMember,
)


# ─────────────────────────────────────────────────────────────────────────────
# Status helpers
# ─────────────────────────────────────────────────────────────────────────────

def is_completed(status: str | None) -> bool:
    """Return True if the status string represents a completed course."""
    if status is None:
        return False
    return bool(str(status).strip())


def get_completion_date_obj(status: str | None) -> date | None:
    """Parse the status field into a date object; return None if not parseable."""
    if not status:
        return None
    s = str(status).strip()
    if not s or s.lower() in ('none', 'null', 'completed'):
        return None
    formats = ['%Y-%m-%d', '%m/%d/%Y', '%d/%m/%Y', '%Y/%m/%d', '%m-%d-%Y']
    for fmt in formats:
        try:
            from datetime import datetime
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def get_completion_display(status: str | None) -> str | None:
    """Return a human-readable completion date string."""
    if not status:
        return None
    s = str(status).strip()
    if s.lower() == 'completed':
        return 'Completed'
    d = get_completion_date_obj(s)
    if d:
        return d.strftime('%b %d, %Y')
    return s


# ─────────────────────────────────────────────────────────────────────────────
# Due-date / refresh logic
# ─────────────────────────────────────────────────────────────────────────────

def calculate_due_date(
    assigned_date: date,
    expect_days: int,
    refresh_days: int | None = None,
    completion_date: date | None = None,
) -> date:
    """
    Calculate the due date for a course.

    - Without completion / refresh: assigned_date + expect_days
    - With completion AND refresh_days set: max(assigned_date, completion_date) + refresh_days
    """
    if refresh_days and completion_date:
        base = max(assigned_date, completion_date)
        return base + timedelta(days=refresh_days)
    return assigned_date + timedelta(days=expect_days)


def _update_refresh_date(record: EEJTPStatus) -> None:
    """
    After a course is marked complete, recalculate due_date and refresh_date
    for courses that have a refresh_cycle set.
    """
    try:
        pathway_course = JTPPathway.objects.filter(
            pathway_name=record.assigned_pathway,
            course_name=record.course_name,
        ).first()

        if not pathway_course or not pathway_course.refresh_cycle:
            return

        completion_date = get_completion_date_obj(record.status)
        if not completion_date:
            return

        # assigned_date is stored as TEXT in the DB; parse before arithmetic
        ad_obj = get_completion_date_obj(str(record.assigned_date)) if record.assigned_date else completion_date
        base = max(ad_obj, completion_date)
        new_date = base + timedelta(days=pathway_course.refresh_cycle)
        record.refresh_date = new_date.strftime('%Y-%m-%d')  # store as text
        record.due_date     = new_date.strftime('%Y-%m-%d')  # store as text
    except Exception as exc:
        print(f'[RefreshDate] Error updating refresh date for record {record.pk}: {exc}')


# ─────────────────────────────────────────────────────────────────────────────
# inf_data WBT sync
# ─────────────────────────────────────────────────────────────────────────────

def _parse_inf_date(date_str: str) -> date:
    """Try common date formats used in inf_data."""
    from datetime import datetime
    formats = ['%Y-%m-%d', '%m/%d/%Y', '%d/%m/%Y', '%Y/%m/%d', '%m-%d-%Y']
    for fmt in formats:
        try:
            return datetime.strptime(date_str.strip(), fmt).date()
        except ValueError:
            continue
    raise ValueError(f'Cannot parse inf_data date: {date_str!r}')


def sync_wbt_completions_for_employee(employee_wwid: str) -> int:
    """
    Query inf_data for all WBT courses assigned to this employee and update
    EE_JTP_Status.status where the inf_data shows completion.

    Some inf_data rows have status='Complete' but no completion_date.
    In that case today's date is used as the fallback.

    Returns the number of records updated.
    """
    pending = EEJTPStatus.objects.filter(
        employee_wwid=employee_wwid,
        course_type='WBT',
    ).filter(Q(status__isnull=True) | Q(status=''))

    col_wwid    = settings.INF_DATA_COL_WWID
    col_cid     = settings.INF_DATA_COL_COURSE_ID
    col_status  = settings.INF_DATA_COL_STATUS
    col_date    = settings.INF_DATA_COL_COMPLETION_DATE
    table       = settings.INF_DATA_TABLE

    updated = 0
    for record in pending:
        # course_id in EE_JTP_Status is double precision; convert to int for inf_data lookup
        try:
            cid = int(float(record.course_id))
        except (TypeError, ValueError):
            continue
        if not cid:
            continue
        try:
            with connection.cursor() as cursor:
                # Number_ID may be zero-padded text; cast both sides to bigint for numeric match
                cursor.execute(
                    f'SELECT "{col_status}", "{col_date}" FROM {table} '
                    f'WHERE "{col_wwid}"::text = %s AND "{col_cid}"::bigint = %s LIMIT 1',
                    [str(employee_wwid), cid],
                )
                row = cursor.fetchone()
            if not row:
                continue

            inf_status, inf_date = row
            if not inf_status:
                continue
            if str(inf_status).strip().lower() not in ('complete', 'completed'):
                continue

            # Determine completion date
            if inf_date:
                try:
                    completion = _parse_inf_date(str(inf_date))
                    record.status = completion.strftime('%Y-%m-%d')
                except ValueError:
                    record.status = date.today().strftime('%Y-%m-%d')
            else:
                # "Complete" but no date — use today as fallback
                record.status = date.today().strftime('%Y-%m-%d')

            _update_refresh_date(record)
            record.save(update_fields=['status', 'refresh_date', 'due_date'])
            updated += 1

        except Exception as exc:
            print(f'[SyncWBT] Error WWID={employee_wwid} course={record.course_id}: {exc}')

    return updated


def sync_wbt_completions_for_all() -> int:
    """Sync WBT completions for every employee who has pending WBT courses."""
    wwids = (
        EEJTPStatus.objects.filter(course_type='WBT')
        .filter(Q(status__isnull=True) | Q(status=''))
        .values_list('employee_wwid', flat=True)
        .distinct()
    )
    total = 0
    for wwid in wwids:
        total += sync_wbt_completions_for_employee(wwid)
    return total


# ─────────────────────────────────────────────────────────────────────────────
# Progress calculation
# ─────────────────────────────────────────────────────────────────────────────

def build_pathway_progress(records) -> dict[str, Any]:
    """
    Build an ordered dict: pathway_name → {name, courses[], total, completed, percentage, …}
    Accepts a QuerySet of EEJTPStatus or a list.
    """
    from collections import OrderedDict
    today = date.today()
    pathways: dict[str, Any] = OrderedDict()

    for record in records:
        pname = record.assigned_pathway
        # Skip orphaned / legacy rows that have no valid pathway name
        if not pname or str(pname).strip() in ('', 'None'):
            continue
        pname = str(pname).strip()
        if pname not in pathways:
            pathways[pname] = {
                'name': pname,
                'courses': [],
                'total': 0,
                'completed': 0,
            }

        is_done      = record.is_completed
        # Parse text dates for comparison (DB stores these as TEXT)
        due_date_obj     = get_completion_date_obj(str(record.due_date))     if record.due_date     else None
        refresh_date_obj = get_completion_date_obj(str(record.refresh_date)) if record.refresh_date else None
        assigned_date_obj = get_completion_date_obj(str(record.assigned_date)) if record.assigned_date else None
        is_overdue   = bool(due_date_obj and not is_done and due_date_obj < today)
        refresh_due  = bool(refresh_date_obj and is_done and refresh_date_obj <= today)

        pathways[pname]['courses'].append({
            'id':                  record.pk,
            'course_name':         record.course_name,
            'course_type':         record.course_type or 'WBT',
            'assigned_date':       assigned_date_obj,
            'due_date':            due_date_obj,
            'refresh_date':        refresh_date_obj,
            'status':              record.status,
            'is_completed':        is_done,
            'completion_display':  record.completion_date_display,
            'is_overdue':          is_overdue,
            'refresh_due':         refresh_due,
            'manually_confirmed':  record.manually_confirmed,
            # Only ILT/Other can be manually confirmed
            'can_manual_confirm': (
                not is_done and record.course_type in ('ILT', 'Other')
            ),
        })

        pathways[pname]['total'] += 1
        if is_done:
            pathways[pname]['completed'] += 1

    for pname, data in pathways.items():
        t = data['total']
        c = data['completed']
        data['percentage']       = int(c / t * 100) if t > 0 else 0
        data['is_fully_complete'] = data['percentage'] == 100

    return pathways


def get_employee_pathway_completion(employee_wwid: str) -> dict[str, Any]:
    """Return pathway progress dict for one employee."""
    records = EEJTPStatus.objects.filter(
        employee_wwid=employee_wwid,
    ).exclude(assigned_pathway='').exclude(assigned_pathway__isnull=True
    ).order_by('assigned_pathway', 'course_name')
    return build_pathway_progress(records)


# ─────────────────────────────────────────────────────────────────────────────
# Manual completion (ILT / Other)
# ─────────────────────────────────────────────────────────────────────────────

def confirm_course_completion(
    status_id: int,
    requesting_wwid: str,
    admin_override: bool = False,
) -> EEJTPStatus:
    """
    Mark an ILT or Other course as complete.
    Only the employee themselves, their manager, or an admin may do this.
    Pass admin_override=True (from is_admin(request)) to bypass the auth check.
    Returns the updated EEJTPStatus record.
    """
    record = EEJTPStatus.objects.get(pk=status_id)

    if record.course_type not in ('ILT', 'Other'):
        raise PermissionError('Only ILT and Other courses can be manually confirmed.')

    # Authorization: the employee, their manager, or an admin
    # employee_wwid is bigint in DB so psycopg2 returns int; normalise to str for comparison
    if not admin_override:
        if str(record.employee_wwid) != requesting_wwid and str(record.mgr_wwid or '') != requesting_wwid:
            from .models import JTPAdminUser
            if not JTPAdminUser.objects.filter(
                Q(wwid=requesting_wwid) | Q(isid=requesting_wwid)
            ).exists():
                raise PermissionError('You do not have permission to confirm this course.')

    record.status = date.today().strftime('%Y-%m-%d')
    record.manually_confirmed = True
    _update_refresh_date(record)
    record.save(update_fields=['status', 'manually_confirmed', 'refresh_date', 'due_date'])
    return record


# ─────────────────────────────────────────────────────────────────────────────
# Pathway assignment
# ─────────────────────────────────────────────────────────────────────────────

def assign_pathway_to_employee(
    pathway_name: str,
    employee_wwid: str,
    employee_info: dict,
    assigned_by_wwid: str = '',
) -> list[EEJTPStatus]:
    """
    Assign all courses in *pathway_name* to *employee_wwid*.
    Skips courses already assigned.
    Returns list of newly created EEJTPStatus records.
    """
    courses = JTPPathway.objects.filter(pathway_name=pathway_name)
    if not courses.exists():
        raise ValueError(f"Pathway '{pathway_name}' not found or has no courses.")

    today = date.today()
    created: list[EEJTPStatus] = []

    with transaction.atomic():
        for course in courses:
            if EEJTPStatus.objects.filter(
                employee_wwid=employee_wwid,
                assigned_pathway=pathway_name,
                course_name=course.course_name,
            ).exists():
                continue

            due = today + timedelta(days=course.expect_completion_time or 90)

            record = EEJTPStatus.objects.create(
                # Composite DB primary-key fields (format matches existing rows)
                wwid_pathway_coursename = f'{employee_wwid}_{pathway_name}_{course.course_name}',
                wwid_pathway            = f'{employee_wwid}_{pathway_name}',
                pathway_coursename      = f'{pathway_name}_{course.course_name}',
                employee_wwid    = employee_wwid,
                employee_name    = employee_info.get('name', ''),
                employee_email   = employee_info.get('email', ''),
                mgr_name         = employee_info.get('mgr_name', ''),
                mgr_wwid         = employee_info.get('mgr_wwid', ''),
                org_unit_descr   = employee_info.get('org_unit_descr', ''),
                org_level_desc7  = employee_info.get('org_level_desc7', ''),
                assigned_pathway = pathway_name,
                course_name      = course.course_name,
                course_id        = course.course_id,  # float or None
                course_type      = course.course_type or 'WBT',
                assigned_date    = today.strftime('%Y-%m-%d'),  # store as text
                due_date         = due.strftime('%Y-%m-%d'),    # store as text
                status           = None,
                manually_confirmed = False,
            )
            created.append(record)

        # Ensure team-member record exists so employee appears on My Team even
        # before any course is completed.
        mgr_wwid = employee_info.get('mgr_wwid', '')
        if mgr_wwid:
            JTPTeamMember.objects.get_or_create(
                mgr_wwid=mgr_wwid,
                employee_wwid=employee_wwid,
                defaults={
                    'employee_name':  employee_info.get('name', ''),
                    'employee_email': employee_info.get('email', ''),
                },
            )

    return created


def remove_pathway_from_employee(pathway_name: str, employee_wwid: str) -> int:
    """
    Remove ALL courses of a pathway from an employee (both pending and completed).
    Called when a manager explicitly unassigns a pathway from an employee's profile.
    """
    deleted, _ = EEJTPStatus.objects.filter(
        employee_wwid=employee_wwid,
        assigned_pathway=pathway_name,
    ).delete()
    return deleted


# ─────────────────────────────────────────────────────────────────────────────
# Pathway change propagation
# ─────────────────────────────────────────────────────────────────────────────

def propagate_course_addition(pathway_name: str, course: JTPPathway) -> int:
    """
    After a new course is added to a pathway, create EEJTPStatus rows for all
    employees who already have that pathway assigned.
    """
    assigned_wwids = (
        EEJTPStatus.objects.filter(assigned_pathway=pathway_name)
        .values('employee_wwid', 'employee_name', 'employee_email',
                'mgr_name', 'mgr_wwid', 'org_unit_descr', 'org_level_desc7',
                'assigned_date')
        .distinct()
    )

    created = 0
    for row in assigned_wwids:
        wwid = row['employee_wwid']
        if EEJTPStatus.objects.filter(
            employee_wwid=wwid,
            assigned_pathway=pathway_name,
            course_name=course.course_name,
        ).exists():
            continue

        # assigned_date stored as TEXT in DB; parse before arithmetic.
        # Fall back to today if the field is missing or unparseable.
        raw_ad = row['assigned_date']
        assigned_date = (get_completion_date_obj(str(raw_ad)) if raw_ad else None) or date.today()
        due = assigned_date + timedelta(days=course.expect_completion_time or 90)

        EEJTPStatus.objects.create(
            # Composite DB primary-key fields
            wwid_pathway_coursename = f'{wwid}_{pathway_name}_{course.course_name}',
            wwid_pathway            = f'{wwid}_{pathway_name}',
            pathway_coursename      = f'{pathway_name}_{course.course_name}',
            employee_wwid    = wwid,
            employee_name    = row['employee_name'],
            employee_email   = row['employee_email'],
            mgr_name         = row['mgr_name'],
            mgr_wwid         = row['mgr_wwid'],
            org_unit_descr   = row['org_unit_descr'],
            org_level_desc7  = row['org_level_desc7'],
            assigned_pathway = pathway_name,
            course_name      = course.course_name,
            course_id        = course.course_id,  # float or None
            course_type      = course.course_type or 'WBT',
            assigned_date    = assigned_date.strftime('%Y-%m-%d'),  # store as text
            due_date         = due.strftime('%Y-%m-%d'),            # store as text
            status           = None,
            manually_confirmed = False,
        )
        created += 1

    return created


def propagate_course_removal(pathway_name: str, course_name: str) -> int:
    """Remove incomplete status rows when a course is deleted from a pathway."""
    deleted, _ = EEJTPStatus.objects.filter(
        assigned_pathway=pathway_name,
        course_name=course_name,
    ).filter(Q(status__isnull=True) | Q(status='')).delete()
    return deleted


def remove_all_pending_for_pathway(pathway_name: str) -> int:
    """Remove ALL pending (not-yet-completed) EE_JTP_Status rows for an entire pathway.
    Used when deleting a pathway entirely. Completed records are preserved for audit.
    """
    deleted, _ = EEJTPStatus.objects.filter(
        assigned_pathway=pathway_name,
    ).filter(Q(status__isnull=True) | Q(status='')).delete()
    return deleted


def propagate_course_update(
    pathway_name: str,
    old_course_name: str,
    updated_fields: dict,
) -> int:
    """
    After a course in a pathway is edited, propagate changes to all open
    (not-yet-completed) EEJTPStatus records.
    """
    records = EEJTPStatus.objects.filter(
        assigned_pathway=pathway_name,
        course_name=old_course_name,
    ).filter(Q(status__isnull=True) | Q(status=''))

    updated = 0
    for record in records:
        changed = False

        new_name = updated_fields.get('course_name')
        if new_name and new_name != old_course_name:
            record.course_name = new_name
            changed = True

        new_type = updated_fields.get('course_type')
        if new_type and new_type != record.course_type:
            record.course_type = new_type
            changed = True

        new_cid = updated_fields.get('course_id')
        if new_cid is not None and new_cid != record.course_id:
            record.course_id = new_cid
            changed = True

        new_expect = updated_fields.get('expect_completion_time')
        if new_expect and record.assigned_date:
            # assigned_date is stored as TEXT in DB; parse before arithmetic
            ad_obj = get_completion_date_obj(str(record.assigned_date))
            if ad_obj:
                new_due_str = (ad_obj + timedelta(days=new_expect)).strftime('%Y-%m-%d')
                if new_due_str != record.due_date:
                    record.due_date = new_due_str
                    changed = True

        if changed:
            record.save()
            updated += 1

    return updated


# ─────────────────────────────────────────────────────────────────────────────
# Team & department overview
# ─────────────────────────────────────────────────────────────────────────────

def get_team_overview(mgr_wwid: str) -> list[dict]:
    """
    Return a list of dicts, one per employee under *mgr_wwid*.
    JTPTeamMember is the single source of team membership; EEJTPStatus
    is only queried for pathway-progress data.
    Removing a JTPTeamMember record fully removes the employee from the view.
    """
    result = []
    for tm in JTPTeamMember.objects.filter(mgr_wwid=mgr_wwid):
        wwid = str(tm.employee_wwid)  # normalise to str (avoids int vs str key clash)
        pathways = get_employee_pathway_completion(wwid)
        fully_complete = bool(pathways) and all(
            p['is_fully_complete'] for p in pathways.values()
        )
        result.append({
            'wwid':           wwid,
            'name':           tm.employee_name,
            'email':          tm.employee_email,
            'pathways':       pathways,
            'pathway_count':  len(pathways),
            'fully_complete': fully_complete,
            'has_pathways':   len(pathways) > 0,
        })

    result.sort(key=lambda x: x['name'].lower())
    return result


def get_department_overview() -> list[dict]:
    """
    Return per-manager completion stats grouped by department (org_level_desc7).
    Uses jtp_team_members as the authoritative source for team membership so
    every manager with enrolled employees is visible, even before pathway assignment.
    Department Managers (role='DM') are excluded.

    Performance: exactly 2–3 DB queries regardless of how many managers / employees
    exist, by bulk-loading all rows and computing stats in Python.
    """
    from collections import defaultdict

    # ── Query 1: all team-member rows ────────────────────────────────────────────
    all_members = list(JTPTeamMember.objects.all().values(
        'mgr_wwid', 'employee_wwid', 'employee_name', 'employee_email',
        'org_unit_descr', 'org_level_desc7', 'role',
    ))

    if not all_members:
        return []

    # Build lookup structures in pure Python (no extra queries)
    # name_map lets us resolve a manager's display name from their own employee record
    name_map: dict[str, str] = {m['employee_wwid']: m['employee_name'] for m in all_members}
    by_mgr:   dict[str, list]  = defaultdict(list)
    org_map:  dict[str, tuple] = {}   # mgr_wwid → (org_unit_descr, org_level_desc7)

    for m in all_members:
        by_mgr[m['mgr_wwid']].append(m)
        if m['mgr_wwid'] not in org_map:
            org_map[m['mgr_wwid']] = (
                m['org_unit_descr']  or '',
                m['org_level_desc7'] or '',
            )

    mgr_wwids: set[str] = set(by_mgr.keys())

    # Fallback: managers whose mgr_wwid isn't found as an employee in jtp_team_members
    # (edge case — at most one extra query, and only when there are gaps).
    missing = mgr_wwids - set(name_map.keys())
    if missing:
        # ── Query 1b (conditional): fetch mgr_name from EEJTPStatus for unknown managers
        for row in (
            EEJTPStatus.objects
            .filter(mgr_wwid__in=missing)
            .values('mgr_wwid', 'mgr_name')
            .distinct()
        ):
            name_map.setdefault(row['mgr_wwid'], row['mgr_name'] or '')

    # ── Query 2: per-(employee, pathway) completion counts ──────────────────────
    all_emp_wwids = {m['employee_wwid'] for m in all_members}
    pathway_rows = (
        EEJTPStatus.objects
        .filter(employee_wwid__in=all_emp_wwids)
        .exclude(assigned_pathway='').exclude(assigned_pathway__isnull=True)
        .values('employee_wwid', 'assigned_pathway')
        .annotate(
            total=Count('id'),
            completed=Count('id', filter=Q(status__isnull=False) & ~Q(status='')),
        )
    )

    # Group: str(wwid) → {pathway_name: {total, completed}}
    ee_stats: dict[str, dict] = defaultdict(dict)
    for row in pathway_rows:
        ee_stats[str(row['employee_wwid'])][row['assigned_pathway']] = {
            'total':     row['total'],
            'completed': row['completed'],
        }

    # ── Compute per-manager summary in pure Python ───────────────────────────
    managers: list[dict] = []
    for mgr_wwid in mgr_wwids:
        members = by_mgr[mgr_wwid]
        org_unit_descr, org_level_desc7 = org_map.get(mgr_wwid, ('', ''))

        # Exclude the absolute top-level dept head: their direct reports carry no
        # org_level_desc7 data (they sit above any sub-department subdivision).
        if not org_level_desc7:
            continue

        mgr_name = name_map.get(mgr_wwid, '')

        total_members = len(members)
        assigned_size = 0
        done          = 0

        for m in members:
            wwid     = str(m['employee_wwid'])
            pathways = ee_stats.get(wwid, {})
            if not pathways:
                continue
            assigned_size += 1
            if all(p['total'] > 0 and p['completed'] == p['total'] for p in pathways.values()):
                done += 1

        pct = int(done / assigned_size * 100) if assigned_size else 0
        managers.append({
            'mgr_wwid':             mgr_wwid,
            'mgr_name':             mgr_name,
            'org_unit_descr':       org_unit_descr,
            'org_level_desc7':      org_level_desc7,
            'total_members':        total_members,
            'team_size':            assigned_size,
            'fully_complete_count': done,
            'team_pct':             pct,
        })

    managers.sort(key=lambda x: (x['org_level_desc7'].lower(), x['mgr_name'].lower()))
    return managers


# ─────────────────────────────────────────────────────────────────────────────
# Permission helpers
# ─────────────────────────────────────────────────────────────────────────────

def is_admin(request) -> bool:
    """True if the current session user has admin credentials."""
    isid  = request.session.get('authenticated_user_isid', '')
    email = request.session.get('authenticated_user_email', '')
    wwid  = request.session.get('authenticated_user_wwid', '')

    if isid in settings.JTP_ADMIN_ISIDS:
        return True
    if email in settings.JTP_ADMIN_EMAILS:
        return True

    if isid or email or wwid:
        return JTPAdminUser.objects.filter(
            Q(isid=isid) | Q(email=email) | Q(wwid=wwid)
        ).exists()

    return False


def is_manager(request) -> bool:
    """True if the current user has any direct reports."""
    wwid = request.session.get('authenticated_user_wwid', '')
    if not wwid:
        return False
    return (
        EEJTPStatus.objects.filter(mgr_wwid=wwid).exists()
        or JTPTeamMember.objects.filter(mgr_wwid=wwid).exists()
    )


def can_modify_pathway(pathway_name: str, request) -> bool:
    """True if the user may edit or delete the given pathway."""
    if is_admin(request):
        return True
    wwid = request.session.get('authenticated_user_wwid', '')
    return bool(wwid) and JTPPathway.objects.filter(
        pathway_name=pathway_name, owner_wwid=wwid
    ).exists()


# ─────────────────────────────────────────────────────────────────────────────
# Employee info lookup
# ─────────────────────────────────────────────────────────────────────────────

def lookup_employee_info(employee_wwid: str) -> dict:
    """
    Try to find employee info from existing EE_JTP_Status records.
    Returns a dict with name, email, mgr_name, mgr_wwid, org_unit_descr,
    org_level_desc7 — or empty strings if not found.
    """
    rec = EEJTPStatus.objects.filter(employee_wwid=employee_wwid).first()
    if rec:
        return {
            'name':           rec.employee_name,
            'email':          rec.employee_email,
            'mgr_name':       rec.mgr_name,
            'mgr_wwid':       rec.mgr_wwid,
            'org_unit_descr': rec.org_unit_descr,
            'org_level_desc7':rec.org_level_desc7,
        }
    # Fall back to JTPTeamMember
    tm = JTPTeamMember.objects.filter(employee_wwid=employee_wwid).first()
    if tm:
        return {
            'name':           tm.employee_name,
            'email':          tm.employee_email,
            'mgr_name':       '',
            'mgr_wwid':       tm.mgr_wwid,
            'org_unit_descr': '',
            'org_level_desc7':'',
        }
    return {
        'name': '', 'email': '', 'mgr_name': '', 'mgr_wwid': '',
        'org_unit_descr': '', 'org_level_desc7': '',
    }
