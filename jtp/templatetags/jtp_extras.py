"""Custom template filters and tags for JTP Training Tracker."""
from django import template
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter
def progress_color(pct):
    """Return a Bootstrap bg- class based on completion percentage."""
    try:
        pct = int(pct)
    except (ValueError, TypeError):
        return 'bg-secondary'
    if pct == 100:
        return 'bg-success'
    if pct >= 60:
        return 'bg-info'
    if pct >= 30:
        return 'bg-warning'
    return 'bg-danger'


@register.filter
def format_days(days):
    """Convert integer days to human-readable string."""
    mapping = {90: '3 Months', 180: '6 Months', 360: '1 Year'}
    if days is None:
        return 'None'
    return mapping.get(int(days), f'{days} days')


@register.filter
def course_type_badge(course_type):
    """Return an HTML badge for course type."""
    colours = {
        'ILT':   'bg-primary',
        'WBT':   'bg-info text-dark',
        'Other': 'bg-secondary',
    }
    cls = colours.get(course_type, 'bg-secondary')
    return mark_safe(f'<span class="badge {cls}">{course_type}</span>')


@register.filter
def status_badge(status):
    """Return an HTML badge for a status value."""
    if not status:
        return mark_safe('<span class="badge bg-secondary">Pending</span>')
    s = str(status).strip()
    if s.lower() == 'completed':
        return mark_safe('<span class="badge bg-success">Completed</span>')
    # Try to detect ISO date
    try:
        from datetime import datetime
        d = datetime.strptime(s, '%Y-%m-%d').date()
        return mark_safe(f'<span class="badge bg-success">{d.strftime("%b %d, %Y")}</span>')
    except ValueError:
        pass
    return mark_safe(f'<span class="badge bg-success">{s}</span>')


@register.filter
def dict_get(d, key):
    """Access dict value by key in a template."""
    return d.get(key)


@register.simple_tag
def progress_bar(pct, small=False):
    """Render a Bootstrap progress bar."""
    from django.utils.safestring import mark_safe
    try:
        pct_int = int(pct)
    except (ValueError, TypeError):
        pct_int = 0
    colour = 'bg-success' if pct_int == 100 else ('bg-warning' if pct_int >= 50 else 'bg-danger')
    h = ' style="height:8px;"' if small else ''
    return mark_safe(
        f'<div class="progress"{h}>'
        f'<div class="progress-bar {colour}" role="progressbar" '
        f'style="width:{pct_int}%" aria-valuenow="{pct_int}" '
        f'aria-valuemin="0" aria-valuemax="100">{pct_int}%</div>'
        f'</div>'
    )
