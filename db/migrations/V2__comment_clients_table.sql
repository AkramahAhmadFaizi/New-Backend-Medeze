-- First real migration: harmless, proves the Flyway pipeline end to end.
comment on table public.clients is
  'Client profiles. A client''s own referral code lives in referral_codes.client_id.';