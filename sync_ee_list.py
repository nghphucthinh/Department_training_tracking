"""
Standalone script: sync jtp_team_members from an EE list CSV.

Sync behaviour (keyed on employee_wwid):
  - New employees in the CSV  → inserted
  - Existing employees        → updated if any field changed
  - Employees absent from CSV → deleted

Usage:
    python sync_ee_list.py                         # uses EE_list.csv next to this file
    python sync_ee_list.py path/to/other_list.csv  # custom CSV path
"""
import csv
import os
import sys

# ── Bootstrap Django ──────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

import django
django.setup()
# ─────────────────────────────────────────────────────────────────────────────

from django.db import transaction
from jtp.models import JTPTeamMember

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


def sync(csv_path: str) -> None:
    if not os.path.isfile(csv_path):
        print(f'ERROR: CSV file not found: {csv_path}')
        sys.exit(1)

    print(f'Reading from: {csv_path}')

    # ── 1. Load CSV ───────────────────────────────────────────────────────────
    csv_data: dict[str, dict] = {}
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
        print('ERROR: CSV file produced no valid rows (check WWID / MGR_WWID columns).')
        sys.exit(1)

    # ── 2. Load existing DB records ───────────────────────────────────────────
    existing: dict[str, JTPTeamMember] = {
        str(tm.employee_wwid): tm
        for tm in JTPTeamMember.objects.all()
    }

    # ── 3. Compute changes ────────────────────────────────────────────────────
    csv_wwids = set(csv_data.keys())
    db_wwids  = set(existing.keys())

    to_create = []
    to_update = []          # list of (instance, [changed_field_names])
    to_delete = db_wwids - csv_wwids

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

    # ── 4. Apply in a single transaction ──────────────────────────────────────
    with transaction.atomic():
        deleted_count = 0
        if to_delete:
            deleted_count, _ = JTPTeamMember.objects.filter(
                employee_wwid__in=to_delete
            ).delete()

        JTPTeamMember.objects.bulk_create(to_create)

        for tm, changed_fields in to_update:
            tm.save(update_fields=changed_fields)

    # ── 5. Report ─────────────────────────────────────────────────────────────
    print(
        f'\nSync complete:'
        f'\n  {len(to_create):>4} inserted  (new employees)'
        f'\n  {len(to_update):>4} updated   (field changes)'
        f'\n  {deleted_count:>4} deleted   (no longer in CSV)'
        + (f'\n  {skipped:>4} skipped   (missing WWID or MGR_WWID)' if skipped else '')
    )


if __name__ == '__main__':
    csv_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(BASE_DIR, 'EE_list.csv')
    sync(csv_path)
