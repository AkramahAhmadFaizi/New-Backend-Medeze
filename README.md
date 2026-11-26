# Therapy Platform API (FastAPI + Supabase)

Backend layer between callers (Postman / future frontend) and Supabase.
Status: **phone OTP + clients create/read/update.** No auth yet: local only, do not deploy.

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
  validate.py           shared field types + allowed values (all schemas use these)
  schemas/clients.py    ClientCreate, ClientUpdate (input), ClientOut (output)
  services/clients.py   create / get / update logic
  services/otp.py       OTP rate limits, audit rows, token issue
  integrations/otp_provider.py   Fake + 2Factor providers (adapter)
  tokens.py             short-lived token after OTP (JWT)
  deps.py               require_phone_token dependency
  routers/health.py     GET /health, GET /health/db
  routers/otp.py        POST /auth/otp/send, POST /auth/otp/verify
  routers/clients.py    POST /clients, GET /clients/{id}, PATCH /clients/{id}
tests/test_validate.py   unit tests for validate.py (no DB needed)
therapy-api.postman_collection.json   import into Postman
```

## Endpoints
| Method | Path | Notes |
|---|---|---|
| POST | /auth/otp/send | `{phone}` -> 202. Same answer for any number. Rate limited |
| POST | /auth/otp/verify | `{phone, code}` -> `access_token` (15 min), `client_id`, `is_new_client` |
| POST | /clients | **Needs `Authorization: Bearer <access_token>`**; body phone must match the token. Required: phone, first_name, email, dob, source. Accepts `referral_code` (e.g. "PARTNERX"), not a UUID |
| GET | /clients/{id} | 404 if missing |
| PATCH | /clients/{id} | Only first_name, last_name, dob, email. Only last_name can be cleared with `null` |

## Rules enforced
- phone: international format; spaces/dashes stripped; unique (409 on duplicate)
- first_name: required, max 100 chars, spaces trimmed
- email: required, validated, stored lowercase, duplicates allowed (matches schema)
- dob: required, after 1900-01-01, not in the future
- last_name: optional
- source: match_form | whatsapp | web
- unknown fields rejected (e.g. phone_verified_at cannot be set by callers)
- phone, source, referral_code cannot be changed via PATCH

## Setup (Windows, VS Code terminal)
1. `powershell -ExecutionPolicy Bypass -File .\setup.ps1`
2. Fill in `.env` (SUPABASE_URL without /rest/v1, SUPABASE_SECRET_KEY = sb_secret_...)
3. `.\.venv\Scripts\Activate.ps1`
4. `uvicorn app.main:app --reload`   (restart manually after editing .env)

## Phone OTP
```
POST /auth/otp/send    -> code sent (fake provider: printed in the server terminal)
POST /auth/otp/verify  -> access_token
  is_new_client=true   -> POST /clients with the token
  is_new_client=false  -> client_id returned (phone_verified_at updated)
```
- Provider is chosen by `OTP_PROVIDER` in `.env`: `fake` (tests/local) or `2factor` (real SMS, India).
  Switching needs only `.env` changes. `fake` is refused when `APP_ENV=production`.
- Limits (configurable in `.env`): 3 sends/phone/10 min, 10 sends/IP/hour, 5 wrong codes per code,
  **50 sends/24h across all users** (budget guard), Indian numbers only (`+91`).
- Codes are never stored or logged by us. `otp_verifications` is an audit + rate-limit log.
- Still open: GET/PATCH /clients are not protected yet (local only).

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

## Run in Docker (local)
```
docker compose up --build
```
Swagger UI: http://localhost:8000/docs . Uses `.env`; Supabase and Medisina are remote, only the API runs in Docker.
Apply `db/migrations/V20261123150000__medisina_link.sql` first (`.\dblyway.ps1 migrate`).

## Database migrations
Schema changes go through Flyway. See `db/README.md`.

## Required client fields (DB check before migrating)
`V20261125150000__clients_required_fields.sql` sets NOT NULL on first_name, email, dob.
It fails (changing nothing) if any existing row is missing one. Check first:
```sql
select id, phone, first_name, email, dob from public.clients
where first_name is null or email is null or dob is null;
```
Must return 0 rows. Fix or remove test rows first.

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