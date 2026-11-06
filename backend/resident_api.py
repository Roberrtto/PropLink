"""Resident (mobile) API: OTP login + endpoints scoped to the signed-in resident's own tenancy."""
import os, hmac, hashlib, base64, json, time, random
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from main import (get_db, row, UserAccount, Tenancy, Unit, Building, Property, Bill, PaymentRequest, MpesaTransaction,
                  Payment, Receipt, ServiceRequest, ServiceProvider, Notification, audit, StkIn, stk, simulate)
import daraja

SECRET = os.getenv("JWT_SECRET", "dev-secret-change-me").encode()
router = APIRouter(prefix="/api")
OTPS: dict = {}  # phone -> (code, expiry). Use Redis/DB in production.

def norm(p): d = "".join(c for c in p if c.isdigit()); return "0" + d[-9:]
def _sig(body): return hmac.new(SECRET, body.encode(), hashlib.sha256).hexdigest()
def sign(uid):
    body = base64.urlsafe_b64encode(json.dumps({"uid": uid, "exp": int(time.time()) + 7 * 86400}).encode()).decode()
    return body + "." + _sig(body)
def verify(tok):
    body, sig = tok.split(".")
    if not hmac.compare_digest(sig, _sig(body)): raise ValueError
    data = json.loads(base64.urlsafe_b64decode(body))
    if data["exp"] < time.time(): raise ValueError
    return data["uid"]

def active_resident(db, phone):
    for u in db.scalars(select(UserAccount).where(UserAccount.role == "resident")):
        if norm(u.phone) == norm(phone):
            t = db.scalar(select(Tenancy).where(Tenancy.resident_id == u.id, Tenancy.end_date.is_(None)))
            if t: return u
    return None

def me(authorization: str = Header(""), db=Depends(get_db)):
    try: uid = verify(authorization.removeprefix("Bearer "))
    except Exception: raise HTTPException(401, "Please sign in again")
    t = db.scalar(select(Tenancy).where(Tenancy.resident_id == uid, Tenancy.end_date.is_(None)))
    if not t: raise HTTPException(403, "No active tenancy")
    return t

class PhoneIn(BaseModel): phone: str
class VerifyIn(BaseModel): phone: str; code: str
@router.post("/auth/request-otp")
def request_otp(d: PhoneIn, db=Depends(get_db)):
    if not active_resident(db, d.phone): raise HTTPException(404, "No resident account with that number")
    code = f"{random.randint(0, 999999):06d}"; OTPS[norm(d.phone)] = (code, time.time() + 300)
    print(f"[SMS simulated] code for {d.phone}: {code}")  # replace with a real SMS gateway later
    return {"sent": True, "dev_code": code if daraja.MOCK else None}

@router.post("/auth/verify")
def verify_otp(d: VerifyIn, db=Depends(get_db)):
    code, exp = OTPS.get(norm(d.phone), (None, 0))
    if code != d.code or exp < time.time(): raise HTTPException(400, "Wrong or expired code")
    OTPS.pop(norm(d.phone)); u = active_resident(db, d.phone)
    return {"token": sign(u.id), "name": u.full_name}

@router.get("/me")
def profile(t=Depends(me), db=Depends(get_db)):
    u = db.get(Unit, t.unit_id); b = db.get(Building, u.building_id); p = db.get(Property, b.property_id); r = db.get(UserAccount, t.resident_id)
    unpaid = db.scalars(select(Bill).where(Bill.tenancy_id == t.id, Bill.status != "paid").order_by(Bill.due_date)).all()
    return {"name": r.full_name, "phone": r.phone, "unit": u.number, "block": b.name, "property": p.name, "balance": sum(x.amount for x in unpaid),
            "unpaid_count": len(unpaid), "next_due": unpaid[0].due_date.isoformat() if unpaid else None}

@router.get("/me/bills")
def my_bills(t=Depends(me), db=Depends(get_db)):
    return [row(b) for b in db.scalars(select(Bill).where(Bill.tenancy_id == t.id).order_by(Bill.due_date.desc(), Bill.id.desc()))]

def own_request(db, t, cid):
    r = db.scalar(select(PaymentRequest).where(PaymentRequest.checkout_request_id == cid)); b = db.get(Bill, r.bill_id) if r else None
    if not r or b.tenancy_id != t.id: raise HTTPException(404, "Payment not found")
    return r

@router.post("/me/pay")
def pay(d: StkIn, t=Depends(me), db=Depends(get_db)):
    b = db.get(Bill, d.bill_id)
    if not b or b.tenancy_id != t.id: raise HTTPException(404, "Bill not found")
    return stk(d, db)  # same flow as the manager side: request recorded, bill stays pending

@router.get("/me/payment/{cid}")
def pay_status(cid: str, t=Depends(me), db=Depends(get_db)):
    r = own_request(db, t, cid); tx = db.scalar(select(MpesaTransaction).where(MpesaTransaction.payment_request_id == r.id))
    rc = db.scalar(select(Receipt).join(Payment, Payment.id == Receipt.payment_id).where(Payment.transaction_id == tx.id)) if tx else None
    return {"status": r.status, "mpesa_receipt": tx.mpesa_receipt if tx else None, "receipt": rc.number if rc else None}

@router.post("/me/mock/{cid}/{outcome}")  # simulates the resident entering (or cancelling) the PIN on the phone prompt
def mock_pin(cid: str, outcome: str, t=Depends(me), db=Depends(get_db)):
    own_request(db, t, cid); return simulate(cid, outcome, db)

@router.get("/me/receipts")
def my_receipts(t=Depends(me), db=Depends(get_db)):
    q = select(Receipt, Payment, Bill).join(Payment, Payment.id == Receipt.payment_id).join(Bill, Bill.id == Payment.bill_id).where(Bill.tenancy_id == t.id).order_by(Receipt.id.desc())
    return [{"number": r.number, "amount": p.amount, "charge": b.charge_type, "period": b.period, "issued_at": r.issued_at.isoformat()} for r, p, b in db.execute(q)]

@router.get("/me/requests")
def my_requests(t=Depends(me), db=Depends(get_db)):
    return [row(r, provider=db.get(ServiceProvider, r.provider_id).name if r.provider_id else None)
            for r in db.scalars(select(ServiceRequest).where(ServiceRequest.tenancy_id == t.id).order_by(ServiceRequest.id.desc()))]

class NewReq(BaseModel): category: str; title: str
@router.post("/me/requests")
def new_request(d: NewReq, t=Depends(me), db=Depends(get_db)):
    b = db.get(Building, db.get(Unit, t.unit_id).building_id)
    r = ServiceRequest(property_id=b.property_id, tenancy_id=t.id, category=d.category, title=d.title); db.add(r); db.flush()
    audit(db, "request submitted by resident", "service_request", r.id, "resident"); db.commit(); return row(r)

@router.get("/me/notifications")
def my_notes(t=Depends(me), db=Depends(get_db)):
    return [row(n) for n in db.scalars(select(Notification).where(Notification.user_id == t.resident_id).order_by(Notification.id.desc()).limit(20))]
