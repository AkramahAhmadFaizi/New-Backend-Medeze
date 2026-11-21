# Medisina API contract (reference only)

This folder is **not** a backend. It only holds the contract for the Medisina API,
so its swagger file doesn't sit next to ours. All code that calls Medisina lives
in the main backend:

```
app/medisina/client.py       shared client: base URL, Bearer token, login/refresh
app/medisina/operations.py   every Medisina endpoint we call
app/schemas|services|routers usual layers, e.g. doctors.py
```

## Files
| File | What it is |
|---|---|
| `swagger.json` | Local copy of the contract for reading. Can go stale: re-pull it. |
| `contract.py` | Pull / show / check tool (uses the backend's venv) |

## The contract
- Source of truth: https://medisina-api-contracts-prod.s3.ap-south-2.amazonaws.com/swagger.json
- It is **refreshed in place** whenever Medisina changes.
- It has **no servers list**. The base URL comes from `MEDISINA_API_BASE_URL` in the main `.env`.
- Most endpoints need `Authorization: Bearer <token>`. The token comes from `POST /auth/login`
  (returns `token` + `refreshToken`) and is renewed with `POST /auth/refresh`.
  `app/medisina/client.py` does all of this automatically.
- Every response is `{"success": bool, "data": ..., "error": {"code", "message"}}`.

## Commands (run from the project root, venv active)
```
python portal-backend/contract.py pull                    # refresh swagger.json; then git diff it
python portal-backend/contract.py show "/doctors/search"  # one path, from the LIVE contract
python portal-backend/contract.py check                   # our operations.py vs the LIVE contract
```

## Adding a Medisina endpoint to the backend
1. `python portal-backend/contract.py show "<path>"` to see the method, params and response
2. `app/medisina/operations.py`: add an `Op(...)` and put it in `ALL_OPS`
3. `app/schemas/` → `app/services/` → `app/routers/` → `app/main.py` → Postman (same flow as `claude.md`)
4. `python portal-backend/contract.py check`
