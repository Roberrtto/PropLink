import hmac, logging, random, secrets, string
from datetime import date, datetime, timedelta
from fastapi import FastAPI, APIRouter, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import func, select
import config, daraja, phone as ph
from crypto import blind_index
from models import (engine, Session, get_db, Base, row, audit, Organization, Property, Building, Unit, UserAccount, StaffUser, Tenancy,
                    BillingConfig, MeterReading, Bill, PaymentRequest, MpesaTransaction, Payment, Receipt, ServiceProvider, ServiceRequest,
                    Rule, Notification, AuditLog)
from security import (current_staff, require_admin, hash_password, check_password, burn_time, password_problem, make_token,
                      rate_limit, client_ip)

log = logging.getLogger("proplink")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

Name = Field(min_length=1, max_length=100)
Money = Field(ge=0, le=10_000_000)


def get_or_404(db, model, id_, what="Record"):
    o = db.get(model, id_) if id_ is not None else None
    if not o: raise HTTPException(404, f"{what} not found")
    return o


def normalize_phone(raw: str) -> str:
    try:
        return ph.normalize(raw)
    except ph.InvalidPhone as e:
        raise HTTPException(400, str(e))


def tinfo(db, tid):
    t = db.get(Tenancy, tid); u = db.get(Unit, t.unit_id); r = db.get(UserAccount, t.resident_id)
    return {"unit": u.number, "resident": r.full_name, "phone": ph.local(r.phone)}


# ---------- app, security headers, CORS ----------
app = FastAPI(title="PropLink API", docs_url=None if config.PRODUCTION else "/docs",
              redoc_url=None, openapi_url=None if config.PRODUCTION else "/openapi.json")
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_methods=["GET", "POST", "PATCH", "DELETE"],
                   allow_headers=["Authorization", "Content-Type"])


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Cache-Control"] = "no-store"
    if config.PRODUCTION: resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return resp


# ---------- startup ----------
@app.on_event("startup")
def startup():
    Base.metadata.create_all(engine)
    with Session() as db:
        if not db.scalar(select(func.count()).select_from(Organization)):
            db.add(Organization(name=config.ORG_NAME)); db.flush()
        if not db.scalar(select(func.count()).select_from(Rule)):
            db.add_all([Rule(kind="overdue_bill", threshold=5), Rule(kind="stalled_request", threshold=48)])
        if config.SEED_DEMO and not db.scalar(select(func.count()).select_from(Property)):
            seed_demo(db)
        db.commit()
        if not db.scalar(select(func.count()).select_from(StaffUser)):
            log.warning("No dashboard accounts exist yet. Create the first admin with:  python manage.py create-admin")
    log.info("PropLink API ready (%s, M-Pesa %s, SMS %s)", config.APP_ENV, "SIMULATED" if daraja.MOCK else "LIVE", config.SMS_PROVIDER)


def seed_demo(db):
    """Fake data for local testing only (SEED_DEMO=1). Never runs in production."""
    o = db.scalar(select(Organization))
    p = Property(org_id=o.id, name="Riverside Court (demo)", address="Ngong Road, Nairobi"); db.add(p); db.flush()
    for cfg in [("Rent", "rent", 0, 5), ("Water", "metered", 150, 25), ("Internet", "fixed", 3500, 10), ("Garbage", "fixed", 1000, 28)]:
        db.add(BillingConfig(property_id=p.id, charge_type=cfg[0], method=cfg[1], rate=cfg[2], due_day=cfg[3]))
    for i, s in enumerate(["Mercy Wanjiku", "Brian Otieno", "Amina Hassan", "Peter Kamau", "Grace Njeri", "Dan Mutua", "Lucy Akinyi", "Joseph Kiptoo"]):
        blk = "ABC"[i % 3]
        b = db.scalar(select(Building).where(Building.property_id == p.id, Building.name == blk)) or Building(property_id=p.id, name=blk)
        if not b.id: db.add(b); db.flush()
        n = db.scalar(select(func.count()).select_from(Unit).where(Unit.building_id == b.id)) + 1
        u = Unit(building_id=b.id, number=f"{blk}{n}", rent=random.choice([18000, 20000, 22000]), status="occupied"); db.add(u); db.flush()
        msisdn = f"2547{random.randint(10000000, 29999999)}"
        r = UserAccount(full_name=s, phone=msisdn, phone_hash=blind_index(msisdn)); db.add(r); db.flush()
        db.add(Tenancy(unit_id=u.id, resident_id=r.id, start_date=date(2026, 1, 1)))
        db.add_all([MeterReading(unit_id=u.id, reading_date=date(2026, 9, 30), value=100), MeterReading(unit_id=u.id, reading_date=date(2026, 10, 31), value=100 + random.randint(8, 20))])
    for blk in "AB":
        b = db.scalar(select(Building).where(Building.property_id == p.id, Building.name == blk)); db.add(Unit(building_id=b.id, number=f"{blk}9", rent=19000, status="vacant"))
    db.add_all([ServiceProvider(name="FixIt Plumbers", category="Plumbing", phone="254711000111"), ServiceProvider(name="BrightSpark Electricals", category="Electrical", phone="254722000222")])
    if not db.scalar(select(func.count()).select_from(StaffUser)):
        pw = secrets.token_urlsafe(9) + "A1"
        db.add(StaffUser(email="admin@demo.local", full_name="Demo Admin", password_hash=hash_password(pw), role="admin"))
        log.warning("DEMO dashboard login -> email: admin@demo.local  password: %s", pw)


# ---------- public ----------
@app.get("/api/health")
def health(): return {"ok": True}


@app.get("/api/config")
def public_config(): return {"payments_simulated": daraja.MOCK, "environment": config.APP_ENV}


class LoginIn(BaseModel): email: str = Field(max_length=254); password: str = Field(max_length=200)
@app.post("/api/staff/login")
def staff_login(d: LoginIn, request: Request, db=Depends(get_db)):
    email = d.email.strip().lower()
    rate_limit("login-ip", client_ip(request), 20, 900); rate_limit("login-email", email, 10, 900)
    s = db.scalar(select(StaffUser).where(StaffUser.email == email))
    if not s or not s.active:
        burn_time(d.password); raise HTTPException(401, "Wrong email or password")
    if s.locked_until and s.locked_until > datetime.now():
        raise HTTPException(429, "Account temporarily locked after too many wrong passwords. Try again in 15 minutes.")
    if not check_password(s.password_hash, d.password):
        s.failed_logins += 1
        if s.failed_logins >= 5: s.locked_until = datetime.now() + timedelta(minutes=15); s.failed_logins = 0
        audit(db, "failed sign-in", "staff_user", s.id, actor=email); db.commit()
        raise HTTPException(401, "Wrong email or password")
    s.failed_logins = 0; s.locked_until = None; s.last_login = datetime.now()
    audit(db, "signed in", "staff_user", s.id, actor=email); db.commit()
    return {"token": make_token("staff", s.id, s.token_version, timedelta(hours=config.STAFF_TOKEN_HOURS)),
            "user": row(s)}


# ---------- M-Pesa callback (called by Safaricom, protected by a secret URL and optional IP allowlist) ----------
@app.post("/api/mpesa/callback/{token}")
def mpesa_callback(token: str, body: dict, request: Request, db=Depends(get_db)):
    if not hmac.compare_digest(token.encode(), config.MPESA_CALLBACK_TOKEN.encode()):
        raise HTTPException(404, "Not found")
    if config.MPESA_ALLOWED_IPS and client_ip(request) not in config.MPESA_ALLOWED_IPS:
        log.warning("Rejected M-Pesa callback from %s", client_ip(request)); raise HTTPException(403, "Forbidden")
    try:
        cb = body["Body"]["stkCallback"]
    except (KeyError, TypeError):
        raise HTTPException(400, "Malformed callback")
    return apply_callback(cb, db)


def apply_callback(cb: dict, db):
    r = db.scalar(select(PaymentRequest).where(PaymentRequest.checkout_request_id == cb.get("CheckoutRequestID")))
    if not r: raise HTTPException(404, "Unknown checkout request")
    if r.status != "pending": return {"ResultCode": 0, "ResultDesc": "Already processed"}  # idempotent
    if cb.get("ResultCode") != 0:
        r.status = "failed"; audit(db, f"payment failed ({cb.get('ResultDesc', '')[:80]})", "payment_request", r.id, "mpesa"); db.commit()
        return {"ResultCode": 0, "ResultDesc": "Recorded"}
    meta = {i["Name"]: i.get("Value") for i in cb.get("CallbackMetadata", {}).get("Item", [])}
    receipt, amount = meta.get("MpesaReceiptNumber"), int(meta.get("Amount") or 0)
    if not receipt or amount <= 0: raise HTTPException(400, "Malformed callback")
    if db.scalar(select(MpesaTransaction).where(MpesaTransaction.mpesa_receipt == receipt)): return {"ResultCode": 0, "ResultDesc": "Duplicate"}
    tx = MpesaTransaction(payment_request_id=r.id, mpesa_receipt=receipt, amount=amount); db.add(tx); db.flush()
    pay = Payment(bill_id=r.bill_id, transaction_id=tx.id, amount=amount); db.add(pay); db.flush()
    db.add(Receipt(payment_id=pay.id, number="RCT-" + str(pay.id).zfill(6)))
    r.status = "confirmed"; b = db.get(Bill, r.bill_id)
    paid = db.scalar(select(func.sum(Payment.amount)).where(Payment.bill_id == b.id)) or 0
    if paid >= b.amount: b.status = "paid"  # a short payment is recorded but the bill stays open
    else: audit(db, f"part payment: KES {paid} of {b.amount}", "bill", b.id, "mpesa")
    audit(db, "payment confirmed " + receipt, "payment", pay.id, "mpesa"); db.commit()
    return {"ResultCode": 0, "ResultDesc": "Accepted"}


def stk(bill: Bill, raw_phone: str | None, db):
    """Send an M-Pesa prompt for a bill. The bill stays pending until Safaricom confirms."""
    if bill.status == "paid": raise HTTPException(400, "Bill is already paid")
    msisdn = normalize_phone(raw_phone) if raw_phone else db.get(UserAccount, db.get(Tenancy, bill.tenancy_id).resident_id).phone
    recent = db.scalar(select(PaymentRequest).where(PaymentRequest.bill_id == bill.id, PaymentRequest.status == "pending",
                                                    PaymentRequest.created_at > datetime.now() - timedelta(seconds=60)))
    if recent: raise HTTPException(429, "A payment prompt was just sent for this bill. Check the phone, or wait a minute.")
    paid = db.scalar(select(func.sum(Payment.amount)).where(Payment.bill_id == bill.id)) or 0
    try:
        cid = daraja.stk_push(msisdn, bill.amount - paid, f"BILL{bill.id}", bill.charge_type)
    except daraja.DarajaError as e:
        raise HTTPException(502, str(e))
    r = PaymentRequest(bill_id=bill.id, phone=msisdn, amount=bill.amount - paid, checkout_request_id=cid); db.add(r); db.flush()
    audit(db, "payment request sent", "payment_request", r.id); db.commit()
    return row(r, phone=ph.local(msisdn), simulated=daraja.MOCK)


def simulate(checkout_id: str, outcome: str, db):
    if not daraja.MOCK: raise HTTPException(404, "Not found")
    r = db.scalar(select(PaymentRequest).where(PaymentRequest.checkout_request_id == checkout_id))
    if not r: raise HTTPException(404, "Payment not found")
    cb = {"CheckoutRequestID": checkout_id, "ResultCode": 0 if outcome == "success" else 1032, "ResultDesc": "Simulated"}
    if outcome == "success":
        cb["CallbackMetadata"] = {"Item": [{"Name": "Amount", "Value": r.amount}, {"Name": "MpesaReceiptNumber", "Value": "SIM" + "".join(random.choices(string.ascii_uppercase + string.digits, k=7))}]}
    return apply_callback(cb, db)


# ================= Manager dashboard API (every route needs a signed-in staff member) =================
manager = APIRouter(prefix="/api", dependencies=[Depends(current_staff)])


# ---------- staff accounts ----------
@manager.get("/staff/me")
def staff_me(s=Depends(current_staff)): return row(s)


@manager.post("/staff/logout")
def staff_logout(s=Depends(current_staff), db=Depends(get_db)):
    s.token_version += 1; audit(db, "signed out", "staff_user", s.id); db.commit(); return {"ok": True}


class PasswordIn(BaseModel): current_password: str; new_password: str = Field(max_length=200)
@manager.post("/staff/me/password")
def change_password(d: PasswordIn, s=Depends(current_staff), db=Depends(get_db)):
    if not check_password(s.password_hash, d.current_password): raise HTTPException(400, "Current password is wrong")
    if err := password_problem(d.new_password): raise HTTPException(400, err)
    s.password_hash = hash_password(d.new_password); s.token_version += 1
    audit(db, "changed password", "staff_user", s.id); db.commit()
    return {"token": make_token("staff", s.id, s.token_version, timedelta(hours=config.STAFF_TOKEN_HOURS))}


@manager.get("/staff")
def staff_list(_=Depends(require_admin), db=Depends(get_db)): return [row(s) for s in db.scalars(select(StaffUser).order_by(StaffUser.id))]


class StaffIn(BaseModel): email: str = Field(max_length=254); full_name: str = Name; role: str = "manager"; password: str = Field(max_length=200)
@manager.post("/staff")
def staff_add(d: StaffIn, _=Depends(require_admin), db=Depends(get_db)):
    email = d.email.strip().lower()
    if "@" not in email: raise HTTPException(400, "Enter a valid email address")
    if d.role not in ("admin", "manager"): raise HTTPException(400, "Role must be admin or manager")
    if err := password_problem(d.password): raise HTTPException(400, err)
    if db.scalar(select(StaffUser).where(StaffUser.email == email)): raise HTTPException(400, "That email already has an account")
    s = StaffUser(email=email, full_name=d.full_name.strip(), role=d.role, password_hash=hash_password(d.password)); db.add(s); db.flush()
    audit(db, f"staff account created ({d.role})", "staff_user", s.id); db.commit(); return row(s)


class StaffUpdate(BaseModel): active: bool | None = None; role: str | None = None; password: str | None = Field(default=None, max_length=200)
@manager.patch("/staff/{sid}")
def staff_update(sid: int, d: StaffUpdate, me=Depends(require_admin), db=Depends(get_db)):
    s = get_or_404(db, StaffUser, sid, "Staff account")
    if s.id == me.id and (d.active is False or (d.role and d.role != "admin")): raise HTTPException(400, "You can't remove your own admin access")
    if d.role is not None:
        if d.role not in ("admin", "manager"): raise HTTPException(400, "Role must be admin or manager")
        s.role = d.role
    if d.active is not None: s.active = d.active
    if d.password:
        if err := password_problem(d.password): raise HTTPException(400, err)
        s.password_hash = hash_password(d.password); s.locked_until = None; s.failed_logins = 0
    s.token_version += 1  # any change signs that person out everywhere
    audit(db, "staff account changed", "staff_user", sid); db.commit(); return row(s)


# ---------- overview ----------
@manager.get("/properties")
def properties(db=Depends(get_db)): return [row(p) for p in db.scalars(select(Property).order_by(Property.id))]


class PropertyIn(BaseModel): name: str = Name; address: str = Field(min_length=1, max_length=200)
@manager.post("/properties")
def add_property(d: PropertyIn, _=Depends(require_admin), db=Depends(get_db)):
    o = db.scalar(select(Organization))
    p = Property(org_id=o.id, name=d.name.strip(), address=d.address.strip()); db.add(p); db.flush()
    db.add_all([BillingConfig(property_id=p.id, charge_type="Rent", method="rent", rate=0, due_day=5)])
    audit(db, "property created", "property", p.id); db.commit(); return row(p)


@manager.get("/overview")
def overview(pid: int, db=Depends(get_db)):
    n = lambda e: db.scalar(e) or 0
    units = select(func.count()).select_from(Unit).join(Building).where(Building.property_id == pid)
    recent = db.scalars(select(PaymentRequest).join(Bill).where(Bill.property_id == pid).order_by(PaymentRequest.id.desc()).limit(6))
    out = []
    for r in recent:
        b = db.get(Bill, r.bill_id); out.append({"unit": tinfo(db, b.tenancy_id)["unit"], "charge": b.charge_type, "amount": r.amount, "status": r.status})
    return {"collected": n(select(func.sum(Payment.amount)).join(Bill, Bill.id == Payment.bill_id).where(Bill.property_id == pid, Bill.charge_type == "Rent")),
            "outstanding": n(select(func.sum(Bill.amount)).where(Bill.property_id == pid, Bill.status != "paid")),
            "occupied": n(units.where(Unit.status == "occupied")), "total_units": n(units),
            "open_requests": n(select(func.count()).select_from(ServiceRequest).where(ServiceRequest.property_id == pid, ServiceRequest.status != "Completed")),
            "recent": out}


# ---------- properties, units, tenancies, meters ----------
@manager.get("/units")
def units(pid: int, db=Depends(get_db)):
    out = []
    for u, b in db.execute(select(Unit, Building).join(Building).where(Building.property_id == pid).order_by(Building.name, Unit.id)):
        t = db.scalar(select(Tenancy).where(Tenancy.unit_id == u.id, Tenancy.end_date.is_(None)))
        out.append(row(u, building=b.name, tenancy_id=t.id if t else None, resident=db.get(UserAccount, t.resident_id).full_name if t else None))
    return out


class UnitIn(BaseModel): property_id: int; building: str = Field(min_length=1, max_length=20); number: str = Field(min_length=1, max_length=20); rent: int = Money
@manager.post("/units")
def add_unit(d: UnitIn, db=Depends(get_db)):
    get_or_404(db, Property, d.property_id, "Property")
    b = db.scalar(select(Building).where(Building.property_id == d.property_id, Building.name == d.building))
    if not b: b = Building(property_id=d.property_id, name=d.building); db.add(b); db.flush()
    u = Unit(building_id=b.id, number=d.number, rent=d.rent); db.add(u); db.flush(); audit(db, "create unit", "unit", u.id); db.commit(); return row(u)


class TenancyIn(BaseModel): unit_id: int; full_name: str = Name; phone: str = Field(max_length=20)
@manager.post("/tenancies")
def assign(d: TenancyIn, db=Depends(get_db)):
    u = get_or_404(db, Unit, d.unit_id, "Unit")
    if u.status == "occupied": raise HTTPException(400, "Unit is not vacant")
    msisdn = normalize_phone(d.phone); h = blind_index(msisdn)
    r = db.scalar(select(UserAccount).where(UserAccount.phone_hash == h))  # the same person keeps one account
    if r:
        if db.scalar(select(Tenancy).where(Tenancy.resident_id == r.id, Tenancy.end_date.is_(None))):
            raise HTTPException(400, "That phone number already belongs to a resident with an active tenancy")
        r.full_name = d.full_name.strip()
    else:
        r = UserAccount(full_name=d.full_name.strip(), phone=msisdn, phone_hash=h); db.add(r); db.flush()
    t = Tenancy(unit_id=u.id, resident_id=r.id, start_date=date.today()); u.status = "occupied"; db.add(t); db.flush()
    audit(db, "assign resident", "tenancy", t.id); db.commit(); return row(t)


@manager.post("/tenancies/{tid}/end")
def end(tid: int, db=Depends(get_db)):
    t = get_or_404(db, Tenancy, tid, "Tenancy")
    if t.end_date: raise HTTPException(400, "Tenancy already ended")
    t.end_date = date.today(); db.get(Unit, t.unit_id).status = "vacant"
    db.get(UserAccount, t.resident_id).token_version += 1  # sign the former resident out of the app
    audit(db, "end tenancy", "tenancy", tid); db.commit(); return row(t)


class MeterIn(BaseModel): unit_id: int; value: int = Field(ge=0, le=100_000_000)
@manager.post("/meter-readings")
def meter(d: MeterIn, db=Depends(get_db)):
    get_or_404(db, Unit, d.unit_id, "Unit")
    m = MeterReading(unit_id=d.unit_id, reading_date=date.today(), value=d.value); db.add(m); audit(db, "meter reading", "unit", d.unit_id); db.commit(); return row(m)


# ---------- billing ----------
@manager.get("/billing-configs")
def configs(pid: int, db=Depends(get_db)): return [row(c) for c in db.scalars(select(BillingConfig).where(BillingConfig.property_id == pid))]


class ConfigIn(BaseModel): property_id: int; charge_type: str = Field(min_length=1, max_length=40); method: str; rate: int = Money; due_day: int = Field(default=5, ge=1, le=28)
@manager.post("/billing-configs")
def add_config(d: ConfigIn, db=Depends(get_db)):
    get_or_404(db, Property, d.property_id, "Property")
    if d.method not in ("rent", "fixed", "metered"): raise HTTPException(400, "method must be rent, fixed or metered")
    c = BillingConfig(**d.model_dump()); db.add(c); db.flush(); audit(db, "billing rule created", "billing_config", c.id); db.commit(); return row(c)


@manager.delete("/billing-configs/{cid}")
def del_config(cid: int, db=Depends(get_db)):
    db.delete(get_or_404(db, BillingConfig, cid, "Billing rule")); audit(db, "billing rule deleted", "billing_config", cid); db.commit(); return {"ok": True}


class GenIn(BaseModel): property_id: int; period: str | None = Field(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
@manager.post("/bills/generate")
def generate(d: GenIn, db=Depends(get_db)):
    get_or_404(db, Property, d.property_id, "Property")
    period = d.period or date.today().strftime("%Y-%m"); y, m = map(int, period.split("-")); made = 0
    cfgs = db.scalars(select(BillingConfig).where(BillingConfig.property_id == d.property_id)).all()
    for t, u in db.execute(select(Tenancy, Unit).join(Unit).join(Building).where(Building.property_id == d.property_id, Tenancy.end_date.is_(None))):
        for c in cfgs:
            if db.scalar(select(Bill).where(Bill.tenancy_id == t.id, Bill.charge_type == c.charge_type, Bill.period == period, Bill.service_request_id.is_(None))): continue
            if c.method == "rent": amt = u.rent
            elif c.method == "fixed": amt = c.rate
            else:
                rs = db.scalars(select(MeterReading).where(MeterReading.unit_id == u.id).order_by(MeterReading.reading_date.desc(), MeterReading.id.desc()).limit(2)).all()
                amt = (rs[0].value - rs[1].value) * c.rate if len(rs) == 2 else 0
            if amt > 0:
                db.add(Bill(property_id=d.property_id, tenancy_id=t.id, charge_type=c.charge_type, period=period, amount=amt, due_date=date(y, m, min(c.due_day, 28)))); made += 1
    audit(db, f"generated {made} bills for {period}", "bill"); db.commit(); return {"created": made, "period": period}


@manager.get("/bills")
def bills(pid: int, db=Depends(get_db)):
    return [row(b, **tinfo(db, b.tenancy_id)) for b in db.scalars(select(Bill).where(Bill.property_id == pid).order_by(Bill.id.desc()))]


# ---------- payments ----------
class StkIn(BaseModel): bill_id: int; phone: str | None = Field(default=None, max_length=20)
@manager.post("/payments/stk")
def manager_stk(d: StkIn, db=Depends(get_db)):
    return stk(get_or_404(db, Bill, d.bill_id, "Bill"), d.phone, db)


@manager.get("/payments")
def payments(pid: int, db=Depends(get_db)):
    out = []
    for r in db.scalars(select(PaymentRequest).join(Bill).where(Bill.property_id == pid).order_by(PaymentRequest.id.desc())):
        b = db.get(Bill, r.bill_id); tx = db.scalar(select(MpesaTransaction).where(MpesaTransaction.payment_request_id == r.id))
        rc = db.scalar(select(Receipt).join(Payment).where(Payment.transaction_id == tx.id)) if tx else None
        out.append(row(r, charge=b.charge_type, period=b.period, mpesa_receipt=tx.mpesa_receipt if tx else None, receipt=rc.number if rc else None,
                       **(tinfo(db, b.tenancy_id) | {"phone": ph.local(r.phone)})))
    return out


if daraja.MOCK:
    @manager.post("/mock/daraja/{checkout_id}/{outcome}")  # development simulator; does not exist when M-Pesa is live
    def manager_simulate(checkout_id: str, outcome: str, db=Depends(get_db)): return simulate(checkout_id, outcome, db)


# ---------- providers & maintenance ----------
@manager.get("/providers")
def providers(db=Depends(get_db)): return [row(p, phone=ph.local(p.phone)) for p in db.scalars(select(ServiceProvider))]


class ProviderIn(BaseModel): name: str = Name; category: str = Field(min_length=1, max_length=40); phone: str = Field(max_length=20)
@manager.post("/providers")
def add_provider(d: ProviderIn, db=Depends(get_db)):
    p = ServiceProvider(name=d.name.strip(), category=d.category.strip(), phone=normalize_phone(d.phone)); db.add(p); db.flush()
    audit(db, "provider added", "service_provider", p.id); db.commit(); return row(p, phone=ph.local(p.phone))


@manager.post("/providers/{id}/toggle")
def toggle_provider(id: int, db=Depends(get_db)):
    p = get_or_404(db, ServiceProvider, id, "Provider"); p.approved = not p.approved
    audit(db, "provider approval changed", "service_provider", id); db.commit(); return row(p, phone=ph.local(p.phone))


@manager.get("/requests")
def requests(pid: int, db=Depends(get_db)):
    return [row(r, provider=(db.get(ServiceProvider, r.provider_id).name if r.provider_id else None), **tinfo(db, r.tenancy_id))
            for r in db.scalars(select(ServiceRequest).where(ServiceRequest.property_id == pid).order_by(ServiceRequest.id.desc()))]


class ReqIn(BaseModel): property_id: int; unit_id: int; category: str = Field(min_length=1, max_length=40); title: str = Field(min_length=1, max_length=200)
@manager.post("/requests")
def add_request(d: ReqIn, db=Depends(get_db)):
    t = db.scalar(select(Tenancy).where(Tenancy.unit_id == d.unit_id, Tenancy.end_date.is_(None)))
    if not t: raise HTTPException(400, "Unit has no active resident")
    r = ServiceRequest(property_id=d.property_id, tenancy_id=t.id, category=d.category, title=d.title); db.add(r); db.flush()
    audit(db, "request logged", "service_request", r.id); db.commit(); return row(r)


STATUSES = ("Submitted", "Assigned", "In Progress", "Completed")
class ReqUpdate(BaseModel): provider_id: int | None = None; status: str | None = None; cost: int | None = Field(default=None, ge=0, le=10_000_000); hours: int | None = Field(default=None, ge=0, le=10_000); work_note: str | None = Field(default=None, max_length=2000)
@manager.patch("/requests/{rid}")
def update_request(rid: int, d: ReqUpdate, db=Depends(get_db)):
    r = get_or_404(db, ServiceRequest, rid, "Request")
    if d.status is not None and d.status not in STATUSES: raise HTTPException(400, "Unknown status")
    if d.provider_id:
        p = db.get(ServiceProvider, d.provider_id)
        if not p or not p.approved: raise HTTPException(400, "Provider is not approved")
        r.provider_id = p.id; r.status = "Assigned"
    for k in ("status", "cost", "hours", "work_note"):
        if getattr(d, k) is not None: setattr(r, k, getattr(d, k))
    r.updated_at = datetime.now(); audit(db, f"request now {r.status}", "service_request", rid); db.commit(); return row(r)


@manager.post("/requests/{rid}/charge")  # turn a completed job's cost into a bill on the resident's account
def charge(rid: int, db=Depends(get_db)):
    r = get_or_404(db, ServiceRequest, rid, "Request")
    if r.cost <= 0: raise HTTPException(400, "Record a cost first")
    if db.scalar(select(Bill).where(Bill.service_request_id == r.id)): raise HTTPException(400, "This job has already been billed")
    b = Bill(property_id=r.property_id, tenancy_id=r.tenancy_id, service_request_id=r.id, charge_type=f"Service: {r.category}", period=date.today().strftime("%Y-%m"),
             amount=r.cost, due_date=date.today() + timedelta(days=7)); db.add(b); db.flush(); audit(db, "service charge billed", "bill", b.id); db.commit(); return row(b)


# ---------- reports, audit, automation ----------
@manager.get("/reports")
def reports(pid: int, db=Depends(get_db)):
    grp = lambda e: [{"label": a, "value": int(b or 0)} for a, b in db.execute(e)]
    return {"collected": grp(select(Bill.charge_type, func.sum(Payment.amount)).join(Payment, Payment.bill_id == Bill.id).where(Bill.property_id == pid).group_by(Bill.charge_type)),
            "outstanding": grp(select(Bill.charge_type, func.sum(Bill.amount)).where(Bill.property_id == pid, Bill.status != "paid").group_by(Bill.charge_type)),
            "maintenance": grp(select(ServiceRequest.category, func.sum(ServiceRequest.cost)).where(ServiceRequest.property_id == pid).group_by(ServiceRequest.category)),
            "unresolved": db.scalar(select(func.count()).select_from(ServiceRequest).where(ServiceRequest.property_id == pid, ServiceRequest.status != "Completed"))}


@manager.get("/audit")
def audit_log(db=Depends(get_db)): return [row(a) for a in db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(100))]


@manager.get("/rules")
def rules(db=Depends(get_db)): return [row(r) for r in db.scalars(select(Rule).order_by(Rule.id))]


class RuleIn(BaseModel): threshold: int | None = Field(default=None, ge=1, le=10_000); enabled: bool | None = None
@manager.patch("/rules/{rid}")
def edit_rule(rid: int, d: RuleIn, db=Depends(get_db)):
    r = get_or_404(db, Rule, rid, "Rule")
    if d.threshold is not None: r.threshold = d.threshold
    if d.enabled is not None: r.enabled = d.enabled
    audit(db, "automation rule changed", "rule", rid); db.commit(); return row(r)


@manager.post("/automation/run")
def run_rules_now(db=Depends(get_db)): return run_rules(db)


def run_rules(db):
    log_ = []
    for r in db.scalars(select(Rule).where(Rule.enabled)):
        if r.kind == "overdue_bill":
            for b in db.scalars(select(Bill).where(Bill.status == "pending", Bill.due_date < date.today() - timedelta(days=r.threshold))):
                b.status = "overdue"; t = db.get(Tenancy, b.tenancy_id)
                db.add(Notification(user_id=t.resident_id, type="reminder", message=f"{b.charge_type} {b.period} (KES {b.amount}) is overdue")); log_.append(f"Bill {b.id} marked overdue, reminder sent")
        else:
            for s in db.scalars(select(ServiceRequest).where(ServiceRequest.status == "Assigned", ServiceRequest.updated_at < datetime.now() - timedelta(hours=r.threshold))):
                db.add(Notification(type="alert", message=f"Request #{s.id} '{s.title}' has had no update for {r.threshold}h")); log_.append(f"Manager alerted: request {s.id} stalled")
    audit(db, f"automation ran ({len(log_)} actions)", "rule", None); db.commit(); return {"actions": log_}


@manager.get("/notifications")
def notifications(db=Depends(get_db)): return [row(n) for n in db.scalars(select(Notification).where(Notification.user_id.is_(None)).order_by(Notification.id.desc()).limit(20))]


app.include_router(manager)

from resident_api import router as resident_router  # resident mobile API  # noqa: E402
app.include_router(resident_router)