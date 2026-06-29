"""
Page views for JTP Training Tracker.
"""
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages

from .models import JTPPathway, EEJTPStatus, JTPTeamMember
from .services import (
    build_pathway_progress,
    get_team_overview,
    get_department_overview,
    sync_wbt_completions_for_employee,
    is_admin,
    is_manager,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _get_session_employee(request) -> dict:
    """Return basic employee info from session."""
    return {
        'name':  request.session.get('authenticated_user_name', ''),
        'wwid':  request.session.get('authenticated_user_wwid', ''),
        'email': request.session.get('authenticated_user_email', ''),
    }


def _is_numeric_wwid(val: str) -> bool:
    """Return True only for numeric WWIDs. Non-numeric ISIDs (local-dev) return False."""
    try:
        int(val)
        return True
    except (ValueError, TypeError):
        return False


def _get_employee_sidebar(wwid: str, request) -> dict:
    """
    Build the sidebar employee-info dict for an employee's profile.
    Priority:
      1. EEJTPStatus row  — most complete org/manager info
      2. JTPTeamMember row — always present after CSV sync, has name/email
      3. Bare fallback    — wwid only; name/email blank (never session data,
                            which would show the viewer's own info)
    """
    if _is_numeric_wwid(wwid):
        rec = EEJTPStatus.objects.filter(employee_wwid=wwid).first()
        if rec:
            return {
                'name':           rec.employee_name,
                'wwid':           rec.employee_wwid,
                'email':          rec.employee_email,
                'mgr_name':       rec.mgr_name,
                'org_unit_descr': rec.org_unit_descr,
                'org_level_desc7':rec.org_level_desc7,
            }

        tm = JTPTeamMember.objects.filter(employee_wwid=wwid).first()
        if tm:
            return {
                'name':           tm.employee_name,
                'wwid':           wwid,
                'email':          tm.employee_email,
                'mgr_name':       '',
                'org_unit_descr': tm.org_unit_descr,
                'org_level_desc7':tm.org_level_desc7,
            }

    # Last resort — show the wwid but leave name/email blank rather than
    # accidentally showing the logged-in viewer's own session data.
    return {
        'name':           '',
        'wwid':           wwid,
        'email':          '',
        'mgr_name':       '',
        'org_unit_descr': '',
        'org_level_desc7':'',
    }


# ─────────────────────────────────────────────────────────────────────────────
# Index — employee's own training dashboard
# ─────────────────────────────────────────────────────────────────────────────

def index(request):
    wwid  = request.session.get('authenticated_user_wwid', '')
    isid  = request.session.get('authenticated_user_isid', '')
    email = request.session.get('authenticated_user_email', '')

    # Require at least an ISID + email (WWID may be empty in local-dev)
    if not (isid and email):
        return render(request, 'jtp/index.html', {'page': 'index', 'needs_auth': True})

    # Use WWID when available, fall back to ISID so the view still works locally
    employee_id = wwid or isid

    # employee_wwid is BIGINT in DB — only query if it's numeric (skip for local-dev ISIDs)
    if _is_numeric_wwid(employee_id):
        sync_wbt_completions_for_employee(employee_id)
        records = EEJTPStatus.objects.filter(
            employee_wwid=employee_id
        ).exclude(assigned_pathway='').exclude(assigned_pathway__isnull=True).order_by('assigned_pathway', 'course_name')
    else:
        records = EEJTPStatus.objects.none()

    employee = _get_employee_sidebar(employee_id, request)
    pathways = build_pathway_progress(records)

    return render(request, 'jtp/index.html', {
        'page':           'index',
        'employee':       employee,
        'pathways':       pathways,
        'no_assignments': not records.exists(),
    })


# ─────────────────────────────────────────────────────────────────────────────
# Employee detail — manager or admin viewing someone else's profile
# ─────────────────────────────────────────────────────────────────────────────

def employee_detail(request, employee_wwid: str):
    mgr_wwid = request.session.get('authenticated_user_wwid', '') or \
               request.session.get('authenticated_user_isid', '')
    email    = request.session.get('authenticated_user_email', '')

    # Must be logged in
    if not (mgr_wwid and email):
        return render(request, 'jtp/employee_detail.html', {'needs_auth': True})

    # Authorization check
    if not is_admin(request):
        is_mgr_of = EEJTPStatus.objects.filter(
            employee_wwid=employee_wwid, mgr_wwid=mgr_wwid
        ).exists() or JTPTeamMember.objects.filter(
            mgr_wwid=mgr_wwid, employee_wwid=employee_wwid
        ).exists()
        if not is_mgr_of:
            messages.error(request, "You do not have permission to view this employee's profile.")
            return redirect('my_team')

    sync_wbt_completions_for_employee(employee_wwid)

    records  = EEJTPStatus.objects.filter(
        employee_wwid=employee_wwid
    ).exclude(assigned_pathway='').exclude(assigned_pathway__isnull=True).order_by('assigned_pathway', 'course_name')

    employee = _get_employee_sidebar(employee_wwid, request)
    pathways = build_pathway_progress(records)

    return render(request, 'jtp/employee_detail.html', {
        'page':           'my_team',
        'employee':       employee,
        'pathways':       pathways,
        'no_assignments': not records.exists(),
        'viewing_as_manager': True,
        'back_url':       request.GET.get('from', '') if request.GET.get('from', '') in ('/my-team/', '/my-department/') else '/my-team/',
    })


# ─────────────────────────────────────────────────────────────────────────────
# My Team
# ─────────────────────────────────────────────────────────────────────────────

def my_team(request):
    mgr_wwid = request.session.get('authenticated_user_wwid', '') or \
               request.session.get('authenticated_user_isid', '')

    if not mgr_wwid:
        return render(request, 'jtp/my_team.html', {'page': 'my_team', 'needs_auth': True})

    manager  = _get_employee_sidebar(mgr_wwid, request)
    team     = get_team_overview(mgr_wwid)
    # Percentage stats: only count employees who have at least one pathway assigned
    assigned = [e for e in team if e.get('has_pathways')]
    done_cnt = sum(1 for e in assigned if e['fully_complete'])
    team_pct = int(done_cnt / len(assigned) * 100) if assigned else 0

    available_pathways = (
        JTPPathway.objects.values_list('pathway_name', flat=True)
        .distinct()
        .order_by('pathway_name')
    )

    return render(request, 'jtp/my_team.html', {
        'page':               'my_team',
        'manager':            manager,
        'team':               team,
        'done_count':         done_cnt,
        'team_pct':           team_pct,
        'team_size':          len(assigned),   # sidebar shows assigned-only count
        'total_members':      len(team),       # full headcount for context
        'no_pathway_count':   len(team) - len(assigned),
        'available_pathways': available_pathways,
    })


# ─────────────────────────────────────────────────────────────────────────────
# My Department
# ─────────────────────────────────────────────────────────────────────────────

def my_department(request):
    isid  = request.session.get('authenticated_user_isid', '')
    email = request.session.get('authenticated_user_email', '')
    if not (isid and email):
        return render(request, 'jtp/my_department.html', {'page': 'my_department', 'needs_auth': True})

    dept_data  = get_department_overview()
    current_dept = ''

    # Determine the current user's department to highlight their section.
    # Try JTPTeamMember first (authoritative source), then fall back to EEJTPStatus.
    wwid = request.session.get('authenticated_user_wwid', '')
    if _is_numeric_wwid(wwid):
        tm = JTPTeamMember.objects.filter(employee_wwid=wwid).first()
        if tm and tm.org_level_desc7:
            current_dept = tm.org_level_desc7
        else:
            rec = EEJTPStatus.objects.filter(employee_wwid=wwid).first()
            if rec:
                current_dept = rec.org_level_desc7

    # Group by department
    from collections import defaultdict
    by_dept: dict = defaultdict(list)
    for mgr in dept_data:
        by_dept[mgr['org_level_desc7']].append(mgr)

    return render(request, 'jtp/my_department.html', {
        'page':         'my_department',
        'by_dept':      dict(by_dept),
        'current_dept': current_dept,
    })


# ─────────────────────────────────────────────────────────────────────────────
# Team detail — admin view of a specific manager's team
# ─────────────────────────────────────────────────────────────────────────────

def team_detail(request, mgr_wwid: str):
    """
    Show any manager's team page.  Accessible to admins and to the manager
    themselves (identified by session WWID).  Read-only: no add/remove actions.
    """
    current_wwid = request.session.get('authenticated_user_wwid', '') or \
                   request.session.get('authenticated_user_isid', '')
    email        = request.session.get('authenticated_user_email', '')

    if not (current_wwid and email):
        return render(request, 'jtp/my_team.html', {'page': 'my_department', 'needs_auth': True})

    if not is_admin(request) and current_wwid != mgr_wwid:
        messages.error(request, 'You do not have permission to view this team.')
        return redirect('my_department')

    manager  = _get_employee_sidebar(mgr_wwid, request)
    # If sidebar lookup gave us session data (wrong for another manager), fall
    # back to the team-member record so the correct name/email is shown.
    if manager.get('wwid') != mgr_wwid or not manager.get('name'):
        from jtp.models import JTPTeamMember as _TM
        own = _TM.objects.filter(employee_wwid=mgr_wwid).first()
        if own:
            manager = {
                'name':           own.employee_name,
                'wwid':           mgr_wwid,
                'email':          own.employee_email,
                'mgr_name':       '',
                'org_unit_descr': own.org_unit_descr,
                'org_level_desc7':own.org_level_desc7,
            }

    team     = get_team_overview(mgr_wwid)
    assigned = [e for e in team if e.get('has_pathways')]
    done_cnt = sum(1 for e in assigned if e['fully_complete'])
    team_pct = int(done_cnt / len(assigned) * 100) if assigned else 0

    available_pathways = (
        JTPPathway.objects.values_list('pathway_name', flat=True)
        .distinct()
        .order_by('pathway_name')
    )

    return render(request, 'jtp/my_team.html', {
        'page':               'my_department',
        'manager':            manager,
        'team':               team,
        'done_count':         done_cnt,
        'team_pct':           team_pct,
        'team_size':          len(assigned),
        'total_members':      len(team),
        'no_pathway_count':   len(team) - len(assigned),
        'available_pathways': available_pathways,
        'back_url':           '/my-department/',
        'read_only':          not is_admin(request),
    })


# ─────────────────────────────────────────────────────────────────────────────
# Pathway management
# ─────────────────────────────────────────────────────────────────────────────

def pathways_manage(request):
    wwid  = request.session.get('authenticated_user_wwid', '')
    isid  = request.session.get('authenticated_user_isid', '')
    email = request.session.get('authenticated_user_email', '')

    if not (isid and email):
        return render(request, 'jtp/pathways/manage.html', {'page': 'pathways', 'needs_auth': True})

    # Group courses by pathway name
    from collections import OrderedDict
    all_courses = JTPPathway.objects.all().order_by('pathway_name', 'course_name')
    pathways_dict: dict = OrderedDict()

    for course in all_courses:
        pname = course.pathway_name
        if pname not in pathways_dict:
            pathways_dict[pname] = {
                'name':       pname,
                'owner_wwid': course.owner_wwid,
                'courses':    [],
                'can_modify': False,
            }
        pathways_dict[pname]['courses'].append(course)

    # Set permission flag for each pathway
    user_is_admin = is_admin(request)
    current_id = wwid or isid  # use whichever identity is available
    for pname, data in pathways_dict.items():
        data['can_modify'] = user_is_admin or data['owner_wwid'] in (wwid, isid)

    return render(request, 'jtp/pathways/manage.html', {
        'page':          'pathways',
        'pathways_dict': pathways_dict,
        'is_admin':      user_is_admin,
        'current_wwid':  current_id,
        'course_types':  ['ILT', 'WBT', 'Other'],
        'expect_choices': [(90, '3 Months'), (180, '6 Months'), (360, '1 Year')],
        'refresh_choices': [(None, 'None'), (90, '3 Months'), (180, '6 Months'), (360, '1 Year')],
    })
