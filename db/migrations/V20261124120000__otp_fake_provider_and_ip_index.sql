-- Phone OTP (phase 1)
-- 1. Allow provider = 'fake' (local development provider) besides msg91/twilio.
-- 2. Index for the per-IP rate limit (count sends by ip in the last hour).
-- Additive only: no data is changed or removed.

do $$
declare
  c text;
begin
  -- find the existing CHECK on provider by its definition (name may vary)
  select conname into c
  from pg_constraint
  where conrelid = 'public.otp_verifications'::regclass
    and contype = 'c'
    and pg_get_constraintdef(oid) ilike '%provider%';
  if c is not null then
    execute format('alter table public.otp_verifications drop constraint %I', c);
  end if;
end $$;

alter table public.otp_verifications
  add constraint otp_verifications_provider_check
  check (provider in ('msg91', 'twilio', 'fake'));

create index if not exists idx_otp_verifications_ip_created
  on public.otp_verifications (ip, created_at desc);