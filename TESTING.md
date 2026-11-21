# Checking that it works (local Docker)

This guide runs everything on your own machine. Nothing touches the shared Supabase project.
Run each check in order. **If a check fails, fix it before going on**, because every later
check depends on the ones before it.

All commands run from the project folder in the VS Code PowerShell terminal.

---

## Part A: Is my setup working?

### A1. Docker is running
```powershell
docker ps
```
✅ A table header (possibly empty): `CONTAINER ID   IMAGE ...`
❌ `failed to connect to the docker API` -> start Docker Desktop and wait until it says *Running*.

### A2. Local Supabase is running
```powershell
npx supabase start
```
The first run downloads images and takes a few minutes.
✅ It prints a list that includes:
```
API URL:     http://127.0.0.1:54321
Studio URL:  http://127.0.0.1:54323
Secret key:  sb_secret_...      (older CLI versions call this "service_role key")
```
❌ `cannot find config.toml` -> run `npx supabase init` once, then `npx supabase start` again.

To see these values again later: `npx supabase status`.

### A3. `.env` points at local Supabase
`.env` must contain:
```
SUPABASE_URL=http://127.0.0.1:54321
SUPABASE_SECRET_KEY=<the Secret key / service_role key from A2>
```
- No `/rest/v1` at the end of the URL.
- Not the **Publishable** key. The app refuses to start with it.

### A4. The tables exist
Open Studio at http://127.0.0.1:54323, then **Table Editor**.
✅ You see `clients`, `coupons`, `coupon_redemptions`, `sessions`, ...
❌ No tables -> open **SQL Editor**, paste all of `db/migrations/V1__baseline.sql`, click **Run**.

### A5. Permissions and test data
In Studio **SQL Editor**, paste all of `db/seed/coupons_local.sql` and click **Run**.
It is safe to run again.
✅ `Success. No rows returned`
Check: **Table Editor -> coupons** shows WELCOME20, FLAT200, EXPIRED10, INACTIVE5, FUTURE15.

To also test the `/clients` endpoints, run this as well:
```sql
grant select, insert, update on public.clients to service_role;
grant select on public.referral_codes to service_role;
```

### A6. Unit tests pass (no database needed)
```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
pytest -q
```
✅ `37 passed` (or more)

### A7. The API starts
```powershell
uvicorn app.main:app --reload
```
✅ `Uvicorn running on http://127.0.0.1:8000`
❌ `ValidationError ... SUPABASE_URL` / `SUPABASE_SECRET_KEY` -> go back to A3.

Leave this terminal running. Open a **second** terminal for the next steps.

### A8. The server is up
```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```
✅ `status : ok`

### A9. The server can reach the database
```powershell
Invoke-RestMethod http://127.0.0.1:8000/health/db
```
✅ `database : ok`
❌ The response is 503, which PowerShell shows as an error. Read the message:

| Message contains | Fix |
|---|---|
| `ConnectError` / `connection refused` | Supabase is not running -> A2 |
| `42501` / `permission denied` | Run the grants -> A5 |
| `42P01` / `does not exist` | Tables missing -> A4 |
| `Invalid API key` / `401` | Wrong key in `.env` -> A3, then restart uvicorn |

**When A1 to A9 are green, your setup works.**

---

## Part B: Is the coupon flow working?

### B1. Swagger UI
Open http://127.0.0.1:8000/docs, then **coupons -> POST /coupons/check -> Try it out**.
Paste this body and click **Execute**:
```json
{
  "code": "welcome20",
  "client_id": "11111111-1111-1111-1111-111111111111",
  "amount": "1500.00"
}
```
✅ Response `200`:
```json
{
  "valid": true,
  "code": "WELCOME20",
  "discount_type": "percent",
  "discount_value": "20.00",
  "amount": "1500.00",
  "discount_amount": "250.00",
  "final_amount": "1250.00"
}
```
This checks three things at once:
- The lowercase code was accepted and uppercased.
- 20% of 1500 is 300, but the coupon caps the discount at 250.
- The final price is 1500 - 250 = 1250.

`client_id` is the test client that `coupons_local.sql` created.

### B2. Postman (all the cases in one click)
1. Postman -> **Import** -> `therapy-api.postman_collection.json`. If you imported it before,
   replace the old copy.
2. Right-click the folder **Coupons - check** -> **Run folder** -> **Run**.
3. Do the same for **Coupons - should fail**.

✅ Every test is green. This is what each request covers:

| Request | Expect | Error code |
|---|---|---|
| 1. Percent coupon, capped (WELCOME20, 1500) | 200, discount 250, final 1250 | - |
| 2. Flat coupon (FLAT200, 1500) | 200, discount 200, final 1300 | - |
| Unknown coupon | 404 | `coupon_not_found` |
| Unknown client | 404 | `client_not_found` |
| Below min amount (FLAT200, 500) | 422 | `below_min_amount` |
| Expired coupon (EXPIRED10) | 422 | `coupon_expired` |
| Inactive coupon (INACTIVE5) | 422 | `coupon_inactive` |
| Not started yet (FUTURE15) | 422 | `coupon_not_started` |
| Zero amount | 422 | `validation_error` |
| Unknown field (`discount_amount` sent) | 422 | `validation_error` |

Every error has the same shape:
```json
{"error": {"code": "coupon_expired", "message": "This coupon has expired."}}
```

### B3. Quick check from PowerShell (optional)
```powershell
$body = '{"code":"FLAT200","client_id":"11111111-1111-1111-1111-111111111111","amount":"1500.00"}'
Invoke-RestMethod -Method Post http://127.0.0.1:8000/coupons/check -ContentType 'application/json' -Body $body
```
✅ `discount_amount : 200.00` and `final_amount : 1300.00`

### B4. Checking is read-only
Run B1 several times. It keeps returning 200, and
**Table Editor -> coupon_redemptions** stays empty. Checking a coupon never uses it up.
Only booking a session, which is not built yet, creates a redemption.

**When B1 and B2 are green, the coupon flow works.**

---

## What is not tested yet
- `first_session_only`, `coupon_exhausted` and `client_limit_reached` need real sessions and
  redemptions in the database. The seed data does not create those yet, because they need a
  therapist and a slot first. These checks are in the code but not covered by Postman.
- `wrong_therapist` needs a coupon that has a `therapist_id`.

## Common problems
| Symptom | Cause / fix |
|---|---|
| Every coupon gives `coupon_not_found` | Seed not run on the database `.env` points at -> A5 |
| `db_permission` (500) | Grants missing -> A5 |
| A change in `.env` has no effect | uvicorn does not reload `.env`. Stop it (Ctrl+C) and start it again |
| `FUTURE15` returns 200 | The seed was run more than 30 days ago. Its start date is now in the past. That is expected |
| Port 54321 already in use | Another Supabase project is running. Run `npx supabase stop --all` |

## Stopping
```powershell
npx supabase stop     # keeps your local data
```
