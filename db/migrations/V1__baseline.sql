-- V1 BASELINE: this is the schema that already exists in Supabase.
-- On the existing DB it is NOT executed (marked applied via `flyway baseline`).
-- On a brand-new empty DB, `flyway migrate` runs it to recreate the schema.
-- NEVER edit this file. Changes go in a new V<n>__*.sql file.

-- =====================================================================
-- THERAPY PLATFORM — DATABASE SCHEMA (PostgreSQL 15+ / Supabase)
-- Run once on a NEW / EMPTY Supabase project using SQL Editor.
--
-- Important design decisions:
-- 1. A client's own referral code is represented by referral_codes.client_id.
--    There is no duplicated clients.own_referral_code field to drift out of sync.
-- 2. A session's therapist and start/end times must exactly match its slot.
-- 3. Coupon limits are enforced transactionally by a trigger that locks the
--    coupon row. Reserved and used redemptions consume a limit; released ones do not.
-- 4. RLS is enabled on every table. No public policies are created.
-- =====================================================================

-- ---------------------------------------------------------------------
-- Shared updated_at trigger
-- ---------------------------------------------------------------------
create or replace function public.set_updated_at()
returns trigger
language plpgsql
set search_path = public
as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

-- ---------------------------------------------------------------------
-- 1. CLIENTS
-- ---------------------------------------------------------------------
create table public.clients (
  id                  uuid primary key default gen_random_uuid(),
  phone               text not null unique
                      check (phone ~ '^\+[1-9][0-9]{7,14}$'),
  first_name          text,
  last_name           text,
  dob                 date check (dob > date '1900-01-01'),
  email               text check (
                        email is null or
                        email ~* '^[^@\s]+@[^@\s]+\.[^@\s]+$'
                      ),
  referred_by_code_id uuid,
  source              text not null
                      check (source in ('match_form','whatsapp','web')),
  phone_verified_at   timestamptz,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now()
);

create trigger trg_clients_updated
before update on public.clients
for each row execute function public.set_updated_at();

-- ---------------------------------------------------------------------
-- 2. OTP VERIFICATIONS
-- ---------------------------------------------------------------------
create table public.otp_verifications (
  id                  uuid primary key default gen_random_uuid(),
  phone               text not null check (phone ~ '^\+[1-9][0-9]{7,14}$'),
  channel             text not null default 'sms'
                      check (channel in ('sms','whatsapp')),
  provider            text not null check (provider in ('msg91','twilio')),
  provider_request_id text,
  status              text not null default 'sent'
                      check (status in ('sent','verified','failed','expired')),
  attempts            int not null default 0 check (attempts between 0 and 10),
  expires_at          timestamptz not null,
  verified_at         timestamptz,
  ip                  inet,
  created_at          timestamptz not null default now()
);

create index idx_otp_verifications_phone_created
on public.otp_verifications (phone, created_at desc);

-- ---------------------------------------------------------------------
-- 3. THERAPISTS
-- ---------------------------------------------------------------------
create table public.therapists (
  id              uuid primary key default gen_random_uuid(),
  full_name       text not null,
  phone           text unique check (
                    phone is null or phone ~ '^\+[1-9][0-9]{7,14}$'
                  ),
  email           text unique,
  photo_url       text,
  intro_video_url text,
  qualification   text,
  about           text,
  languages       jsonb not null default '[]'::jsonb
                  check (jsonb_typeof(languages) = 'array'),
  specialties     jsonb not null default '[]'::jsonb
                  check (jsonb_typeof(specialties) = 'array'),
  session_fee     numeric(10,2) not null check (session_fee >= 0),
  session_minutes int not null default 50
                  check (session_minutes between 10 and 240),
  is_active       boolean not null default true,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create trigger trg_therapists_updated
before update on public.therapists
for each row execute function public.set_updated_at();

-- ---------------------------------------------------------------------
-- 4. REFERRAL CODES
-- A referral code belongs to exactly one client, therapist, or partner.
-- Partner ownership is stored as partner_owner_ref because no partners
-- table exists in this schema yet.
-- ---------------------------------------------------------------------
create table public.referral_codes (
  id                     uuid primary key default gen_random_uuid(),
  code                   text not null unique
                         check (
                           code = upper(code)
                           and length(code) between 4 and 20
                         ),
  owner_type             text not null
                         check (owner_type in ('client','therapist','partner')),
  client_id              uuid unique references public.clients(id),
  therapist_id           uuid unique references public.therapists(id),
  partner_owner_ref      text,
  referee_discount_type  text
                         check (referee_discount_type in ('percent','flat')),
  referee_discount_value numeric(10,2)
                         check (referee_discount_value >= 0),
  referrer_reward_type   text
                         check (referrer_reward_type in ('percent','flat','credit','free_session')),
  referrer_reward_value  numeric(10,2)
                         check (referrer_reward_value >= 0),
  is_active              boolean not null default true,
  created_at             timestamptz not null default now(),

  constraint chk_referral_code_single_owner check (
    (owner_type = 'client'
      and client_id is not null
      and therapist_id is null
      and partner_owner_ref is null)
    or
    (owner_type = 'therapist'
      and therapist_id is not null
      and client_id is null
      and partner_owner_ref is null)
    or
    (owner_type = 'partner'
      and partner_owner_ref is not null
      and client_id is null
      and therapist_id is null)
  )
);

create index idx_referral_codes_owner_type
on public.referral_codes (owner_type);

-- Now that referral_codes exists, add the client's referred-by relationship.
alter table public.clients
add constraint fk_clients_referred_by_code
foreign key (referred_by_code_id)
references public.referral_codes(id);

-- ---------------------------------------------------------------------
-- 5. THERAPIST SLOTS
-- ---------------------------------------------------------------------
create table public.therapist_slots (
  id           uuid primary key default gen_random_uuid(),
  therapist_id uuid not null references public.therapists(id) on delete cascade,
  start_at     timestamptz not null,
  end_at       timestamptz not null,
  status       text not null default 'open'
               check (status in ('open','held','booked','blocked')),
  held_until   timestamptz,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now(),

  constraint uq_therapist_slots_id_therapist_time
    unique (id, therapist_id, start_at, end_at),
  constraint uq_therapist_slots_therapist_start
    unique (therapist_id, start_at),
  constraint chk_therapist_slots_time
    check (end_at > start_at),
  constraint chk_therapist_slots_hold
    check (status <> 'held' or held_until is not null)
);

create index idx_therapist_slots_status_start
on public.therapist_slots (status, start_at);

create trigger trg_slots_updated
before update on public.therapist_slots
for each row execute function public.set_updated_at();

-- ---------------------------------------------------------------------
-- 6. COUPONS
-- Redemption counts are calculated from coupon_redemptions, not duplicated
-- in a mutable used_count column.
-- ---------------------------------------------------------------------
create table public.coupons (
  id                  uuid primary key default gen_random_uuid(),
  code                text not null unique check (code = upper(code)),
  discount_type       text not null check (discount_type in ('percent','flat')),
  discount_value      numeric(10,2) not null check (discount_value > 0),
  max_discount        numeric(10,2) check (max_discount > 0),
  min_amount          numeric(10,2) not null default 0 check (min_amount >= 0),
  valid_from          timestamptz not null default now(),
  valid_to            timestamptz,
  max_uses_total      int check (max_uses_total > 0),
  max_uses_per_client int not null default 1 check (max_uses_per_client > 0),
  first_session_only  boolean not null default false,
  therapist_id        uuid references public.therapists(id),
  is_active           boolean not null default true,
  created_by          text,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),

  constraint chk_coupon_percent
    check (discount_type <> 'percent' or discount_value <= 100),
  constraint chk_coupon_valid_dates
    check (valid_to is null or valid_to > valid_from)
);

create trigger trg_coupons_updated
before update on public.coupons
for each row execute function public.set_updated_at();

-- ---------------------------------------------------------------------
-- 7. SESSIONS
-- Composite foreign key guarantees the selected slot belongs to the same
-- therapist and has exactly the same start_at / end_at values.
-- ---------------------------------------------------------------------
create table public.sessions (
  id               uuid primary key default gen_random_uuid(),
  client_id        uuid not null references public.clients(id),
  therapist_id     uuid not null,
  slot_id          uuid not null,
  concern          text,
  start_at         timestamptz not null,
  end_at           timestamptz not null,
  meeting_link     text,
  status           text not null default 'pending_payment'
                   check (status in ('pending_payment','confirmed','completed','cancelled','no_show')),
  list_price       numeric(10,2) not null check (list_price >= 0),
  discount_amount  numeric(10,2) not null default 0 check (discount_amount >= 0),
  final_amount     numeric(10,2) not null check (final_amount >= 0),
  coupon_id        uuid references public.coupons(id),
  referral_code_id uuid references public.referral_codes(id),
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),

  constraint fk_sessions_matching_slot
    foreign key (slot_id, therapist_id, start_at, end_at)
    references public.therapist_slots (id, therapist_id, start_at, end_at),
  constraint chk_sessions_time check (end_at > start_at),
  constraint chk_sessions_discount check (discount_amount <= list_price),
  constraint chk_sessions_final_amount
    check (final_amount = list_price - discount_amount)
);

-- Only one non-cancelled booking may use a slot.
create unique index sessions_one_live_booking_per_slot
on public.sessions (slot_id)
where status <> 'cancelled';

create index idx_sessions_client on public.sessions (client_id);
create index idx_sessions_therapist_start
on public.sessions (therapist_id, start_at);

create trigger trg_sessions_updated
before update on public.sessions
for each row execute function public.set_updated_at();

-- ---------------------------------------------------------------------
-- 8. PAYMENTS
-- ---------------------------------------------------------------------
create table public.payments (
  id                 uuid primary key default gen_random_uuid(),
  session_id         uuid not null references public.sessions(id),
  gateway            text not null,
  gateway_order_id   text unique,
  gateway_payment_id text unique,
  amount             numeric(10,2) not null check (amount >= 0),
  currency           char(3) not null default 'INR',
  status             text not null default 'created'
                     check (status in ('created','paid','failed','refunded')),
  raw_payload        jsonb,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now()
);

create index idx_payments_session on public.payments (session_id);

create trigger trg_payments_updated
before update on public.payments
for each row execute function public.set_updated_at();

-- ---------------------------------------------------------------------
-- 9. COUPON REDEMPTIONS
-- A redemption in reserved or used state consumes the coupon's limits.
-- A released redemption does not.
-- ---------------------------------------------------------------------
create table public.coupon_redemptions (
  id              uuid primary key default gen_random_uuid(),
  coupon_id       uuid not null references public.coupons(id),
  client_id       uuid not null references public.clients(id),
  session_id      uuid not null references public.sessions(id),
  discount_amount numeric(10,2) not null check (discount_amount >= 0),
  status          text not null default 'reserved'
                  check (status in ('reserved','used','released')),
  created_at      timestamptz not null default now()
);

create unique index coupon_redemptions_one_active_per_session
on public.coupon_redemptions (session_id)
where status <> 'released';

create index idx_coupon_redemptions_coupon_client
on public.coupon_redemptions (coupon_id, client_id);

-- Serialize redemption-limit checks per coupon to prevent concurrent
-- transactions from both consuming the final available redemption.
create or replace function public.enforce_coupon_redemption_limits()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  v_max_total integer;
  v_max_per_client integer;
  v_total_active bigint;
  v_client_active bigint;
begin
  if new.status = 'released' then
    return new;
  end if;

  select max_uses_total, max_uses_per_client
    into v_max_total, v_max_per_client
  from public.coupons
  where id = new.coupon_id
  for update;

  if not found then
    raise exception 'Coupon % does not exist', new.coupon_id
      using errcode = 'foreign_key_violation';
  end if;

  if tg_op = 'INSERT' then
    select count(*)
      into v_total_active
    from public.coupon_redemptions
    where coupon_id = new.coupon_id and status <> 'released';

    select count(*)
      into v_client_active
    from public.coupon_redemptions
    where coupon_id = new.coupon_id
      and client_id = new.client_id
      and status <> 'released';
  else
    select count(*)
      into v_total_active
    from public.coupon_redemptions
    where coupon_id = new.coupon_id
      and status <> 'released'
      and id <> new.id;

    select count(*)
      into v_client_active
    from public.coupon_redemptions
    where coupon_id = new.coupon_id
      and client_id = new.client_id
      and status <> 'released'
      and id <> new.id;
  end if;

  if v_max_total is not null and v_total_active >= v_max_total then
    raise exception 'Coupon % has reached its total redemption limit', new.coupon_id
      using errcode = 'check_violation';
  end if;

  if v_max_per_client is not null and v_client_active >= v_max_per_client then
    raise exception 'Client % has reached the redemption limit for coupon %',
      new.client_id, new.coupon_id
      using errcode = 'check_violation';
  end if;

  return new;
end;
$$;

create trigger trg_enforce_coupon_redemption_limits
before insert or update of coupon_id, client_id, status
on public.coupon_redemptions
for each row execute function public.enforce_coupon_redemption_limits();

-- ---------------------------------------------------------------------
-- 10. REFERRALS
-- ---------------------------------------------------------------------
create table public.referrals (
  id                    uuid primary key default gen_random_uuid(),
  referral_code_id      uuid not null references public.referral_codes(id),
  referred_client_id    uuid not null unique references public.clients(id),
  qualifying_session_id uuid references public.sessions(id),
  status                text not null default 'pending'
                        check (status in ('pending','qualified','rewarded')),
  created_at            timestamptz not null default now(),
  check (status = 'pending' or qualifying_session_id is not null)
);

-- ---------------------------------------------------------------------
-- 11. CONSENTS
-- Keep grant history: withdrawal updates withdrawn_at; re-grant inserts
-- a new row.
-- ---------------------------------------------------------------------
create table public.consents (
  id             uuid primary key default gen_random_uuid(),
  client_id      uuid not null references public.clients(id) on delete cascade,
  purpose        text not null
                 check (purpose in ('terms','privacy','whatsapp_messages','health_data')),
  policy_version text not null,
  granted_at     timestamptz not null default now(),
  withdrawn_at   timestamptz,
  ip             inet,
  user_agent     text,
  check (withdrawn_at is null or withdrawn_at >= granted_at)
);

create index idx_consents_client_purpose
on public.consents (client_id, purpose);

create view public.active_consents
with (security_invoker = true)
as
select * from public.consents where withdrawn_at is null;

-- ---------------------------------------------------------------------
-- SUPABASE SECURITY
-- Enable RLS on every table. No anon/authenticated policies are created.
-- Backend access should use a server-side secret/service credential only.
-- Never expose the service-role/secret key in browser or mobile code.
-- ---------------------------------------------------------------------
alter table public.clients enable row level security;
alter table public.otp_verifications enable row level security;
alter table public.therapists enable row level security;
alter table public.referral_codes enable row level security;
alter table public.therapist_slots enable row level security;
alter table public.coupons enable row level security;
alter table public.sessions enable row level security;
alter table public.payments enable row level security;
alter table public.coupon_redemptions enable row level security;
alter table public.referrals enable row level security;
alter table public.consents enable row level security;

-- End of schema.