"""
API endpoints for JTP Training Tracker.

Sections:
  1. Auth endpoints (adapted from tegaf_home/api_views.py)
  2. JTP course / pathway actions
  3. Team management
"""
import json

from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .user_auth import (
    _normalize_isid, bootstrap_user_from_request,
    _log_page_visit_from_referer,
)
from .services import (
    sync_wbt_completions_for_employee,
    confirm_course_completion,
    assign_pathway_to_employee,
    remove_pathway_from_employee,
    propagate_course_addition,
    propagate_course_removal,
    remove_all_pending_for_pathway,
    propagate_course_update,
    can_modify_pathway,
    lookup_employee_info,
    is_admin,
)
from .models import (
    JTPPathway, EEJTPStatus, JTPTeamMember,
)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Auth endpoints
# ─────────────────────────────────────────────────────────────────────────────

@require_http_methods(['POST'])
def set_user_info(request):
    """Store user info sent from client-side JS into the session."""
    try:
        data = json.loads(request.body)

        isid       = _normalize_isid(data.get('isid', ''))
        email      = data.get('email', '')
        name       = data.get('name', '')
        wwid       = data.get('wwid', '')

        if not isid:
            return JsonResponse({'success': False, 'error': 'Missing ISID'}, status=400)
        if isid.endswith('$'):
            return JsonResponse({'success': False, 'error': 'Machine account not allowed'}, status=400)
        if not email:
            email = f'{isid}@intel.com'
        if not name:
            name = isid

        request.session['authenticated_user_isid']   = isid
        request.session['authenticated_user_email']  = email
        request.session['authenticated_user_name']   = name
        request.session['authenticated_user_wwid']   = wwid
        request.session['authenticated_user_source'] = 'client-hsdes'
        request.session.pop('auth_logout_requested', None)
        request.session.modified = True

        _log_page_visit_from_referer(request, user_email=email, user_name=name, wwid=wwid)

        return JsonResponse({'success': True, 'message': f'User {isid} authenticated'})

    except Exception as exc:
        return JsonResponse({'success': False, 'error': str(exc)}, status=500)


@require_http_methods(['POST'])
def auth_client_event(request):
    """Receive client-side auth diagnostics for server logging."""
    try:
        data = json.loads(request.body)
        print(
            f"[AuthClient] stage={data.get('stage')} status={data.get('status')} "
            f"path={data.get('path')} isid={_normalize_isid(data.get('isid','')) or '-'} "
            f"message={data.get('message','') or '-'}"
        )
        return JsonResponse({'success': True})
    except Exception as exc:
        return JsonResponse({'success': False}, status=500)


@require_http_methods(['POST'])
def bootstrap_user_session(request):
    """Same-origin bootstrap endpoint used on first page load."""
    is_auth, user_info, source = bootstrap_user_from_request(request, silent=False)

    if is_auth and user_info:
        _log_page_visit_from_referer(
            request,
            user_email=user_info.get('email', ''),
            user_name=user_info.get('displayName') or user_info.get('isid', ''),
            wwid=user_info.get('employeeId', ''),
        )

    return JsonResponse({
        'success':       is_auth,
        'authenticated': is_auth,
        'source':        source,
        'user':          user_info if is_auth else None,
    })


# ─────────────────────────────────────────────────────────────────────────────
# 2. Training actions
# ─────────────────────────────────────────────────────────────────────────────

@require_http_methods(['POST'])
def mark_course_complete(request):
    """Manually confirm completion for ILT / Other courses."""
    try:
        data       = json.loads(request.body)
        status_id  = int(data.get('status_id', 0))
        wwid       = request.session.get('authenticated_user_wwid', '')

        if not wwid:
            return JsonResponse({'success': False, 'error': 'Not authenticated'}, status=401)
        if not status_id:
            return JsonResponse({'success': False, 'error': 'Missing status_id'}, status=400)

        record = confirm_course_completion(
            status_id,
            requesting_wwid=wwid,
            admin_override=is_admin(request),
        )
        return JsonResponse({
            'success': True,
            'completion_display': record.completion_date_display,
        })

    except EEJTPStatus.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Record not found'}, status=404)
    except PermissionError as exc:
        return JsonResponse({'success': False, 'error': str(exc)}, status=403)
    except Exception as exc:
        return JsonResponse({'success': False, 'error': str(exc)}, status=500)


@require_http_methods(['POST'])
def assign_pathway(request):
    """Assign a pathway to an employee (manager action)."""
    try:
        data          = json.loads(request.body)
        pathway_name  = data.get('pathway_name', '').strip()
        employee_wwid = data.get('employee_wwid', '').strip()
        mgr_wwid      = request.session.get('authenticated_user_wwid', '')

        if not (pathway_name and employee_wwid):
            return JsonResponse({'success': False, 'error': 'Missing pathway_name or employee_wwid'}, status=400)
        if not mgr_wwid:
            return JsonResponse({'success': False, 'error': 'Not authenticated'}, status=401)

        # Look up employee info; override mgr_wwid with the current manager
        emp_info = lookup_employee_info(employee_wwid)
        emp_info['mgr_wwid'] = mgr_wwid
        emp_info['mgr_name'] = request.session.get('authenticated_user_name', '')

        # Allow manager to supply name/email for new employees
        if not emp_info['name']:
            emp_info['name']  = data.get('employee_name', employee_wwid)
        if not emp_info['email']:
            emp_info['email'] = data.get('employee_email', '')

        created = assign_pathway_to_employee(
            pathway_name, employee_wwid, emp_info, assigned_by_wwid=mgr_wwid
        )
        return JsonResponse({'success': True, 'courses_added': len(created)})

    except ValueError as exc:
        return JsonResponse({'success': False, 'error': str(exc)}, status=400)
    except Exception as exc:
        return JsonResponse({'success': False, 'error': str(exc)}, status=500)


@require_http_methods(['POST'])
def remove_pathway(request):
    """Remove a pathway's incomplete courses from an employee."""
    try:
        data          = json.loads(request.body)
        pathway_name  = data.get('pathway_name', '').strip()
        employee_wwid = data.get('employee_wwid', '').strip()
        mgr_wwid      = request.session.get('authenticated_user_wwid', '')

        if not (pathway_name and employee_wwid):
            return JsonResponse({'success': False, 'error': 'Missing fields'}, status=400)
        if not mgr_wwid:
            return JsonResponse({'success': False, 'error': 'Not authenticated'}, status=401)

        # Only the manager of the employee or an admin can remove
        record = EEJTPStatus.objects.filter(
            employee_wwid=employee_wwid, assigned_pathway=pathway_name
        ).first()
        if record and record.mgr_wwid != mgr_wwid and not is_admin(request):
            return JsonResponse({'success': False, 'error': 'Permission denied'}, status=403)

        deleted = remove_pathway_from_employee(pathway_name, employee_wwid)
        return JsonResponse({'success': True, 'deleted': deleted})

    except Exception as exc:
        return JsonResponse({'success': False, 'error': str(exc)}, status=500)


# ─────────────────────────────────────────────────────────────────────────────
# 3. Pathway CRUD
# ─────────────────────────────────────────────────────────────────────────────

@require_http_methods(['POST'])
def add_pathway_course(request):
    """Add a new course to a pathway (creates pathway if it doesn't exist)."""
    try:
        data         = json.loads(request.body)
        pathway_name = data.get('pathway_name', '').strip()
        course_name  = data.get('course_name', '').strip()
        course_type  = data.get('course_type', 'WBT')
        course_id    = data.get('course_id', '').strip()
        expect_time  = int(data.get('expect_completion_time', 90))
        refresh      = data.get('refresh_cycle')
        owner_wwid   = data.get('owner_wwid', '').strip()

        wwid = request.session.get('authenticated_user_wwid', '')
        if not wwid:
            return JsonResponse({'success': False, 'error': 'Not authenticated'}, status=401)

        if not (pathway_name and course_name):
            return JsonResponse({'success': False, 'error': 'pathway_name and course_name are required'}, status=400)

        # Check permission if pathway exists
        if JTPPathway.objects.filter(pathway_name=pathway_name).exists():
            if not can_modify_pathway(pathway_name, request):
                return JsonResponse({'success': False, 'error': 'Permission denied'}, status=403)

        # Duplicate course guard — avoids an IntegrityError that would break the
        # ATOMIC_REQUESTS transaction and return an HTML 500 to the client.
        if JTPPathway.objects.filter(pathway_name=pathway_name, course_name=course_name).exists():
            return JsonResponse({
                'success': False,
                'error': f'A course named "{course_name}" already exists in pathway "{pathway_name}".',
            }, status=200)

        # course_id defaults to '1' for "Other"
        if course_type == 'Other' and not course_id:
            course_id = '1'

        course = JTPPathway.objects.create(
            # DB primary-key field for JTP_Pathways
            pathway_coursename=f'{pathway_name}_{course_name}',
            pathway_name=pathway_name,
            course_name=course_name,
            course_id=course_id,
            course_type=course_type,
            expect_completion_time=expect_time,
            refresh_cycle=int(refresh) if refresh else None,
            owner_wwid=owner_wwid or wwid,
        )

        # Propagate to employees who already have this pathway
        added = propagate_course_addition(pathway_name, course)
        return JsonResponse({'success': True, 'course_id': course.pk, 'employees_updated': added})

    except Exception as exc:
        return JsonResponse({'success': False, 'error': str(exc)}, status=500)


@require_http_methods(['POST'])
def edit_pathway_course(request, course_id: int):
    """Edit a course within a pathway."""
    try:
        data = json.loads(request.body)
        wwid = request.session.get('authenticated_user_wwid', '')
        if not wwid:
            return JsonResponse({'success': False, 'error': 'Not authenticated'}, status=401)

        course = JTPPathway.objects.get(pk=course_id)

        if not can_modify_pathway(course.pathway_name, request):
            return JsonResponse({'success': False, 'error': 'Permission denied'}, status=403)

        old_name = course.course_name
        updated_fields: dict = {}

        if 'course_name' in data:
            course.course_name = data['course_name'].strip()
            updated_fields['course_name'] = course.course_name
        if 'course_type' in data:
            course.course_type = data['course_type']
            updated_fields['course_type'] = course.course_type
        if 'course_id' in data:
            course.course_id = data['course_id']
            updated_fields['course_id'] = course.course_id
        if 'expect_completion_time' in data:
            course.expect_completion_time = int(data['expect_completion_time'])
            updated_fields['expect_completion_time'] = course.expect_completion_time
        if 'refresh_cycle' in data:
            course.refresh_cycle = int(data['refresh_cycle']) if data['refresh_cycle'] else None

        course.save()

        emp_updated = propagate_course_update(course.pathway_name, old_name, updated_fields)
        return JsonResponse({'success': True, 'employees_updated': emp_updated})

    except JTPPathway.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Course not found'}, status=404)
    except Exception as exc:
        return JsonResponse({'success': False, 'error': str(exc)}, status=500)


@require_http_methods(['POST'])
def delete_pathway_course(request, course_id: int):
    """Delete a course from a pathway and remove it from employees."""
    try:
        wwid = request.session.get('authenticated_user_wwid', '')
        if not wwid:
            return JsonResponse({'success': False, 'error': 'Not authenticated'}, status=401)

        course = JTPPathway.objects.get(pk=course_id)

        if not can_modify_pathway(course.pathway_name, request):
            return JsonResponse({'success': False, 'error': 'Permission denied'}, status=403)

        pathway_name = course.pathway_name
        course_name  = course.course_name
        course.delete()

        removed = propagate_course_removal(pathway_name, course_name)
        return JsonResponse({'success': True, 'employees_updated': removed})

    except JTPPathway.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Course not found'}, status=404)
    except Exception as exc:
        return JsonResponse({'success': False, 'error': str(exc)}, status=500)


@require_http_methods(['POST'])
def edit_pathway(request):
    """Rename a pathway or change its owner."""
    try:
        data         = json.loads(request.body)
        pathway_name = data.get('pathway_name', '').strip()
        wwid         = request.session.get('authenticated_user_wwid', '')

        if not wwid:
            return JsonResponse({'success': False, 'error': 'Not authenticated'}, status=401)
        if not can_modify_pathway(pathway_name, request):
            return JsonResponse({'success': False, 'error': 'Permission denied'}, status=403)

        new_name      = data.get('new_pathway_name', '').strip()
        new_owner     = data.get('owner_wwid', '').strip()

        with transaction.atomic():
            courses = JTPPathway.objects.filter(pathway_name=pathway_name)
            if new_name and new_name != pathway_name:
                courses.update(pathway_name=new_name)
                EEJTPStatus.objects.filter(assigned_pathway=pathway_name).update(
                    assigned_pathway=new_name
                )
                pathway_name = new_name

            if new_owner:
                JTPPathway.objects.filter(pathway_name=pathway_name).update(owner_wwid=new_owner)

        return JsonResponse({'success': True, 'new_pathway_name': pathway_name})

    except Exception as exc:
        return JsonResponse({'success': False, 'error': str(exc)}, status=500)


@require_http_methods(['POST'])
def delete_pathway(request):
    """Delete an entire pathway and all pending employee records."""
    try:
        data         = json.loads(request.body)
        pathway_name = data.get('pathway_name', '').strip()
        wwid         = request.session.get('authenticated_user_wwid', '')

        if not wwid:
            return JsonResponse({'success': False, 'error': 'Not authenticated'}, status=401)
        if not can_modify_pathway(pathway_name, request):
            return JsonResponse({'success': False, 'error': 'Permission denied'}, status=403)

        with transaction.atomic():
            JTPPathway.objects.filter(pathway_name=pathway_name).delete()
            remove_all_pending_for_pathway(pathway_name)

        return JsonResponse({'success': True})

    except Exception as exc:
        return JsonResponse({'success': False, 'error': str(exc)}, status=500)


# ─────────────────────────────────────────────────────────────────────────────
# 4. Team management
# ─────────────────────────────────────────────────────────────────────────────

@require_http_methods(['POST'])
def remove_course(request):
    """Remove a single EEJTPStatus row from an employee's training profile."""
    try:
        data      = json.loads(request.body)
        status_id = data.get('status_id')
        mgr_wwid  = (request.session.get('authenticated_user_wwid', '')
                     or request.session.get('authenticated_user_isid', ''))

        if not mgr_wwid:
            return JsonResponse({'success': False, 'error': 'Not authenticated'}, status=401)
        if not status_id:
            return JsonResponse({'success': False, 'error': 'status_id required'}, status=400)

        record = EEJTPStatus.objects.filter(pk=status_id).first()
        if not record:
            return JsonResponse({'success': False, 'error': 'Record not found'}, status=404)

        # Allow if: logged-in user is the employee's manager OR an admin
        is_mgr = (
            str(record.mgr_wwid) == str(mgr_wwid)
            or JTPTeamMember.objects.filter(
                mgr_wwid=mgr_wwid, employee_wwid=str(record.employee_wwid)
            ).exists()
        )
        if not is_mgr and not is_admin(request):
            return JsonResponse({'success': False, 'error': 'Permission denied'}, status=403)

        record.delete()
        return JsonResponse({'success': True})

    except Exception as exc:
        return JsonResponse({'success': False, 'error': str(exc)}, status=500)


@require_http_methods(['GET'])
def employee_data(request, employee_wwid: str):
    """Return JSON summary of an employee's pathway progress (for manager modal)."""
    from .services import get_employee_pathway_completion
    wwid = request.session.get('authenticated_user_wwid', '')
    if not wwid:
        return JsonResponse({'success': False, 'error': 'Not authenticated'}, status=401)

    pathways = get_employee_pathway_completion(employee_wwid)
    # Simplify for JSON serialisation
    simplified = {}
    for pname, data in pathways.items():
        simplified[pname] = {
            'percentage': data['percentage'],
            'total':      data['total'],
            'completed':  data['completed'],
        }
    return JsonResponse({'success': True, 'pathways': simplified})
