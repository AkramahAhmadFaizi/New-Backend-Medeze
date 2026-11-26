-- LOCAL DEVELOPMENT SEED DATA. Never run against the shared/cloud database.
-- Idempotent: safe to run many times (existing rows are left alone).
-- Fixed UUIDs so Postman / tests can reference them.

-- Therapist
insert into public.therapists
  (id, full_name, phone, email, qualification, about, languages, specialties, session_fee, session_minutes)
values
  ('00000000-0000-4000-8000-00000000a001', 'Dr. Ayesha Khan (seed)', '+919800000001',
   'ayesha.seed@example.com', 'M.Phil Clinical Psychology', 'Seed therapist for local development.',
   '["English", "Hindi"]', '["Anxiety", "Stress"]', 1500, 50)
on conflict (id) do nothing;

-- Partner referral code
insert into public.referral_codes
  (id, code, owner_type, partner_owner_ref, referee_discount_type, referee_discount_value)
values
  ('00000000-0000-4000-8000-00000000b001', 'PARTNERX', 'partner', 'seed-partner', 'percent', 10)
on conflict (code) do nothing;

-- Coupon
insert into public.coupons
  (id, code, discount_type, discount_value, max_discount, max_uses_total, max_uses_per_client, first_session_only)
values
  ('00000000-0000-4000-8000-00000000c001', 'WELCOME20', 'percent', 20, 300, 500, 1, true)
on conflict (code) do nothing;

-- Client (complete record: required fields + verified phone)
insert into public.clients
  (id, phone, first_name, last_name, dob, email, source, referred_by_code_id, phone_verified_at)
values
  ('00000000-0000-4000-8000-00000000d001', '+919800000101', 'Rahul', 'Sharma (seed)', '1994-03-12',
   'rahul.seed@example.com', 'web', '00000000-0000-4000-8000-00000000b001', now())
on conflict (phone) do nothing;

-- Open slots: next 3 days at 10:00 and 11:00 IST, always in the future
insert into public.therapist_slots (therapist_id, start_at, end_at)
select '00000000-0000-4000-8000-00000000a001',
       (day_ist + hour_ist) at time zone 'Asia/Kolkata',
       (day_ist + hour_ist + interval '50 minutes') at time zone 'Asia/Kolkata'
from generate_series(1, 3) as g(n)
cross join lateral (select date_trunc('day', now() at time zone 'Asia/Kolkata') + n * interval '1 day' as day_ist) d
cross join (values (interval '10 hours'), (interval '11 hours')) as h(hour_ist)
on conflict (therapist_id, start_at) do nothing;

-- Summary
select (select count(*) from public.therapists)      as therapists,
       (select count(*) from public.clients)         as clients,
       (select count(*) from public.referral_codes)  as referral_codes,
       (select count(*) from public.coupons)         as coupons,
       (select count(*) from public.therapist_slots) as slots;
