"""
Models for the JTP Training Tracker.

Existing tables (managed=False — schema changes done via sql/schema_changes.sql):
  - JTPPathway   → "JTP_Pathways"
  - EEJTPStatus  → "EE_JTP_Status"

New Django-managed tables:
  - JTPAdminUser   → jtp_admin_users
  - JTPTeamMember  → jtp_team_members
  - JTPAccessLog   → jtp_access_log
"""
from django.db import models

# ── Choice constants ───────────────────────────────────────────────────────────
EXPECT_TIME_CHOICES = [
    (90,  '3 Months'),
    (180, '6 Months'),
    (360, '1 Year'),
]

REFRESH_CYCLE_CHOICES = [
    (90,  '3 Months'),
    (180, '6 Months'),
    (360, '1 Year'),
]

COURSE_TYPE_CHOICES = [
    ('ILT',   'ILT'),
    ('WBT',   'WBT'),
    ('Other', 'Other'),
]


# ─────────────────────────────────────────────────────────────────────────────
# Existing tables  (managed = False — Django reads/writes but never alters DDL)
# ─────────────────────────────────────────────────────────────────────────────

class JTPPathway(models.Model):
    """
    JTP_Pathways — one row per course within a pathway.
    The (pathway_name, course_name) pair uniquely identifies a course entry.
    """
    # pathway_coursename is the DB primary key but we use the BIGSERIAL 'id' column
    # as Django's PK (added via schema migration) for simpler ORM usage.
    pathway_coursename     = models.TextField(blank=True, default='')
    pathway_name           = models.TextField(blank=True, default='')
    course_name            = models.TextField(blank=True, default='')
    # course_id stored as bigint in DB; accessed as int, converted to str when needed
    course_id              = models.BigIntegerField(null=True, blank=True)
    course_type            = models.TextField(choices=COURSE_TYPE_CHOICES, default='WBT')
    # Store as integer days: 90 / 180 / 360 (bigint in DB)
    expect_completion_time = models.BigIntegerField(choices=EXPECT_TIME_CHOICES, default=90, null=True, blank=True)
    # NULL means no refresh required
    refresh_cycle          = models.BigIntegerField(choices=REFRESH_CYCLE_CHOICES, null=True, blank=True)
    # DB column is 'owner' — map via db_column
    owner_wwid             = models.TextField(blank=True, default='', db_column='owner')
    material               = models.TextField(blank=True, default='')
    created_at             = models.DateTimeField(auto_now_add=True)
    updated_at             = models.DateTimeField(auto_now=True)

    class Meta:
        managed  = False
        db_table = '"JTP_Pathways"'
        ordering = ['pathway_name', 'course_name']

    def __str__(self):
        return f'{self.pathway_name} › {self.course_name}'

    @property
    def expect_display(self):
        return dict(EXPECT_TIME_CHOICES).get(self.expect_completion_time, f'{self.expect_completion_time}d')

    @property
    def refresh_display(self):
        if not self.refresh_cycle:
            return 'None'
        return dict(REFRESH_CYCLE_CHOICES).get(self.refresh_cycle, f'{self.refresh_cycle}d')


class EEJTPStatus(models.Model):
    """
    EE_JTP_Status — one row per employee × pathway × course assignment.

    status field semantics:
      NULL / ''        → course not yet completed
      'YYYY-MM-DD'     → completed on that date
      'Completed'      → legacy completed record (no specific date)

    DB primary key is wwid_pathway_coursename (text composite) but we use the
    BIGSERIAL 'id' column as Django's PK for simpler ORM usage.
    assigned_date / due_date / refresh_date are stored as TEXT in the DB.
    employee_wwid is stored as BIGINT in DB (numeric WWID).
    """
    # Composite key fields (read-only, managed by DB)
    wwid_pathway_coursename = models.TextField(blank=True, default='')
    wwid_pathway            = models.TextField(blank=True, default='')
    pathway_coursename      = models.TextField(blank=True, default='')
    # Employee info
    employee_wwid    = models.TextField(blank=True, default='')  # bigint in DB, returned as int by psycopg2
    employee_name    = models.TextField(blank=True, default='')
    employee_email   = models.TextField(blank=True, default='')
    # Manager info
    is_manager       = models.TextField(blank=True, default='')
    mgr_name         = models.TextField(blank=True, default='')
    mgr_email        = models.TextField(blank=True, default='')
    mgr_wwid         = models.TextField(blank=True, default='')
    # Org info
    org_unit_descr   = models.TextField(blank=True, default='')
    org_level_desc7  = models.TextField(blank=True, default='')
    # Assignment info
    assigned_pathway = models.TextField(blank=True, default='')
    assigned_date    = models.TextField(blank=True, default='')  # stored as TEXT in DB
    due_date         = models.TextField(null=True,  blank=True)  # stored as TEXT in DB
    course_name      = models.TextField(blank=True, default='')
    course_id        = models.FloatField(null=True, blank=True)  # double precision in DB
    course_type      = models.TextField(blank=True, default='WBT')
    # status: NULL=pending, 'YYYY-MM-DD'=completed, 'Completed'=legacy
    status           = models.TextField(null=True, blank=True)
    # refresh_date stored as TEXT for consistency with assigned_date / due_date
    refresh_date     = models.TextField(null=True, blank=True)
    manually_confirmed = models.BooleanField(default=False)

    class Meta:
        managed  = False
        db_table = '"EE_JTP_Status"'
        ordering = ['employee_name', 'assigned_pathway', 'course_name']

    def __str__(self):
        return f'{self.employee_name} – {self.assigned_pathway} – {self.course_name}'

    @property
    def is_completed(self):
        return bool(self.status and str(self.status).strip())

    @property
    def completion_date_display(self):
        if not self.status:
            return None
        s = str(self.status).strip()
        if s.lower() == 'completed':
            return 'Completed'
        try:
            from datetime import date
            parts = s.split('-')
            if len(parts) == 3:
                d = date(int(parts[0]), int(parts[1]), int(parts[2]))
                return d.strftime('%b %d, %Y')
        except (ValueError, IndexError):
            pass
        return s


# ─────────────────────────────────────────────────────────────────────────────
# New Django-managed tables
# ─────────────────────────────────────────────────────────────────────────────

class JTPAdminUser(models.Model):
    """Users with full admin rights over all pathways."""
    # Use NULL for blank unique fields so multiple empty rows are allowed
    wwid  = models.CharField(max_length=50,  unique=True, null=True, blank=True)
    isid  = models.CharField(max_length=50,  unique=True, null=True, blank=True)
    email = models.CharField(max_length=255, unique=True, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'jtp_admin_users'

    def __str__(self):
        return self.email or self.isid or self.wwid or '<admin>'


class JTPTeamMember(models.Model):
    """
    Tracks all employees under each manager, even before any pathway is assigned.
    This allows the "My Team" page to show employees with no assignments.
    """
    mgr_wwid        = models.CharField(max_length=50)
    mgr_email       = models.CharField(max_length=255, blank=True, default='')
    employee_wwid   = models.CharField(max_length=50, unique=True)
    employee_name   = models.CharField(max_length=255)
    employee_email  = models.CharField(max_length=255, blank=True, default='')
    org_unit_descr  = models.CharField(max_length=255, blank=True, default='')
    org_level_desc7 = models.CharField(max_length=255, blank=True, default='')
    role            = models.CharField(max_length=50, blank=True, default='')
    module          = models.CharField(max_length=100, blank=True, default='')

    class Meta:
        db_table = 'jtp_team_members'

    def __str__(self):
        return f'{self.mgr_wwid} → {self.employee_name}'


class JTPAccessLog(models.Model):
    """Simple access log for page visits (mirrors tegaf_home.UserAccessLog)."""
    user_email  = models.CharField(max_length=255)
    user_name   = models.CharField(max_length=255, blank=True, default='')
    wwid        = models.CharField(max_length=50,  blank=True, default='')
    page_url    = models.CharField(max_length=512)
    accessed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'jtp_access_log'

    def __str__(self):
        return f'{self.user_email} → {self.page_url}'
