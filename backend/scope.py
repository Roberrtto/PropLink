"""Who may see what.

Every dashboard route that touches a property, unit, resident, bill or request calls one of these helpers first.
- a landlord sees every property of their own organization
- a manager sees only the properties assigned to them
A record outside that set is reported as "not found" (404), so nobody can tell whether it exists.
"""
from fastapi import HTTPException
from sqlalchemy import select
from models import (Property, PropertyManager, Building, Unit, Tenancy, Bill, ServiceRequest, ServiceProvider, UserAccount,
                    BillingConfig, PaymentRequest)


def _missing(what):
    return HTTPException(404, f"{what} not found")


def property_ids(db, s) -> set:
    if s.role == "landlord":
        q = select(Property.id).where(Property.org_id == s.org_id)
    else:
        q = (select(PropertyManager.property_id).join(Property, Property.id == PropertyManager.property_id)
             .where(PropertyManager.staff_id == s.id, Property.org_id == s.org_id))
    return set(db.scalars(q))


def own_property(db, s, pid):
    if pid is None or pid not in property_ids(db, s): raise _missing("Property")
    return db.get(Property, pid)


def unit_property(db, unit) -> int:
    return db.get(Building, unit.building_id).property_id


def own_unit(db, s, uid):
    u = db.get(Unit, uid) if uid is not None else None
    if not u or unit_property(db, u) not in property_ids(db, s): raise _missing("Unit")
    return u


def own_tenancy(db, s, tid):
    t = db.get(Tenancy, tid) if tid is not None else None
    if not t or unit_property(db, db.get(Unit, t.unit_id)) not in property_ids(db, s): raise _missing("Tenancy")
    return t


def own_resident(db, s, rid):
    """(resident, active tenancy) for a resident currently living in one of the caller's properties."""
    r = db.get(UserAccount, rid) if rid is not None else None
    if not r or r.org_id != s.org_id: raise _missing("Resident")
    ids = property_ids(db, s)
    for t in db.scalars(select(Tenancy).where(Tenancy.resident_id == r.id, Tenancy.end_date.is_(None))):
        if unit_property(db, db.get(Unit, t.unit_id)) in ids: return r, t
    raise _missing("Resident")


def own_bill(db, s, bid):
    b = db.get(Bill, bid) if bid is not None else None
    if not b or b.property_id not in property_ids(db, s): raise _missing("Bill")
    return b


def own_service(db, s, rid):
    r = db.get(ServiceRequest, rid) if rid is not None else None
    if not r or r.property_id not in property_ids(db, s): raise _missing("Request")
    return r


def own_provider(db, s, pid):
    p = db.get(ServiceProvider, pid) if pid is not None else None
    if not p or p.org_id != s.org_id: raise _missing("Provider")
    return p


def own_config(db, s, cid):
    c = db.get(BillingConfig, cid) if cid is not None else None
    if not c or c.property_id not in property_ids(db, s): raise _missing("Billing rule")
    return c


def own_payment_request(db, s, checkout_id):
    r = db.scalar(select(PaymentRequest).where(PaymentRequest.checkout_request_id == checkout_id))
    b = db.get(Bill, r.bill_id) if r else None
    if not r or b.property_id not in property_ids(db, s): raise _missing("Payment")
    return r