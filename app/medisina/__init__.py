"""Everything that talks to the Medisina backend lives in this package.

  client.py      ONE shared HTTP client: base URL, Bearer token, login/refresh,
                 envelope unwrapping (like db.py is for Supabase)
  operations.py  every Medisina endpoint this app calls (one registry)

The API contract itself lives in portal-backend/ (swagger.json + contract.py).
"""
