-- Clients must have first_name, email and dob (product rule, 2026-11-25).
-- The API already enforces this; NOT NULL makes sure nothing can bypass it.
-- FAILS (and changes nothing) if any existing row is missing one of them:
-- run the check query in README.md ("Required client fields") first.
alter table public.clients
  alter column first_name set not null,
  alter column email      set not null,
  alter column dob        set not null;