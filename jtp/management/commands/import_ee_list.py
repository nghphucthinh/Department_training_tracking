"""
Management command: sync jtp_team_members from an EE list CSV.

Sync behaviour (keyed on employee_wwid):
  - New employees in the CSV   → inserted
  - Existing employees         → updated if any field changed
  - Employees absent from CSV  → deleted

CSV expected columns (case-insensitive header):
    EMPLOYEE_NAME, WWID, EMPLOYEE_EMAIL, MGR_WWID, MGR_EMAIL,
    ORG_UNIT_DESCR, ORG_LEVEL_DESC7, ROLE, MODULE

Usage:
    python manage.py import_ee_list                         # uses EE_list.csv in project root
    python manage.py import_ee_list --csv path/to/file.csv
"""
import csv
import os

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from jtp.models import JTPTeamMember

# All syncable fields (everything except employee_wwid and created_at)
SYNC_FIELDS = [
    'mgr_wwid',
    'mgr_email',
    'employee_name',
    'employee_email',
    'org_unit_descr',
    'org_level_desc7',
    'role',
    'module',
]


def _row_to_dict(row: dict) -> dict:
    """Map normalised CSV row → field dict for JTPTeamMember."""
    return {
        'mgr_wwid':        row.get('MGR_WWID', ''),
        'mgr_email':       row.get('MGR_EMAIL', ''),
        'employee_name':   row.get('EMPLOYEE_NAME', ''),
        'employee_email':  row.get('EMPLOYEE_EMAIL', ''),
        'org_unit_descr':  row.get('ORG_UNIT_DESCR', ''),
        'org_level_desc7': row.get('ORG_LEVEL_DESC7', ''),
        'role':            row.get('ROLE', ''),
        'module':          row.get('MODULE', ''),
    }


class Command(BaseCommand):
    help = 'Sync jtp_team_members from an EE list CSV (add new, update changed, remove departed)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--csv',
            default=None,
            help='Path to the EE list CSV file (default: EE_list.csv in project root)',
        )

    def handle(self, *args, **options):
        csv_path = options['csv']
        if csv_path is None:
            csv_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
                    os.path.abspath(__file__)
                )))),
                'EE_list.csv',
            )

        if not os.path.isfile(csv_path):
            raise CommandError(f'CSV file not found: {csv_path}')

        self.stdout.write(f'Reading from: {csv_path}')

        # ── 1. Load CSV ────────────────────────────────────────────────────────
        csv_data: dict[str, dict] = {}   # employee_wwid → field dict
        skipped = 0

        with open(csv_path, newline='', encoding='utf-8-sig') as fh:
            reader = csv.DictReader(fh)
            for raw in reader:
                row = {k.strip().upper(): (v.strip() if v else '') for k, v in raw.items()}
                wwid     = row.get('WWID', '').strip()
                mgr_wwid = row.get('MGR_WWID', '').strip()
                if not wwid or not mgr_wwid:
                    skipped += 1
                    continue
                csv_data[wwid] = _row_to_dict(row)

        if not csv_data:
            raise CommandError('CSV file produced no valid rows (check WWID / MGR_WWID columns).')

        # ── 2. Load existing DB records ────────────────────────────────────────
        existing: dict[str, JTPTeamMember] = {
            str(tm.employee_wwid): tm
            for tm in JTPTeamMember.objects.all()
        }

        # ── 3. Compute changes ─────────────────────────────────────────────────
        csv_wwids = set(csv_data.keys())
        db_wwids  = set(existing.keys())

        to_create  = []
        to_update  = []   # list of (instance, [changed_fields])
        to_delete  = db_wwids - csv_wwids

        for wwid, fields in csv_data.items():
            if wwid not in existing:
                to_create.append(JTPTeamMember(employee_wwid=wwid, **fields))
            else:
                tm = existing[wwid]
                changed = [f for f in SYNC_FIELDS if getattr(tm, f) != fields[f]]
                if changed:
                    for f in changed:
                        setattr(tm, f, fields[f])
                    to_update.append((tm, changed))

        # ── 4. Apply within a single transaction ───────────────────────────────
        with transaction.atomic():
            # Deletions
            deleted_count = 0
            if to_delete:
                deleted_count, _ = JTPTeamMember.objects.filter(
                    employee_wwid__in=to_delete
                ).delete()

            # Inserts
            JTPTeamMember.objects.bulk_create(to_create)

            # Updates
            for tm, changed_fields in to_update:
                tm.save(update_fields=changed_fields)

        # ── 5. Report ──────────────────────────────────────────────────────────
        self.stdout.write(self.style.SUCCESS(
            f'\nSync complete:'
            f'\n  {len(to_create):>4} inserted  (new employees)'
            f'\n  {len(to_update):>4} updated   (field changes)'
            f'\n  {deleted_count:>4} deleted   (no longer in CSV)'
            + (f'\n  {skipped:>4} skipped   (missing WWID or MGR_WWID)' if skipped else '')
        ))
