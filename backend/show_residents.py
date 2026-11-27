"""Lists demo residents with the details you need to sign in to the app. For local development only.

Run from the backend folder:  python show_residents.py
Sign in to the app with the name and ID shown, after issuing an activation code in the dashboard (Residents page).
"""
import sys
import config

if config.PRODUCTION:
    sys.exit("This tool prints personal data and is for local development only.")

from sqlalchemy import select
from models import Session, UserAccount, Tenancy, Unit, Building, Property, Organization

# Names and IDs are decrypted automatically when read, so there is nothing to decrypt by hand.
with Session() as db:
    for r in db.scalars(select(UserAccount).order_by(UserAccount.org_id, UserAccount.id)):
        t = db.scalar(select(Tenancy).where(Tenancy.resident_id == r.id, Tenancy.end_date.is_(None)))
        if t:
            u = db.get(Unit, t.unit_id); b = db.get(Building, u.building_id); p = db.get(Property, b.property_id)
            home = f"{p.name}, unit {u.number}"
        else:
            home = "no active tenancy"
        org = db.get(Organization, r.org_id).name
        state = "activated" if r.password_hash else "not activated"
        print(f"#{r.id} [{org}] {r.full_name} | {r.id_type}: {r.id_number} | {r.phone} | {home} | {state}")