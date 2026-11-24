"""In-memory stand-in for the Supabase client (just what our services use)."""
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace as NS

from postgrest.exceptions import APIError

DEFAULTS = {
    "clients": lambda: {"first_name": None, "last_name": None, "dob": None, "email": None,
                        "referred_by_code_id": None, "phone_verified_at": None},
    "otp_verifications": lambda: {"status": "sent", "attempts": 0, "channel": "sms",
                                  "provider_request_id": None, "verified_at": None, "ip": None},
}


class FakeQuery:
    def __init__(self, db, table):
        self.db, self.table = db, table
        self.filters, self.op, self.payload = [], "select", None
        self.want_count, self._order, self._limit = False, None, None

    def select(self, cols, count=None):
        self.want_count = count == "exact"
        return self

    def eq(self, k, v):
        self.filters.append(lambda r: str(r.get(k)) == str(v)); return self

    def gte(self, k, v):
        self.filters.append(lambda r: r.get(k) is not None and r[k] >= v); return self

    def order(self, col, desc=False):
        self._order = (col, desc); return self

    def limit(self, n):
        self._limit = n; return self

    def insert(self, row):
        self.op, self.payload = "insert", row; return self

    def update(self, row):
        self.op, self.payload = "update", row; return self

    def _rows(self):
        return [r for r in self.db[self.table] if all(f(r) for f in self.filters)]

    def execute(self):
        rows = self.db.setdefault(self.table, [])
        now = datetime.now(timezone.utc).isoformat()
        if self.op == "insert":
            if self.table == "clients" and any(r["phone"] == self.payload["phone"] for r in rows):
                raise APIError({"code": "23505", "message": "duplicate key clients_phone_key"})
            r = {"id": str(uuid.uuid4()), "created_at": now, "updated_at": now,
                 **DEFAULTS.get(self.table, dict)(), **self.payload}
            rows.append(r)
            return NS(data=[r], count=None)
        if self.op == "update":
            matched = self._rows()
            for r in matched:
                r.update(self.payload)
            return NS(data=matched, count=None)
        matched = self._rows()
        count = len(matched)
        if self._order:
            col, desc = self._order
            matched = sorted(matched, key=lambda r: r[col], reverse=desc)
        if self._limit is not None:
            matched = matched[: self._limit]
        return NS(data=matched, count=count if self.want_count else None)


class FakeSupabase:
    def __init__(self):
        self.db = {"clients": [], "otp_verifications": [], "referral_codes": []}

    def table(self, name):
        return FakeQuery(self.db, name)