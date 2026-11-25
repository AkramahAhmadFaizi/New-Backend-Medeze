-- LOCAL DOCKER ONLY (supabase start). Do NOT run on the shared/prod database.
-- Run in local Studio -> SQL Editor (http://127.0.0.1:54323). Safe to re-run.
--
-- Part 1 = step 5 of "adding an endpoint": let the backend read the tables
--          POST /coupons/check needs.
-- Part 2 = test data used by the Postman folder "Coupons - check".

-- ---- Part 1: permissions (one time per table) ----
grant select on public.coupons            to service_role;
grant select on public.coupon_redemptions to service_role;
grant select on public.sessions           to service_role;
grant select on public.clients            to service_role;

-- ---- Part 2: test data (fixed ids so Postman can reference them) ----
insert into public.clients (id, phone, first_name, source)
values ('11111111-1111-1111-1111-111111111111', '+919000000099', 'Coupon', 'web')
on conflict do nothing;

insert into public.coupons
  (code, discount_type, discount_value, max_discount, min_amount,
   valid_from, valid_to, max_uses_total, max_uses_per_client, is_active, created_by)
values
  -- 20% off, capped at 250
  ('WELCOME20', 'percent', 20,  250,  0,    now() - interval '1 day', null, null, 1, true,  'seed'),
  -- 200 off, only on amounts >= 1000
  ('FLAT200',   'flat',    200, null, 1000, now() - interval '1 day', null, null, 1, true,  'seed'),
  -- expired yesterday
  ('EXPIRED10', 'percent', 10,  null, 0,    now() - interval '10 days', now() - interval '1 day', null, 1, true, 'seed'),
  -- switched off
  ('INACTIVE5', 'percent', 5,   null, 0,    now() - interval '1 day', null, null, 1, false, 'seed'),
  -- starts in 30 days
  ('FUTURE15',  'percent', 15,  null, 0,    now() + interval '30 days', null, null, 1, true, 'seed')
on conflict (code) do nothing;
