# Therapy Platform API (FastAPI + Supabase)

Backend layer between callers (Postman / future frontend) and Supabase.
Status: **clients endpoints - create, read, update; coupon check.** No auth yet: local only, do not deploy.

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
  routers/health.py     GET /health, GET /health/db
  routers/clients.py    POST /clients, GET /clients/{id}, PATCH /clients/{id}
  schemas/coupons.py    CouponCheck (input), CouponCheckOut (output)
  services/coupons.py   coupon rules + discount math
  routers/coupons.py    POST /coupons/check
db/seed/coupons_local.sql   grants + test coupons (LOCAL Docker only)
tests/test_validate.py   unit tests for validate.py (no DB needed)
therapy-api.postman_collection.json   import into Postman
```

## Endpoints
| Method | Path | Notes |
|---|---|---|
| POST | /clients | phone + source required. Accepts `referral_code` (e.g. "PARTNERX"), not a UUID |
| GET | /clients/{id} | 404 if missing |
| PATCH | /clients/{id} | Only first_name, last_name, dob, email. Send `null` to clear |
| POST | /coupons/check | `code`, `client_id`, `amount` (+ `therapist_id` if coupon is therapist-specific). Read-only: returns discount + final price, reserves nothing |

## Rules enforced
- phone: international format; spaces/dashes stripped; unique (409 on duplicate)
- email: optional, validated, stored lowercase, duplicates allowed (matches schema)
- dob: optional, after 1900-01-01, not in the future
- source: match_form | whatsapp | web
- unknown fields rejected (e.g. phone_verified_at cannot be set by callers)
- phone, source, referral_code cannot be changed via PATCH

## Coupon check rules (in order)
404 `coupon_not_found` -> 422 `coupon_inactive` / `coupon_not_started` / `coupon_expired` /
`below_min_amount` / `wrong_therapist` -> 404 `client_not_found` -> 422 `first_session_only`
(client has a confirmed/completed/no_show session) / `coupon_exhausted` / `client_limit_reached`
(reserved + used redemptions count; released do not).
Percent discount is capped by `max_discount`; no discount ever exceeds the amount.

**Is it working?** Step-by-step checks for setup and the coupon flow: see [TESTING.md](TESTING.md).

## Setup (Windows, VS Code terminal)
1. `powershell -ExecutionPolicy Bypass -File .\setup.ps1`
2. Fill in `.env` (SUPABASE_URL without /rest/v1, SUPABASE_SECRET_KEY = sb_secret_...)
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

## Database migrations
Schema changes go through Flyway. See `db/README.md`.

## Troubleshooting
`db_permission` / 42501 -> run in Supabase SQL Editor:
```sql
grant select, insert, update on public.clients to service_role;
grant select on public.referral_codes to service_role;
grant select on public.coupons, public.coupon_redemptions, public.sessions to service_role;
```

## Security rules
- `.env` holds the secret key; it is git-ignored. Never commit or share it.
- The secret key bypasses RLS. It lives ONLY in this backend.
- Error responses include raw DB messages (`details.db`) for debugging. Remove before deploying.