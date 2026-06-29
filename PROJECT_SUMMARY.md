# TEG-AF JTP Web App — Project Summary

## Overview

A Django-based internal web application for Intel's **Job Training Program (JTP)** tracking within the TEG-AF organization. The app allows employees to view their own training progress, managers to oversee their team's pathway completion, and admins to manage training pathways.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Django 6.0.5, Python 3.14 |
| Database | PostgreSQL (`vnat_teg_af_database`), schema `VNAT_TEGAF_JTP` (SSL required) |
| ORM driver | psycopg2-binary |
| Frontend | Bootstrap 5 + Bootstrap Icons + DataTables (all CDN) |
| Auth | Session-based; IIS headers → HSDES/Kerberos API → local-dev fallback |
| Sessions | `django.contrib.sessions.backends.db` |

---

## Project Requirements

### Pages

| Page | Route | Description |
|---|---|---|
| My Training | `/` | Employee's own pathway/course progress |
| My Team | `/my-team/` | Manager view — team members, pathway assignment |
| My Department | `/my-department/` | Dept-level completion overview grouped by manager |
| Manage Pathways | `/pathways/` | Admin/owner CRUD for JTP pathways and courses |
| Employee Profile | `/employee/<wwid>/` | Manager/admin view of individual employee's training |

### Key Features

- **WBT auto-sync**: On every index or profile page load, incomplete WBT courses are queried against the `inf_data` table and updated automatically if completed.
- **Pathway assignment**: Managers can assign a pathway (set of courses) to team members. Each course becomes an `EEJTPStatus` row.
- **Manual completion**: Managers/admins can mark ILT/Other courses as complete on behalf of employees.
- **Pathway management**: Admins/owners can create pathways, add/edit/remove courses. Changes propagate to all currently-assigned employees.
- **Team management**: Managers can add/remove members from their team. Removing a member also removes the pathway records they were assigned.

### Admin Users

- ISIDs: `hoangp5`, `ngocanhm`
- Emails: `hoang.phuc.thinh.nguyen@intel.com`, `ngoc.anh.minh.huynh@intel.com`

---

## Database Schema

### `JTP_Pathways` (managed=False)
- PK: `pathway_coursename` (text, format: `{pathway_name}_{course_name}`)
- Also has `id BIGSERIAL` as Django's ORM PK (added via `run_schema.py`)
- Key columns: `pathway_name`, `course_name`, `course_type`, `course_id` (bigint), `expect_completion_time`, `refresh_cycle`, `owner` (owner_wwid)

### `EE_JTP_Status` (managed=False)
- PK: `wwid_pathway_coursename` (text, format: `{wwid}_{pathway_name}_{course_name}`)
- Also has `id BIGSERIAL` as Django's ORM PK
- Key columns: `employee_wwid` (bigint in DB, TextField in ORM), `assigned_pathway`, `course_name`, `course_id` (double precision), `course_type`, `status` (text — completion date or null), `assigned_date`, `due_date`, `refresh_date` (all text), `mgr_wwid`, `manually_confirmed`

### `jtp_team_members` (managed=True)
- Stores manager → employee relationships independently of `EE_JTP_Status`

### `jtp_admin_users`, `jtp_access_log` (managed=True)

### `inf_data` (external, read-only)
- Columns: `wwid` (text), `Number_ID` (text), `Status` (text), `course_completion` (date), `wwid_course` (text)

---

## Configuration (`.env`)

```
DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASS, DB_SSLMODE
SCHEMA_NAME=VNAT_TEGAF_JTP
INF_DATA_TABLE="VNAT_TEGAF_JTP"."inf_data"
INF_DATA_COL_WWID=wwid
INF_DATA_COL_COURSE_ID=Number_ID
INF_DATA_COL_STATUS=Status
INF_DATA_COL_COMPLETION_DATE=course_completion
```

---

## Bug Fixes & Adjustments (Development Session)

### 1. WBT sync silent failure — wrong `inf_data` column names
**Problem:** `.env` defaults used `course_id`, `status`, `completion_date` but the actual `inf_data` table has `Number_ID`, `Status`, `course_completion`. Every sync silently caught the `column does not exist` error and updated 0 records.  
**Fix:**
- Updated `.env` with correct column names.
- Updated `settings.py` defaults to match.
- Changed `load_dotenv()` → `load_dotenv(override=True)` so Django's auto-reloader subprocess always picks up fresh `.env` values instead of inheriting stale parent-process env vars.

### 2. WBT sync type mismatch — float course_id vs integer in `inf_data`
**Problem:** `EE_JTP_Status.course_id` is `double precision` → Python `float` (e.g. `1543.0`). Direct comparison against `inf_data.Number_ID` (text) failed.  
**Fix:** In `sync_wbt_completions_for_employee`, convert `record.course_id` via `int(float(...))` and use `::bigint` cast in the SQL query; also cast `wwid` with `::text` for type-safe comparison.

### 3. "Back to My Team" broken after "Mark Complete"
**Problem:** `back_url` was set from `HTTP_REFERER`. After `markCourseComplete` called `location.reload()`, the referer became the employee detail page itself, so the back button looped back to the same page.  
**Fix:** Pass `?from=/my-team/` (or `/my-department/`) as a query parameter when linking to the employee profile from My Team. The view reads `request.GET.get('from', '')` with a whitelist check (`/my-team/`, `/my-department/`). Query params are preserved on `location.reload()`.

### 4. Remove from team — cascade to pathway records
**Feature request:** Removing an employee from a manager's team should also remove their assigned pathway records.  
**Implementation:**
- `remove_team_member` now wraps both deletes in `transaction.atomic()`.
- Only deletes `EEJTPStatus` rows where `mgr_wwid` matches the removing manager — preserves original-data records and records assigned by other managers.

### 5. Unassign pathway / remove course from employee profile
**Feature request:** Managers/admins should be able to unassign an entire pathway or remove a single course from an employee's profile.  
**Implementation:**
- **Unassign Pathway**: Added `Unassign` button in each pathway card header (visible when `viewing_as_manager=True`). Calls existing `POST /api/remove-pathway/`. Pending courses are deleted; completed records are preserved.
- **Remove Course**: Added trash-icon button per course row. New endpoint `POST /api/remove-course/` (accepts `status_id`). Checks that caller is the employee's manager (via `mgr_wwid` or `JTPTeamMember` lookup) or an admin. Removes the row from the DOM immediately without a full page reload.

### 6. Employee name/email blank after re-adding to team
**Problem:** After fix #4, `remove_team_member` was deleting **all** `EEJTPStatus` rows for an employee (not just manager-assigned ones). This wiped original-data records that `lookup_employee_info` relied on for name/email, causing blank name/email when the employee was re-added.  
**Fix:** Scoped the `EEJTPStatus` delete to `WHERE employee_wwid = X AND mgr_wwid = current_manager`.

---

## File Reference

| File | Purpose |
|---|---|
| `config/settings.py` | Django settings, DB config, inf_data column settings |
| `.env` | Environment variables (DB creds, inf_data column names) |
| `jtp/models.py` | ORM models for all tables |
| `jtp/views.py` | Page view functions (index, my_team, employee_detail, etc.) |
| `jtp/api_views.py` | REST API endpoints (mark complete, assign/remove pathway, team management) |
| `jtp/services.py` | Business logic (sync, pathway assignment, team overview) |
| `jtp/user_auth.py` | Auth middleware, session helpers, local-dev overrides |
| `jtp/urls.py` | URL routing |
| `jtp/templates/jtp/` | HTML templates (base, index, my_team, employee_detail, etc.) |
| `run_schema.py` | One-time schema migration (adds `id BIGSERIAL`, missing columns) |

---

## Running the App (Local Dev)

```powershell
# Start server
& "C:/Program Files/Python314/python.exe" manage.py runserver

# Apply migrations (managed tables only)
& "C:/Program Files/Python314/python.exe" manage.py migrate

# Seed admin users
& "C:/Program Files/Python314/python.exe" manage.py seed_admins

# System check
& "C:/Program Files/Python314/python.exe" manage.py check
```

The local-dev identity is controlled by `_LOCAL_DEV_OVERRIDES` in `jtp/user_auth.py`. `getpass.getuser()` returns the Windows username (e.g. `hoangp5`), which maps to WWID `11748293`.
