"""
Context processor: injects current-user info into every template.
"""
from .services import is_admin, is_manager


def jtp_user_context(request):
    wwid  = request.session.get('authenticated_user_wwid', '')
    email = request.session.get('authenticated_user_email', '')
    name  = request.session.get('authenticated_user_name', '')
    isid  = request.session.get('authenticated_user_isid', '')

    authenticated = bool(isid and not isid.endswith('$') and email)

    return {
        'current_user': {
            'wwid':             wwid,
            'email':            email,
            'name':             name,
            'isid':             isid,
            'is_authenticated': authenticated,
            'is_admin':         is_admin(request) if authenticated else False,
            'is_manager':       is_manager(request) if authenticated else False,
        }
    }
