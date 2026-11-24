-- Allow provider = '2factor' (2Factor.in, Indian SMS OTP provider).
-- Additive only: widens the allowed values, no data changed.

do $$
declare
  c text;
begin
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
  check (provider in ('msg91', 'twilio', 'fake', '2factor'));