# How the two databases stay in sync

| | Old database (Medisina) | New database (Supabase) |
|---|---|---|
| Reached through | Medisina API (`app/medisina/`) | Supabase client (`app/db.py`) |
| Doctor | `doctorId` (number) | `therapists.id` (uuid) |
| Booking | `appointmentId` (number) | `sessions.id` (uuid) |
| Time slot | computed on demand (`/available-slots`) | `therapist_slots` row |
| Patient | `patientId` | `clients.id` (uuid) |

Both sides use different id types, so we need a **bridge key**.

## The bridge: `medisina_doctor_id`
Migration `db/migrations/V20261123150000__medisina_link.sql` adds:

| Table | New column | Meaning |
|---|---|---|
| `therapists` | `medisina_doctor_id bigint` (unique) | Medisina `doctorId`. **This is the doctor_id foreign key between the databases.** |
| `sessions` | `medisina_appointment_id bigint` (unique) | The Medisina appointment this session mirrors |
| `sessions` | `medisina_patient_id bigint` | `patientId` Medisina assigned |

Rules:
- A Medisina doctor maps to **at most one** therapist (unique index). A therapist can exist without a Medisina link (NULL).
- A session maps to **at most one** Medisina appointment (unique index).
- Therapists are **created lazily**: the first time someone books doctor 7, we fetch `GET /doctors/7` and insert a `therapists` row with `medisina_doctor_id = 7`. Later bookings reuse and refresh it. No bulk import is needed.

## Field mapping (what each side needs)
| New DB column | Source |
|---|---|
| `therapists.full_name` | Medisina salutation + firstName + lastName |
| `therapists.photo_url`, `about`, `specialties` | `profilePictureUrl`, `bio`, `specialties[].specialtyName` |
| `therapists.session_minutes` | slot length (`scheduledEndAt - scheduledStartAt`) |
| `therapists.session_fee`, `sessions.list_price`, `final_amount` | `fee` from `GET /appointments/{id}` (0 if Medisina has none) |
| `therapist_slots.start_at` / `end_at` | `scheduledStartAt` / `scheduledEndAt` from Medisina |
| `therapist_slots.status` | `booked` |
| `sessions.client_id` | caller's `client_id` (our client) |
| `sessions.status` | `pending_payment` (no payment step yet) |
| `sessions.concern` | request `concern` = Medisina `reasonForVisit` |

| Medisina request field | Source |
|---|---|
| `doctorId` | request `doctor_id` |
| `slotStartUtc` | request `slot_start_utc` (must be a `start_utc` from the slots endpoint) |
| `appointmentType` | request `appointment_type` (default `VIDEO`) |
| `reasonForVisit` | request `concern` |

## Booking flow (`POST /bookings`)
```
GET /specialties            -> Medisina        (list specialties)
GET /doctors?specialty_id=  -> Medisina        (experts)
GET /doctors/{id}/slots     -> Medisina        (free slots)
POST /bookings              -> both:
   1. client exists?                      new DB  (read)
   2. slot already booked here?           new DB  (read)  -> 409 slot_taken
   3. GET /doctors/{id}                   Medisina
   4. POST /appointments  (holds slot)    Medisina  <- source of truth for availability
   5. GET /appointments/{id}  (fee)       Medisina
   6. upsert therapist, slot=booked       new DB
   7. insert session (linked ids)         new DB
   any failure in 6-7 -> DELETE /appointments/{id} on Medisina, slot back to 'open'
```
Medisina goes first because it decides whether a slot is really free. Supabase has no
multi-system transaction, so a failure after step 4 is **compensated** by cancelling the
Medisina appointment. If that cancel also fails, it is logged as `ROLLBACK FAILED ...
Cancel it manually` (an orphan appointment exists only in Medisina).

Replays: Medisina returns `replayed: true` for a repeated request; we then return the existing session instead of creating a second.

## Known limitations (decide before production)
1. **One Medisina patient.** `POST /appointments` books for the account in `MEDISINA_EMAIL`. Every booking therefore lands on that one Medisina patient, whoever our `client_id` is. Real per-client patients need either a Medisina patient per client or a Medisina endpoint that accepts a patient id.
2. **Price.** Medisina's doctor profile has no fee; we read `fee` from the appointment and fall back to 0.
3. **Payment.** Sessions stay `pending_payment`; Medisina's appointment stays `SCHEDULED` (it expires at `holdExpiresAt`). Confirming both after payment is the next feature.
4. **Slot rows** exist in the new DB only for booked slots, not for every free slot.
5. Error responses still show raw upstream details (dev only), as in the rest of the app.

## How to verify a booking reached BOTH databases
After `POST /bookings` returns 201, note two values from the response:
`session_id` (new DB) and `medisina_appointment_id` (old DB). The booking is in both
databases only if **all three** checks below pass.

### 1. New database (Supabase)
Local Supabase (`npx supabase start`): open Studio at http://127.0.0.1:54323 -> SQL Editor, or run
```
docker exec supabase_db_New-Backend-Medeze psql -U postgres -c "<query>"
```
Cloud Supabase: Dashboard -> SQL Editor. Run (replace `<session_id>`):
```sql
select s.id            as session_id,
       s.status        as session_status,
       s.medisina_appointment_id,
       s.start_at, s.end_at, s.final_amount,
       t.full_name, t.medisina_doctor_id,
       sl.status       as slot_status
from public.sessions s
join public.therapists t        on t.id  = s.therapist_id
join public.therapist_slots sl  on sl.id = s.slot_id
where s.id = '<session_id>';
```
Expect one row with `session_status = pending_payment`, `slot_status = booked`, and a non-null
`medisina_appointment_id` and `medisina_doctor_id`.

### 2. Old database (Medisina)
Ask Medisina for the appointment by id. Use the Medisina Swagger/Postman, or `curl`
with a token from `POST /auth/login`:
```
GET {MEDISINA_API_BASE_URL}/appointments/<medisina_appointment_id>
Authorization: Bearer <token>
```
Expect `status` = `SCHEDULED`, `doctorId` = the doctor you booked, and `scheduledStartAt` /
`scheduledEndAt` equal to the session's `start_at` / `end_at`.
Also: `GET /doctors/<doctor_id>/slots?date=<day>` must no longer list the booked `start_utc`.

### 3. They agree
| Check | New DB | Old DB |
|---|---|---|
| Same doctor | `therapists.medisina_doctor_id` | `doctorId` |
| Same appointment | `sessions.medisina_appointment_id` | `appointmentId` |
| Same time | `sessions.start_at` / `end_at` | `scheduledStartAt` / `scheduledEndAt` |
| Same patient | `sessions.medisina_patient_id` | `patientId` |

### Finding mismatches (drift)
- **Sessions with no Medisina link** (should be none for bookings made through this API):
  ```sql
  select id from public.sessions where medisina_appointment_id is null;
  ```
- **Booked slot with no live session** (a failed rollback left the slot booked):
  ```sql
  select sl.id from public.therapist_slots sl
  where sl.status = 'booked'
    and not exists (select 1 from public.sessions s
                    where s.slot_id = sl.id and s.status <> 'cancelled');
  ```
- **Medisina appointment with no session** (new DB save failed AND the cancel failed): look for
  `ROLLBACK FAILED` in the API log. Cancel that appointment in Medisina by hand
  (`DELETE /appointments/<id>`).
- **Failure tests:** book the same slot twice. The second call must return 409 and must not
  add a row to either database.

## Applying the migration
```
.\db\flyway.ps1 validate
.\db\flyway.ps1 migrate
```
