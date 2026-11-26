-- Link the new database to the old (Medisina) one.
-- The shared key is the Medisina doctor id, stored on the therapist.
-- Each booked session also remembers the Medisina appointment it mirrors.

alter table public.therapists
  add column medisina_doctor_id bigint;

create unique index uq_therapists_medisina_doctor_id
  on public.therapists (medisina_doctor_id)
  where medisina_doctor_id is not null;

alter table public.sessions
  add column medisina_appointment_id bigint,
  add column medisina_patient_id bigint;

create unique index uq_sessions_medisina_appointment_id
  on public.sessions (medisina_appointment_id)
  where medisina_appointment_id is not null;

comment on column public.therapists.medisina_doctor_id is
  'doctorId in the old Medisina database. The sync key between the two databases.';
comment on column public.sessions.medisina_appointment_id is
  'appointmentId in the old Medisina database for this same session.';
comment on column public.sessions.medisina_patient_id is
  'patientId Medisina assigned (the backend service account''s patient).';

-- The backend writes these tables with the service_role key.
grant select, insert, update on public.therapists      to service_role;
grant select, insert, update on public.therapist_slots to service_role;
grant select, insert, update on public.sessions        to service_role;
