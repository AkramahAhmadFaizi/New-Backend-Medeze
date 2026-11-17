# Database migrations (Flyway)

All schema changes go through numbered SQL files in `db/migrations/`.
**Do not change the schema in the Supabase SQL Editor or Table Editor anymore.**

## How it works
- Flyway records applied migrations in `flyway.flyway_schema_history`
  (its own `flyway` schema, not exposed by the Data API).
- `migrate` runs every file whose version is newer than the last applied one, in order.
- Each migration runs in a transaction: it fully applies or fully rolls back.

## Rules
1. Name files `V<number>__<description>.sql` (two underscores). Next number = highest + 1.
2. **Never edit a migration that has been applied.** Flyway stores a checksum;
   `validate` fails if a file changed. To fix something, write a new migration.
3. One logical change per migration.
4. `clean` (drops everything) is disabled. Keep it that way.

## Setup (once)
1. Docker Desktop running.
2. Copy `.env.flyway.example` to `.env.flyway`, fill in the Session pooler URL,
   user (`postgres.<project-ref>`) and the **database** password.

## Commands (from the project folder)
```
.\db\flyway.ps1 info       # what is applied / pending
.\db\flyway.ps1 validate   # applied files unchanged?
.\db\flyway.ps1 migrate    # apply pending migrations
```

## Adding a change
1. Create `db/migrations/V3__add_xyz.sql`
2. `.\db\flyway.ps1 migrate`, then `info` to confirm
3. Commit the file in the same PR as the code that needs it
## Team rules (several people change the schema)
1. Run `migrate` on the shared database ONLY from merged `dev`. Never from an unmerged branch.
2. Test a new migration on your own database first (second Supabase project or local Docker).
3. Name new files with a timestamp so they never collide:
   `V20261117143000__add_session_notes.sql` (V1 and V2 stay as they are).
4. Never edit a merged migration. Fix mistakes with a new file.
5. No schema changes in the SQL Editor or Table Editor. Ever.