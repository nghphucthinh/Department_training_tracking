"""Apply all missing JTP schema changes to the database."""
import os, sys
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
sys.path.insert(0, '.')
import django; django.setup()
from django.db import connection

S = 'VNAT_TEGAF_JTP'

stmts = [
    # ── id BIGSERIAL on JTP_Pathways (not PK, but unique auto-increment) ───
    f'ALTER TABLE "{S}"."JTP_Pathways" ADD COLUMN IF NOT EXISTS id BIGSERIAL',
    f'CREATE UNIQUE INDEX IF NOT EXISTS idx_jtp_pathways_id ON "{S}"."JTP_Pathways"(id)',

    # ── id BIGSERIAL on EE_JTP_Status ────────────────────────────────────────
    f'ALTER TABLE "{S}"."EE_JTP_Status" ADD COLUMN IF NOT EXISTS id BIGSERIAL',
    f'CREATE UNIQUE INDEX IF NOT EXISTS idx_ee_jtp_status_id ON "{S}"."EE_JTP_Status"(id)',

    # ── New columns for JTP_Pathways ─────────────────────────────────────────
    f"""ALTER TABLE "{S}"."JTP_Pathways"
        ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW(),
        ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW()""",

    # ── New columns for EE_JTP_Status ────────────────────────────────────────
    f"""ALTER TABLE "{S}"."EE_JTP_Status"
        ADD COLUMN IF NOT EXISTS mgr_wwid           TEXT NOT NULL DEFAULT '',
        ADD COLUMN IF NOT EXISTS course_type        TEXT NOT NULL DEFAULT 'WBT',
        ADD COLUMN IF NOT EXISTS refresh_date       TEXT,
        ADD COLUMN IF NOT EXISTS manually_confirmed BOOLEAN NOT NULL DEFAULT FALSE""",
]

with connection.cursor() as cur:
    for stmt in stmts:
        label = stmt.strip().replace('\n', ' ')[:90]
        print(f'Running: {label}')
        cur.execute(stmt)
        print('  OK')

print('\nAll schema changes applied successfully.')


