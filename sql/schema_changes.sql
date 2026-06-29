-- =============================================================================
-- JTP Training Tracker — Schema Changes
-- Run this ONCE against vnat_teg_af_database before starting the Django app.
-- Schema: VNAT_TEGAF_JTP
-- =============================================================================

-- ── 1. Add primary-key columns if they don't exist ───────────────────────────

-- JTP_Pathways: add surrogate PK
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'VNAT_TEGAF_JTP'
          AND table_name   = 'JTP_Pathways'
          AND column_name  = 'id'
    ) THEN
        ALTER TABLE "VNAT_TEGAF_JTP"."JTP_Pathways"
            ADD COLUMN id SERIAL PRIMARY KEY;
    END IF;
END $$;

-- EE_JTP_Status: add surrogate PK
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'VNAT_TEGAF_JTP'
          AND table_name   = 'EE_JTP_Status'
          AND column_name  = 'id'
    ) THEN
        ALTER TABLE "VNAT_TEGAF_JTP"."EE_JTP_Status"
            ADD COLUMN id SERIAL PRIMARY KEY;
    END IF;
END $$;


-- ── 2. New columns for JTP_Pathways ──────────────────────────────────────────

ALTER TABLE "VNAT_TEGAF_JTP"."JTP_Pathways"
    ADD COLUMN IF NOT EXISTS course_type            VARCHAR(10)  NOT NULL DEFAULT 'WBT',
    ADD COLUMN IF NOT EXISTS expect_completion_time INTEGER      NOT NULL DEFAULT 90,
    ADD COLUMN IF NOT EXISTS refresh_cycle          INTEGER      NULL,
    ADD COLUMN IF NOT EXISTS owner_wwid             VARCHAR(50)  NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ADD COLUMN IF NOT EXISTS updated_at             TIMESTAMPTZ NOT NULL DEFAULT NOW();

-- Auto-update updated_at via trigger
CREATE OR REPLACE FUNCTION "VNAT_TEGAF_JTP".set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_jtp_pathways_updated_at ON "VNAT_TEGAF_JTP"."JTP_Pathways";
CREATE TRIGGER trg_jtp_pathways_updated_at
BEFORE UPDATE ON "VNAT_TEGAF_JTP"."JTP_Pathways"
FOR EACH ROW EXECUTE FUNCTION "VNAT_TEGAF_JTP".set_updated_at();


-- ── 3. New columns for EE_JTP_Status ─────────────────────────────────────────

ALTER TABLE "VNAT_TEGAF_JTP"."EE_JTP_Status"
    ADD COLUMN IF NOT EXISTS mgr_wwid            VARCHAR(50)  NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS course_id           VARCHAR(50)  NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS course_type         VARCHAR(10)  NOT NULL DEFAULT 'WBT',
    ADD COLUMN IF NOT EXISTS refresh_date        DATE         NULL,
    ADD COLUMN IF NOT EXISTS manually_confirmed  BOOLEAN      NOT NULL DEFAULT FALSE;

-- If the existing 'status' column is not VARCHAR, rename/convert it.
-- The app stores NULL (pending), 'YYYY-MM-DD', or legacy 'Completed'.
-- If status is currently a DATE type, cast it:
-- ALTER TABLE "VNAT_TEGAF_JTP"."EE_JTP_Status"
--     ALTER COLUMN status TYPE VARCHAR(50) USING status::text;


-- ── 4. Helpful indexes ───────────────────────────────────────────────────────

CREATE INDEX IF NOT EXISTS idx_ee_jtp_employee_wwid
    ON "VNAT_TEGAF_JTP"."EE_JTP_Status" (employee_wwid);

CREATE INDEX IF NOT EXISTS idx_ee_jtp_mgr_wwid
    ON "VNAT_TEGAF_JTP"."EE_JTP_Status" (mgr_wwid);

CREATE INDEX IF NOT EXISTS idx_ee_jtp_pathway
    ON "VNAT_TEGAF_JTP"."EE_JTP_Status" (assigned_pathway);

CREATE INDEX IF NOT EXISTS idx_ee_jtp_status
    ON "VNAT_TEGAF_JTP"."EE_JTP_Status" (status);

CREATE INDEX IF NOT EXISTS idx_jtp_pathways_pathway_name
    ON "VNAT_TEGAF_JTP"."JTP_Pathways" (pathway_name);


-- ── 5. Django-managed tables (created automatically by migrate) ───────────────
-- The following tables are created by Django migrations; no action needed here:
--   jtp_admin_users
--   jtp_team_members
--   jtp_access_log
--   django_migrations
--   django_session
--   (etc.)

-- ── 6. Verify ────────────────────────────────────────────────────────────────
SELECT
    table_name,
    column_name,
    data_type,
    is_nullable
FROM information_schema.columns
WHERE table_schema = 'VNAT_TEGAF_JTP'
  AND table_name IN ('JTP_Pathways', 'EE_JTP_Status')
ORDER BY table_name, ordinal_position;
