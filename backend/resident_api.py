"""Resident (mobile) API: phone + one-time-code login, and endpoints scoped to the signed-in resident's own tenancy."""
import hmac, logging, secrets
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
import config, daraja, sms, phone as ph
from crypto import blind_index, hash_secret
from models import (get_db, row, audit, UserAccount, Tenancy, Unit, Building, Property, Bill, PaymentRequest, MpesaTransaction,
                    Payment, Receipt, ServiceRequest, ServiceProvider, Notification, OtpCode)
from security import current_tenancy, make_token, rate_limit, client_ip
from main import stk, simulate, normalize_phone

log = logging.getLogger("proplink.resident")
router = APIRouter(prefix="/api")
GENERIC = "If this number belongs to a resident, a code has been sent by SMS."


def active_resident(db, msisdn):
    for u in db.scalars(select(UserAccount).where(UserAccount.phone_hash == blind_index(msisdn))):
        if db.scalar(select(Tenancy).where(Tenancy.resident_id == u.id, Tenancy.end_date.is_(None))): return u
    return None


class PhoneIn(BaseModel): phone: str = Field(max_length=20)
class VerifyIn(BaseModel): phone: str = Field(max_length=20); code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


@router.post("/auth/request-otp")
def request_otp(d: PhoneIn, request: Request, db=Depends(get_db)):
    msisdn = normalize_phone(d.phone); h = blind_index(msisdn)
    rate_limit("otp-ip", client_ip(request), 10, 3600); rate_limit("otp-phone", h, 3, 600)
    last = db.scalar(select(OtpCode).where(OtpCode.phone_hash == h).order_by(OtpCode.id.desc()))
    if last and last.created_at > datetime.now() - timedelta(seconds=config.OTP_RESEND_SECONDS):
        raise HTTPException(429, "A code was just sent. Wait a minute before asking for another.")
    resident = active_resident(db, msisdn)
    if not resident:  # same answer either way, so nobody can test which numbers are registered
        log.info("Login code requested for an unregistered number"); return {"sent": True, "message": GENERIC}
    code = f"{secrets.randbelow(1_000_000):06d}"
    db.execute(delete(OtpCode).where(OtpCode.phone_hash == h))
    db.add(OtpCode(phone_hash=h, code_hash=hash_secret(code), expires_at=datetime.now() + timedelta(seconds=config.OTP_TTL_SECONDS)))
    try:
        sms.send(msisdn, f"Your PropLink code is {code}. It expires in {config.OTP_TTL_SECONDS // 60} minutes. Never share it with anyone.")
    except sms.SmsError as e:
        log.error("Login code not sent: %s", e); db.rollback()
        raise HTTPException(502, "We couldn't send the SMS right now. Please try again shortly.")
    db.commit()
    out = {"sent": True, "message": GENERIC}
    if config.SMS_PROVIDER == "console" and not config.PRODUCTION: out["dev_code"] = code  # local testing only
    return out


@router.post("/auth/verify")
def verify_otp(d: VerifyIn, request: Request, db=Depends(get_db)):
    rate_limit("verify-ip", client_ip(request), 30, 600)
    msisdn = normalize_phone(d.phone); h = blind_index(msisdn)
    otp = db.scalar(select(OtpCode).where(OtpCode.phone_hash == h).order_by(OtpCode.id.desc()))
    if not otp or otp.expires_at < datetime.now(): raise HTTPException(400, "Wrong or expired code")
    otp.attempts += 1
    if otp.attempts > config.OTP_MAX_ATTEMPTS:
        db.delete(otp); db.commit(); raise HTTPException(400, "Too many wrong codes. Request a new code.")
    if not hmac.compare_digest(otp.code_hash, hash_secret(d.code)):
        db.commit(); raise HTTPException(400, "Wrong or expired code")
    db.delete(otp)
    u = active_resident(db, msisdn)
    if not u: db.commit(); raise HTTPException(400, "Wrong or expired code")
    audit(db, "resident signed in", "user_account", u.id, actor=f"resident #{u.id}"); db.commit()
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