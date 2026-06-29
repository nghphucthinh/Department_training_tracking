"""
Adapted from tegaf_home/user_auth.py.
Handles session-based user authentication via IIS Windows Auth headers
and optional HSDES API lookup. Falls back to client-side auth overlay.
"""
import getpass
import json
import threading
from datetime import timedelta
from urllib.parse import urlparse

import requests
import urllib3
from django.core.cache import cache
from django.http import JsonResponse
from django.shortcuts import redirect
from django.utils import timezone
from django.views.decorators.http import require_POST

try:
    from requests_kerberos import HTTPKerberosAuth, OPTIONAL as KERBEROS_OPTIONAL
    KERBEROS_AVAILABLE = True
except ImportError:
    HTTPKerberosAuth = None
    KERBEROS_OPTIONAL = None
    KERBEROS_AVAILABLE = False

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_thread_locals = threading.local()

AUTH_SKIP_PATHS = [
    '/api/',
    '/favicon.ico',
    '/static/',
    '/media/',
    '/admin/',
    '/__debug__/',
]

LOGOUT_SUPPRESSION_SESSION_KEY = 'auth_logout_requested'
LOG_COOLDOWN_MINUTES = 30

JTP_LOGGED_PAGES = [
    '/',
    '/my-team/',
    '/my-department/',
    '/pathways/',
]


# ── Thread-local helpers ──────────────────────────────────────────────────────

def set_current_user_email(email: str):
    _thread_locals.current_user_email = email

def get_current_user_email() -> str:
    return getattr(_thread_locals, 'current_user_email', getpass.getuser())

def set_current_user_isid(isid: str):
    _thread_locals.current_user_isid = isid

def get_current_user_isid() -> str | None:
    return getattr(_thread_locals, 'current_user_isid', None)

def set_current_user_name(name: str):
    _thread_locals.current_user_name = name

def get_current_user_name() -> str:
    return getattr(_thread_locals, 'current_user_name', '')


# ── Normalization ─────────────────────────────────────────────────────────────

def _normalize_isid(isid: str) -> str:
    if not isid:
        return isid
    if '\\' in isid:
        isid = isid.split('\\')[-1]
    if '@' in isid:
        isid = isid.split('@')[0]
    return isid.strip()


def _is_auth_skip(path: str) -> bool:
    return any(path.startswith(p) for p in AUTH_SKIP_PATHS)


def _is_auto_auth_suppressed(session) -> bool:
    return bool(session.get(LOGOUT_SUPPRESSION_SESSION_KEY, False))


def _is_user_authenticated(session):
    user_isid  = _normalize_isid(session.get('authenticated_user_isid', ''))
    user_email = session.get('authenticated_user_email', '')
    user_name  = session.get('authenticated_user_name', '')

    # Sanitize double-domain emails
    if user_email.count('@') > 1:
        parts = user_email.split('@')
        user_email = parts[0] + '@' + parts[1]

    if user_isid and not user_isid.endswith('$') and user_email:
        return True, {
            'isid':        user_isid,
            'email':       user_email,
            'displayName': user_name,
            'employeeId':  session.get('authenticated_user_wwid', ''),
            'source':      session.get('authenticated_user_source', 'session'),
        }
    return False, None


def _get_request_user_isid(request) -> str:
    user_isid = (
        request.META.get('REMOTE_USER') or
        request.META.get('AUTH_USER') or
        request.META.get('LOGON_USER') or
        request.META.get('HTTP_X_REMOTE_USER') or
        ''
    )
    return _normalize_isid(user_isid)


def _build_fallback_user_info(isid: str) -> dict:
    clean = _normalize_isid(isid)
    # Local-dev user overrides — real info for developers running locally.
    _LOCAL_DEV_OVERRIDES = {
        'hoangp5': {
            'email':       'hoang.phuc.thinh.nguyen@intel.com',
            'displayName': 'Nguyen Hoang Phuc Thinh',
            'employeeId':  '11748293',
            'isid':        'hoangp5',
        },
        'ngocanhm': {
            'email':       'ngoc.anh.minh.huynh@intel.com',
            'displayName': 'Huynh Ngoc Anh Minh',
            'employeeId':  '',
            'isid':        'ngocanhm',
        },
    }
    if clean in _LOCAL_DEV_OVERRIDES:
        return _LOCAL_DEV_OVERRIDES[clean]
    return {
        'email':       f'{clean}@intel.com',
        'displayName': clean,
        'employeeId':  '',
        'isid':        clean,
    }


def _empty_user_info() -> dict:
    return {'email': '', 'displayName': '', 'employeeId': '', 'isid': ''}


def _parse_hsdes_user_response(payload: dict) -> dict:
    records = payload.get('data', [])
    if not isinstance(records, list) or not records:
        return _empty_user_info()
    user_data = records[0] if isinstance(records[0], dict) else {}
    return {
        'email':       user_data.get('sys_user.email', ''),
        'displayName': user_data.get('sys_user.name', ''),
        'employeeId':  user_data.get('sys_user.wwid', ''),
        'isid':        '',
    }


def _store_authenticated_user(request, user_info: dict, source: str = 'session'):
    request.session.pop(LOGOUT_SUPPRESSION_SESSION_KEY, None)
    request.session['authenticated_user_isid']       = user_info.get('isid', '')
    request.session['authenticated_user_email']      = user_info.get('email', '')
    request.session['authenticated_user_name']       = user_info.get('displayName', '')
    request.session['authenticated_user_wwid']       = user_info.get('employeeId', '')
    request.session['authenticated_user_source']     = source
    request.session.modified = True


def _is_local_request(request) -> bool:
    host = request.get_host().split(':', 1)[0].lower()
    return host in {'127.0.0.1', 'localhost'}


def _get_user_details_by_isid(isid: str, silent: bool = False) -> dict:
    """Fetch user details from HSDES API. Falls back to empty dict on failure."""
    cache_key = f'hsdes_user_{isid}'
    cached = cache.get(cache_key)
    if cached:
        return cached

    try:
        if not KERBEROS_AVAILABLE:
            if not silent:
                print('[HSDES] Kerberos not available — using fallback')
            return _build_fallback_user_info(isid)

        kbauth = HTTPKerberosAuth(mutual_authentication=KERBEROS_OPTIONAL)
        url    = f'https://hsdes-api.intel.com/rest/user/{isid}?expand=personal'
        resp   = requests.get(url, verify=False, auth=kbauth, timeout=10)

        if resp.status_code == 200:
            info = _parse_hsdes_user_response(resp.json())
            if any([info.get('email'), info.get('displayName'), info.get('employeeId')]):
                cache.set(cache_key, info, 3600)
                return info
        if not silent:
            print(f'[HSDES] HTTP {resp.status_code} for ISID {isid}')
    except Exception as exc:
        if not silent:
            print(f'[HSDES] Exception for ISID {isid}: {exc}')

    return _empty_user_info()


def bootstrap_user_from_request(request, silent: bool = False):
    """
    Attempt to identify the current user.
    Returns (is_authenticated, user_info | None, source_string).
    """
    if _is_auto_auth_suppressed(request.session):
        return False, None, 'logout-suppressed'

    # For local-dev requests: always re-apply overrides so stale session info is corrected.
    if _is_local_request(request):
        local_isid = _normalize_isid(getpass.getuser())
        if local_isid and not local_isid.endswith('$'):
            override = _build_fallback_user_info(local_isid)
            stored_name  = request.session.get('authenticated_user_name', '')
            stored_email = request.session.get('authenticated_user_email', '')
            expected_name  = override.get('displayName', '')
            expected_email = override.get('email', '')
            # Update session if name or email doesn't match the override
            if stored_name != expected_name or stored_email != expected_email:
                override['isid'] = local_isid
                _store_authenticated_user(request, override, source='local-dev')
                return True, override, 'local-dev'

    is_auth, user_info = _is_user_authenticated(request.session)
    if is_auth:
        return True, user_info, user_info.get('source', 'session')

    user_isid = _get_request_user_isid(request)
    if user_isid:
        if user_isid.endswith('$'):
            return False, None, 'machine-account'
        info = _get_user_details_by_isid(user_isid, silent=silent)
        info['isid'] = user_isid
        if not info.get('email'):
            info = _build_fallback_user_info(user_isid)
        _store_authenticated_user(request, info, source='iis')
        return True, info, 'iis'

    if _is_local_request(request):
        local_isid = _normalize_isid(getpass.getuser())
        if local_isid and not local_isid.endswith('$'):
            info = _get_user_details_by_isid(local_isid, silent=silent)
            if info.get('email'):
                info['isid'] = local_isid
                _store_authenticated_user(request, info, source='local-dev')
                return True, info, 'local-dev'
            fallback = _build_fallback_user_info(local_isid)
            _store_authenticated_user(request, fallback, source='local-dev')
            return True, fallback, 'local-dev'

    return False, None, 'none'


# ── Middleware ────────────────────────────────────────────────────────────────

class UserAccessLogMiddleware:
    """
    Sets request.current_user_* attributes on every request.
    Logs JTP page visits to jtp_access_log.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if _is_auth_skip(request.path):
            return self.get_response(request)

        should_log = any(
            request.path == p or (p != '/' and request.path.startswith(p))
            for p in JTP_LOGGED_PAGES
        )

        is_auth, user_info, source = bootstrap_user_from_request(request, silent=False)

        if is_auth and user_info:
            request.current_user_email  = user_info.get('email', '')
            request.current_user_name   = user_info.get('displayName', user_info.get('isid', ''))
            request.current_user_isid   = user_info.get('isid', '')
            request.current_user_wwid   = user_info.get('employeeId', '')
            request.is_user_authenticated = True
        else:
            request.current_user_email  = ''
            request.current_user_name   = ''
            request.current_user_isid   = ''
            request.current_user_wwid   = ''
            request.is_user_authenticated = False

        set_current_user_email(request.current_user_email)
        set_current_user_isid(request.current_user_isid)
        set_current_user_name(request.current_user_name)

        response = self.get_response(request)

        if should_log and is_auth and user_info:
            self._log_visit(request, user_info)

        return response

    def _log_visit(self, request, user_info: dict):
        session_key  = f'jtp_logged_{request.path}'
        last_logged  = request.session.get(session_key)
        if not isinstance(last_logged, str):
            last_logged = None
        now = timezone.now()
        if last_logged:
            try:
                elapsed = now - timezone.datetime.fromisoformat(last_logged)
                if elapsed < timedelta(minutes=LOG_COOLDOWN_MINUTES):
                    return
            except Exception:
                pass
        try:
            from .models import JTPAccessLog
            email = user_info.get('email', '')
            if email:
                JTPAccessLog.objects.create(
                    user_email  = email,
                    user_name   = user_info.get('displayName', ''),
                    wwid        = user_info.get('employeeId', ''),
                    page_url    = request.path,
                )
                request.session[session_key] = now.isoformat()
        except Exception as exc:
            print(f'[AccessLog] Failed: {exc}')


def _log_page_visit_from_referer(request, user_email: str, user_name: str,
                                  wwid: str = '', **_):
    referer = request.META.get('HTTP_REFERER', '')
    if not referer:
        return
    try:
        path = urlparse(referer).path
    except Exception:
        return

    if not any(path == p or (p != '/' and path.startswith(p)) for p in JTP_LOGGED_PAGES):
        return

    session_key = f'jtp_logged_{path}'
    last_logged = request.session.get(session_key)
    if not isinstance(last_logged, str):
        last_logged = None
    now = timezone.now()
    if last_logged:
        try:
            if (now - timezone.datetime.fromisoformat(last_logged)) < timedelta(minutes=LOG_COOLDOWN_MINUTES):
                return
        except Exception:
            pass
    try:
        from .models import JTPAccessLog
        if user_email:
            JTPAccessLog.objects.create(
                user_email=user_email,
                user_name=user_name,
                wwid=wwid,
                page_url=path,
            )
            request.session[session_key] = now.isoformat()
    except Exception as exc:
        print(f'[AccessLog] Referer log failed: {exc}')


# ── Auth API helpers (called from api_views) ──────────────────────────────────

def logout_view(request):
    """Clear session and redirect to homepage."""
    keys_to_clear = [
        'authenticated_user_isid',
        'authenticated_user_email',
        'authenticated_user_name',
        'authenticated_user_wwid',
        'authenticated_user_source',
    ]
    for key in keys_to_clear:
        request.session.pop(key, None)
    stale = [k for k in list(request.session.keys()) if k.startswith('jtp_logged_')]
    for k in stale:
        request.session.pop(k, None)
    request.session[LOGOUT_SUPPRESSION_SESSION_KEY] = True
    request.session.modified = True
    return redirect('/')
