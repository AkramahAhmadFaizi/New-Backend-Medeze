# Therapy Platform API (FastAPI + Supabase)

Backend layer between callers (Postman / future frontend) and Supabase.
Also calls the **Medisina API** (doctors, slots). Its contract lives in [`portal-backend/`](portal-backend/README.md) (reference only, not a backend).

Status: **clients endpoints - create, read, update.** No auth yet: local only, do not deploy.

## Request flow
```
HTTP request
  -> routers/   URL + status code + which schema to use     (HTTP layer)
  -> schemas/   validate + normalize input (deserialize)    (Pydantic)
  -> services/  business rules, talks to Supabase or Medisina (logic layer)
  -> schemas/   shape the DB row into the response (serialize)
  -> errors.py  any failure becomes {"error": {...}}
```

## Layout
```
app/
  main.py               entry point, wires everything
  config.py             loads + validates .env
  db.py                 one shared Supabase client
  medisina/client.py    one shared Medisina client (base URL, Bearer token, login/refresh)
  medisina/operations.py  every Medisina endpoint we call
  errors.py             consistent error responses, DB error mapping
  validate.py           shared field types + allowed values (all schemas use these)
  schemas/clients.py    ClientCreate, ClientUpdate (input), ClientOut (output)
  services/clients.py   create / get / update logic
  schemas|services|routers/doctors.py   doctor list + slots (from Medisina)
  routers/health.py     GET /health, GET /health/db, GET /health/medisina
  routers/clients.py    POST /clients, GET /clients/{id}, PATCH /clients/{id}
tests/                 unit tests (no DB, no Medisina needed)
portal-backend/        Medisina API contract (swagger.json) + contract.py tool
therapy-api.postman_collection.json   import into Postman
```

## Endpoints
| Method | Path | Notes |
|---|---|---|
| POST | /clients | phone + source required. Accepts `referral_code` (e.g. "PARTNERX"), not a UUID |
| GET | /clients/{id} | 404 if missing |
| PATCH | /clients/{id} | Only first_name, last_name, dob, email. Send `null` to clear |
| GET | /doctors | From Medisina. Optional `q`, `specialty_id`, `city`, `language`, `limit` (1-100), `offset` |
| GET | /doctors/{doctor_id}/slots | From Medisina. Optional `date` (YYYY-MM-DD). Slots in UTC + doctor's local time |

## Rules enforced
- phone: international format; spaces/dashes stripped; unique (409 on duplicate)
- email: optional, validated, stored lowercase, duplicates allowed (matches schema)
- dob: optional, after 1900-01-01, not in the future
- source: match_form | whatsapp | web
- unknown fields rejected (e.g. phone_verified_at cannot be set by callers)
- phone, source, referral_code cannot be changed via PATCH

## Setup (Windows, VS Code terminal)
1. `powershell -ExecutionPolicy Bypass -File .\setup.ps1`
2. Fill in `.env` (SUPABASE_URL without /rest/v1, SUPABASE_SECRET_KEY = sb_secret_..., and the MEDISINA_* values)
3. `.\.venv\Scripts\Activate.ps1`
4. `uvicorn app.main:app --reload`   (restart manually after editing .env)

## Validation (app/validate.py)
Write field rules once, reuse everywhere. New schemas must import types from here:
`Phone`, `Email`, `Name`, `Dob`, `Timestamp`, `ReferralCode`, `CouponCode`, `Money`, `Url`, `TagList`, ...
plus `Optional*` variants and Literal types for every DB CHECK constraint.
All request models extend `InputModel` (rejects unknown fields).

## Tests
```
pip install -r requirements-dev.txt
pytest -v
```

## Medisina API
- `app/medisina/client.py` logs in (`POST /auth/login`), adds `Authorization: Bearer`, refreshes (`POST /auth/refresh`)
  before expiry and on 401, and unwraps Medisina's `{success, data, error}` envelope. Services never touch tokens.
- New Medisina endpoint: add an `Op` to `app/medisina/operations.py` first, then the usual schema -> service -> router flow.
- Contract tools: `python portal-backend/contract.py show "<path>" | check | pull` (see `portal-backend/README.md`).
- Errors: Medisina 4xx pass through as `medisina_<code>`; our login failing -> 502 `medisina_auth_failed`;
  down -> 502 `medisina_unreachable`; slow -> 504 `medisina_timeout`.

## Database migrations
Schema changes go through Flyway. See `db/README.md`.

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