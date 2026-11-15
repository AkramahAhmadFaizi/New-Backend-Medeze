# Therapy Platform API (FastAPI + Supabase)

Backend layer between callers (Postman / future frontend) and Supabase.
Status: **clients endpoints â€” create, read, update.** No auth yet: local only, do not deploy.

## Request flow
```
HTTP request
  -> routers/   URL + status code + which schema to use     (HTTP layer)
  -> schemas/   validate + normalize input (deserialize)    (Pydantic)
  -> services/  business rules, talks to Supabase           (logic layer)
  -> schemas/   shape the DB row into the response (serialize)
  -> errors.py  any failure becomes {"error": {...}}
```

## Layout
```
app/
  main.py               entry point, wires everything
  config.py             loads + validates .env
  db.py                 one shared Supabase client
  errors.py             consistent error responses, DB error mapping
  schemas/clients.py    ClientCreate, ClientUpdate (input), ClientOut (output)
  services/clients.py   create / get / update logic
  routers/health.py     GET /health, GET /health/db
  routers/clients.py    POST /clients, GET /clients/{id}, PATCH /clients/{id}
therapy-api.postman_collection.json   import into Postman
```

## Endpoints
| Method | Path | Notes |
|---|---|---|
| POST | /clients | phone + source required. Accepts `referral_code` (e.g. "PARTNERX"), not a UUID |
| GET | /clients/{id} | 404 if missing |
| PATCH | /clients/{id} | Only first_name, last_name, dob, email. Send `null` to clear |

## Rules enforced
- phone: international format; spaces/dashes stripped; unique (409 on duplicate)
- email: optional, validated, stored lowercase, duplicates allowed (matches schema)
- dob: optional, after 1900-01-01, not in the future
- source: match_form | whatsapp | web
- unknown fields rejected (e.g. phone_verified_at cannot be set by callers)
- phone, source, referral_code cannot be changed via PATCH

## Setup (Windows, VS Code terminal)
1. `powershell -ExecutionPolicy Bypass -File .\setup.ps1`
2. Fill in `.env` (SUPABASE_URL without /rest/v1, SUPABASE_SECRET_KEY = sb_secret_...)
3. `.\.venv\Scripts\Activate.ps1`
4. `uvicorn app.main:app --reload`   (restart manually after editing .env)

## Troubleshooting
`db_permission` / 42501 -> run in Supabase SQL Editor:
```sql
grant select, insert, update on public.clients to service_role;
grant select on public.referral_codes to service_role;
```

## Security rules
- `.env` holds the secret key; it is git-ignored. Never commit or share it.
- The secret key bypasses RLS. It lives ONLY in this backend.
- Error responses include raw DB messages (`details.db`) for debugging. Remove before deploying.