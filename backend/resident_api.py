"""Resident (mobile) API.

Sign-in flow:
  1. /auth/verify-identity  name + ID/passport must match a registered resident with an active tenancy.
  2. First time (or forgotten password): the property manager issues a 2-minute code in the dashboard;
     /auth/activate checks it and sets the resident's password.
  3. Later: /auth/login with name + ID + password. No code needed.
All other endpoints are scoped to the signed-in resident's own tenancy.
"""
import hmac, logging
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
import config, daraja, phone as ph
from crypto import hash_secret, id_index, norm_name
from models import (get_db, row, audit, UserAccount, Tenancy, Unit, Building, Property, Bill, PaymentRequest, MpesaTransaction,
                    Payment, Receipt, ServiceRequest, ServiceProvider, Notification, OtpCode)
from security import current_tenancy, make_token, rate_limit, client_ip, hash_password, check_password, burn_time, password_problem
from main import stk, simulate

log = logging.getLogger("proplink.resident")
router = APIRouter(prefix="/api")
BAD = "The details provided are incorrect"
BAD_CODE = "Wrong or expired code. Ask your property manager for a new one."


class IdentityIn(BaseModel):
    full_name: str = Field(min_length=1, max_length=100)
    id_number: str = Field(min_length=5, max_length=20)
class LoginIn(IdentityIn): password: str = Field(max_length=200)
class ActivateIn(IdentityIn):
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")
    password: str = Field(max_length=200)


def find_resident(db, d):
    """The resident whose ID and name match and who still has an active tenancy, else None."""
    for u in db.scalars(select(UserAccount).where(UserAccount.id_hash == id_index(d.id_number))):
        if norm_name(u.full_name) == norm_name(d.full_name) and \
           db.scalar(select(Tenancy).where(Tenancy.resident_id == u.id, Tenancy.end_date.is_(None))):
            return u
    return None


@router.post("/auth/verify-identity")  # screen 1
def verify_identity(d: IdentityIn, request: Request, db=Depends(get_db)):
    rate_limit("ident-ip", client_ip(request), 20, 600); rate_limit("ident-id", id_index(d.id_number), 8, 600)
    u = find_resident(db, d)
    if not u: raise HTTPException(400, BAD)
    return {"has_password": bool(u.password_hash)}


@router.post("/auth/activate")  # screen 2: first-time activation or forgotten password, using the manager's code
def activate(d: ActivateIn, request: Request, db=Depends(get_db)):
    rate_limit("act-ip", client_ip(request), 30, 600); rate_limit("act-id", id_index(d.id_number), 10, 600)
    if err := password_problem(d.password): raise HTTPException(400, err)
    u = find_resident(db, d)
    if not u: raise HTTPException(400, BAD)
    otp = db.scalar(select(OtpCode).where(OtpCode.user_id == u.id).order_by(OtpCode.id.desc()))
    if not otp or otp.expires_at < datetime.now(): raise HTTPException(400, BAD_CODE)
    otp.attempts += 1
    if otp.attempts > config.OTP_MAX_ATTEMPTS:
        db.delete(otp); db.commit(); raise HTTPException(400, "Too many wrong codes. Ask your property manager for a new one.")
    if not hmac.compare_digest(otp.code_hash, hash_secret(d.code)):
        db.commit(); raise HTTPException(400, BAD_CODE)
    db.delete(otp)
    u.password_hash = hash_password(d.password); u.token_version += 1  # signs out any other device
    audit(db, "resident activated account", "user_account", u.id, actor=f"resident #{u.id}", org=u.org_id); db.commit()
    return {"token": make_token("resident", u.id, u.token_version, timedelta(days=config.RESIDENT_TOKEN_DAYS)), "name": u.full_name}


@router.post("/auth/login")
def login(d: LoginIn, request: Request, db=Depends(get_db)):
    rate_limit("rlogin-ip", client_ip(request), 30, 900); rate_limit("rlogin-id", id_index(d.id_number), 8, 900)
    u = find_resident(db, d)
    if not u or not u.password_hash:
        burn_time(d.password); raise HTTPException(401, BAD)  # same answer and timing as a wrong password
    if not check_password(u.password_hash, d.password):
        audit(db, "failed resident sign-in", "user_account", u.id, actor=f"resident #{u.id}", org=u.org_id); db.commit()
        raise HTTPException(401, BAD)
    audit(db, "resident signed in", "user_account", u.id, actor=f"resident #{u.id}", org=u.org_id); db.commit()
    return {"token": make_token("resident", u.id, u.token_version, timedelta(days=config.RESIDENT_TOKEN_DAYS)), "name": u.full_name}


@router.post("/me/logout")
def logout(t=Depends(current_tenancy), db=Depends(get_db)):
    db.get(UserAccount, t.resident_id).token_version += 1; db.commit(); return {"ok": True}


@router.get("/me")
def profile(t=Depends(current_tenancy), db=Depends(get_db)):
    u = db.get(Unit, t.unit_id); b = db.get(Building, u.building_id); p = db.get(Property, b.property_id); r = db.get(UserAccount, t.resident_id)
    unpaid = db.scalars(select(Bill).where(Bill.tenancy_id == t.id, Bill.status != "paid").order_by(Bill.due_date)).all()
    return {"name": r.full_name, "phone": ph.local(r.phone), "unit": u.number, "block": b.name, "property": p.name, "balance": sum(x.amount for x in unpaid),
            "unpaid_count": len(unpaid), "next_due": unpaid[0].due_date.isoformat() if unpaid else None, "payments_simulated": daraja.MOCK}


@router.get("/me/bills")
def my_bills(t=Depends(current_tenancy), db=Depends(get_db)):
    return [row(b) for b in db.scalars(select(Bill).where(Bill.tenancy_id == t.id).order_by(Bill.due_date.desc(), Bill.id.desc()))]


def own_request(db, t, cid):
    r = db.scalar(select(PaymentRequest).where(PaymentRequest.checkout_request_id == cid)); b = db.get(Bill, r.bill_id) if r else None
    if not r or b.tenancy_id != t.id: raise HTTPException(404, "Payment not found")
    return r


class PayIn(BaseModel): bill_id: int; phone: str | None = Field(default=None, max_length=20)
@router.post("/me/pay")
def pay(d: PayIn, request: Request, t=Depends(current_tenancy), db=Depends(get_db)):
    rate_limit("pay", str(t.id), 10, 600)
    b = db.get(Bill, d.bill_id)
    if not b or b.tenancy_id != t.id: raise HTTPException(404, "Bill not found")
    return stk(b, d.phone, db)  # request recorded, bill stays pending until M-Pesa confirms


@router.get("/me/payment/{cid}")
def pay_status(cid: str, t=Depends(current_tenancy), db=Depends(get_db)):
    r = own_request(db, t, cid); tx = db.scalar(select(MpesaTransaction).where(MpesaTransaction.payment_request_id == r.id))
    rc = db.scalar(select(Receipt).join(Payment, Payment.id == Receipt.payment_id).where(Payment.transaction_id == tx.id)) if tx else None
    return {"status": r.status, "mpesa_receipt": tx.mpesa_receipt if tx else None, "receipt": rc.number if rc else None}


if daraja.MOCK:
    @router.post("/me/mock/{cid}/{outcome}")  # development only: pretend the resident entered (or cancelled) the PIN
    def mock_pin(cid: str, outcome: str, t=Depends(current_tenancy), db=Depends(get_db)):
        own_request(db, t, cid); return simulate(cid, outcome, db)


@router.get("/me/receipts")
def my_receipts(t=Depends(current_tenancy), db=Depends(get_db)):
    q = select(Receipt, Payment, Bill).join(Payment, Payment.id == Receipt.payment_id).join(Bill, Bill.id == Payment.bill_id).where(Bill.tenancy_id == t.id).order_by(Receipt.id.desc())
    return [{"number": r.number, "amount": p.amount, "charge": b.charge_type, "period": b.period, "issued_at": r.issued_at.isoformat()} for r, p, b in db.execute(q)]


@router.get("/me/requests")
def my_requests(t=Depends(current_tenancy), db=Depends(get_db)):
    return [row(r, provider=db.get(ServiceProvider, r.provider_id).name if r.provider_id else None)
            for r in db.scalars(select(ServiceRequest).where(ServiceRequest.tenancy_id == t.id).order_by(ServiceRequest.id.desc()))]


class NewReq(BaseModel): category: str = Field(min_length=1, max_length=40); title: str = Field(min_length=1, max_length=200)
@router.post("/me/requests")
def new_request(d: NewReq, t=Depends(current_tenancy), db=Depends(get_db)):
    rate_limit("req", str(t.id), 20, 3600)
    b = db.get(Building, db.get(Unit, t.unit_id).building_id)
    r = ServiceRequest(property_id=b.property_id, tenancy_id=t.id, category=d.category, title=d.title); db.add(r); db.flush()
    audit(db, "request submitted by resident", "service_request", r.id); db.commit(); return row(r)


@router.get("/me/notifications")
def my_notes(t=Depends(current_tenancy), db=Depends(get_db)):
    return [row(n) for n in db.scalars(select(Notification).where(Notification.user_id == t.resident_id).order_by(Notification.id.desc()).limit(20))]
