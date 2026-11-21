for every new feature: first add in: schema folder -> in services, -> routers, -> main.py, -> therapy-api.postman.
for features that call the Medisina API: first add the endpoint to app/medisina/operations.py (look it up with `python portal-backend/contract.py show "<path>"`), then the same flow above, then run `python portal-backend/contract.py check`.

medisina/operations enter the api address of old backend. once that is fetched, use it in services/[feature.py]. then of course, like any feature, mention it in routers, schemaa, main.py and therapy-api.