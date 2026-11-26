# Local dev environment (backend)

Run the backend in Docker on your own machine. There are two modes:

| Mode | Command | Database | Use it when |
|---|---|---|---|
| **Local DB** (recommended) | `.\dev.ps1 setup`, then `.\dev.ps1 up` | local Supabase on your machine (throwaway, fictional data) | building features, writing migrations, testing OTP |
| **Cloud DB** | `docker compose up --build` | the shared cloud Supabase from `.env` | you need the real shared data |

In both modes Medisina is the remote API from `.env`. Only our API (and in Local DB mode, Supabase) runs on your machine.

```
your machine
├── local Supabase (Supabase CLI, in Docker)    API :54321  DB :54322  Studio :54323   (Local DB mode)
└── docker compose (this repo)
    ├── api     FastAPI with live reload         http://localhost:8000/docs
    ├── flyway  applies db/migrations to the LOCAL db   (one-off, profile "tools")
    └── seed    loads db/seed/*.sql into the LOCAL db   (one-off, profile "tools")
```

## 1. Prerequisites (once per machine)

| Tool | Version | Check |
|---|---|---|
| Docker Desktop | running ("Engine running"), Compose 2.24+ | `docker compose version` |
| Node.js | 20 LTS or newer (runs the Supabase CLI through `npx`) | `node -v` |
| Git | any recent | `git --version` |
| PowerShell | 5.1 or 7 | `$PSVersionTable.PSVersion` |

You do **not** need Python or a venv for this. Python runs inside the `api` container.

If PowerShell refuses to run `dev.ps1`, allow local scripts for your user once:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

## 2. `.env` (both modes)

```powershell
Copy-Item .env.example .env
```

Fill in the `MEDISINA_*` values and the cloud `SUPABASE_*` values (ask the team).
`.env` is git-ignored. Never commit it.

## 3. Local DB mode: first-time setup

From the repo root:

```powershell
.\dev.ps1 setup
```

This:

1. checks Docker, Node, `supabase\config.toml` and `.env`,
2. starts local Supabase (the first run downloads ~1 GB of images),
3. writes `.env.docker` with the **local** Supabase key and a random `OTP_TOKEN_SECRET`,
4. builds the API image,
5. runs every Flyway migration against the local database,
6. loads the fictional seed data (`db/seed/local_seed.sql`, `db/seed/coupons_local.sql`),
7. starts the API.

Then open http://localhost:8000/docs. `GET /health/db` should report ok.

How the override works: compose loads `.env` first, then `.env.docker` on top.
So in Local DB mode `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `APP_ENV`, `OTP_PROVIDER` and `OTP_TOKEN_SECRET`
come from `.env.docker` (local), and the Medisina settings come from `.env`.
**Delete `.env.docker` and you are back in Cloud DB mode.**

## 4. Daily use

```powershell
.\dev.ps1 up       # start local Supabase + API
.\dev.ps1 logs     # follow API logs (Ctrl+C stops following, not the API)
.\dev.ps1 down     # stop everything; local data is kept
```

`app/` and `tests/` are mounted into the container, so saving a file reloads the API.
After changing `requirements.txt`, run `.\dev.ps1 up` again (it rebuilds the image).

## 5. All `dev.ps1` commands

| Command | What it does |
|---|---|
| `setup` | First time: start Supabase, write `.env.docker`, build, migrate, seed, start API |
| `up` | Start local Supabase and the API |
| `down` | Stop everything (data kept) |
| `logs` | Follow API logs. Fake OTP codes are printed here |
| `test` | Run `pytest` inside the API container |
| `migrate` | Apply `db/migrations` to the **local** database |
| `info` | Show local Flyway migration status |
| `seed` | Load `db/seed/*.sql` into the local database |
| `status` | Show local Supabase URLs/keys and running containers |
| `reset` | **Wipe the local database**, then migrate + seed (asks you to type `RESET`) |

## 6. Testing phone OTP locally

`.env.docker` sets `OTP_PROVIDER=fake`, so no SMS is sent and nothing costs money.

1. `POST /auth/otp/send` with `{ "phone": "+91XXXXXXXXXX" }`. Only Indian numbers are accepted.
2. `.\dev.ps1 logs` and copy the 6-digit code printed by the fake provider.
3. `POST /auth/otp/verify` with the phone and code. It returns a `phone_verified` token.
4. `POST /clients` with header `Authorization: Bearer <token>`. The body's phone must match.

The rate limits still apply locally: 3 sends per phone per 10 min, 5 wrong codes per code.
If you hit them, wait, or run `.\dev.ps1 reset`.

## 7. Writing a migration

1. Add `db/migrations/V<yyyyMMddHHmmss>__short_description.sql`. Timestamp versions stop two teammates from picking the same number.
2. Run `.\dev.ps1 migrate`, then `.\dev.ps1 test`.
3. Wrong? Fix the SQL and `.\dev.ps1 reset`. Never edit a migration that is already merged.
4. Raise the PR. The **shared cloud database** is migrated separately with `db\flyway.ps1`,
   after the PR is merged into `dev`. `dev.ps1` cannot reach the cloud database:
   its Flyway connection is hard-wired to `host.docker.internal:54322`.

## 8. Local vs cloud

| | Local DB mode | Cloud DB mode |
|---|---|---|
| Database | your machine, throwaway | shared team project |
| `SUPABASE_URL` | `http://host.docker.internal:54321` | `https://<project>.supabase.co` |
| OTP | fake, code in the logs | whatever `.env` says |
| Data | fictional seed | real |
| Migrations | `.\dev.ps1 migrate` | `db\flyway.ps1 migrate` (after merge) |

Plain `http` in `SUPABASE_URL` is accepted **only** for the hosts `localhost`, `127.0.0.1` and
`host.docker.internal` (see `LOCAL_HOSTS` in `app/config.py`). `APP_ENV=production` rejects http and the fake OTP provider.

## 9. Troubleshooting

| Symptom | Fix |
|---|---|
| `Docker is installed but not running` | Start Docker Desktop, wait for "Engine running", retry |
| `.env is missing` | `Copy-Item .env.example .env`, then fill it in |
| `supabase\config.toml is missing` | Pull the latest `dev`. The file is committed |
| You have an old `supabase\config.jsonc` from your own `supabase init` | Delete it. The team uses the committed `config.toml` |
| Port 54321/54322/54323 or 8000 already in use | Another Supabase project or API is running: `npx supabase stop --all`, or stop the other process |
| API starts but talks to the cloud DB | `.env.docker` is missing. Run `.\dev.ps1 up` (it recreates it) |
| `env_file ... path` error from compose | Docker Compose is older than 2.24. Update Docker Desktop |
| `Could not read the local secret key` | Check `npx supabase status -o env`. Supabase must be running |
| Seed fails | Read the psql error; usually a migration changed a table. Fix the seed SQL, `.\dev.ps1 reset` |

## 10. Rules

- Never commit `.env`, `.env.docker` or `.env.flyway`.
- Never put cloud keys in `.env.docker`.
- Seed data is fictional. Never copy real client data into `db/seed/`.
- Do not disable RLS to make something work locally.
