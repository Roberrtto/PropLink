import hmac, logging, random, secrets, string
from datetime import date, datetime, timedelta
from fastapi import FastAPI, APIRouter, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
import config, daraja, scope, phone as ph
from crypto import blind_index, hash_secret, id_index, clean_id
from models import (engine, Session, get_db, Base, row, audit, new_rules, Organization, PaymentAccount, Property, PropertyManager, Building, Unit,
                    UserAccount, StaffUser, Tenancy, BillingConfig, MeterReading, Bill, PaymentRequest, MpesaTransaction, Payment, Receipt,
                    ServiceProvider, ServiceRequest, Rule, Notification, AuditLog, OtpCode)
from security import (current_staff, require_landlord, hash_password, check_password, burn_time, password_problem, make_token,
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


def org_of(db, property_id):
    return db.get(Property, property_id).org_id


def account_for(db, property_id):
    """The landlord's M-Pesa payment details for a property (None until they have entered them)."""
    return db.scalar(select(PaymentAccount).where(PaymentAccount.org_id == org_of(db, property_id)))


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
        if config.SEED_DEMO and not db.scalar(select(func.count()).select_from(Organization)):
            seed_demo(db)
        db.commit()
        if not db.scalar(select(func.count()).select_from(Organization)):
            log.warning("No landlord organisations exist yet. Create the first one with:  python manage.py create-organization")
    log.info("PropLink API ready (%s, M-Pesa %s)", config.APP_ENV, "SIMULATED" if daraja.MOCK else "LIVE")


def seed_demo(db):
    """Fake data for local testing only (SEED_DEMO=1). Never runs in production."""
    o = Organization(name="Demo Properties"); db.add(o); db.flush(); db.add_all(new_rules(o.id))
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
        idn = str(random.randint(20000000, 39999999))
        r = UserAccount(org_id=o.id, full_name=s, phone=msisdn, phone_hash=blind_index(msisdn), id_type="national_id", id_number=idn,
                        id_hash=id_index(idn), date_of_birth="1995-01-01"); db.add(r); db.flush()
        log.warning("DEMO resident -> name: %s  ID: %s  (issue an activation code in the dashboard to sign in)", s, idn)
        db.add(Tenancy(unit_id=u.id, resident_id=r.id, start_date=date(2026, 1, 1)))
        db.add_all([MeterReading(unit_id=u.id, reading_date=date(2026, 9, 30), value=100), MeterReading(unit_id=u.id, reading_date=date(2026, 10, 31), value=100 + random.randint(8, 20))])
    for blk in "AB":
        b = db.scalar(select(Building).where(Building.property_id == p.id, Building.name == blk)); db.add(Unit(building_id=b.id, number=f"{blk}9", rent=19000, status="vacant"))
    db.add_all([ServiceProvider(org_id=o.id, name="FixIt Plumbers", category="Plumbing", phone="254711000111"),
                ServiceProvider(org_id=o.id, name="BrightSpark Electricals", category="Electrical", phone="254722000222")])
    lpw, mpw = secrets.token_urlsafe(9) + "A1", secrets.token_urlsafe(9) + "A1"
    db.add(StaffUser(org_id=o.id, email="landlord@demo.local", full_name="Demo Landlord", password_hash=hash_password(lpw), role="landlord"))
    m = StaffUser(org_id=o.id, email="manager@demo.local", full_name="Demo Manager", password_hash=hash_password(mpw), role="manager"); db.add(m); db.flush()
    db.add(PropertyManager(property_id=p.id, staff_id=m.id))
    log.warning("DEMO landlord login -> email: landlord@demo.local  password: %s", lpw)
    log.warning("DEMO manager login  -> email: manager@demo.local   password: %s", mpw)


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
        audit(db, "failed sign-in", "staff_user", s.id, actor=email, org=s.org_id, actor_id=s.id); db.commit()
        raise HTTPException(401, "Wrong email or password")
    s.failed_logins = 0; s.locked_until = None; s.last_login = datetime.now()
    audit(db, "signed in", "staff_user", s.id, actor=email, org=s.org_id, actor_id=s.id); db.commit()
    return {"token": make_token("staff", s.id, s.token_version, timedelta(hours=config.STAFF_TOKEN_HOURS)),
            "user": row(s, org=db.get(Organization, s.org_id).name)}


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
    return apply_callback(cb, db, verify=True)


def apply_callback(cb: dict, db, verify=False):
    r = db.scalar(select(PaymentRequest).where(PaymentRequest.checkout_request_id == cb.get("CheckoutRequestID")))
    if not r: raise HTTPException(404, "Unknown checkout request")
    if r.status != "pending": return {"ResultCode": 0, "ResultDesc": "Already processed"}  # idempotent
    b = db.get(Bill, r.bill_id); org = org_of(db, b.property_id)
    if cb.get("ResultCode") != 0:
        r.status = "failed"; audit(db, f"payment failed ({cb.get('ResultDesc', '')[:80]})", "payment_request", r.id, "mpesa", org); db.commit()
        return {"ResultCode": 0, "ResultDesc": "Recorded"}
    meta = {i["Name"]: i.get("Value") for i in cb.get("CallbackMetadata", {}).get("Item", [])}
    receipt, amount = meta.get("MpesaReceiptNumber"), int(meta.get("Amount") or 0)
    if not receipt or amount <= 0: raise HTTPException(400, "Malformed callback")
    if verify and not daraja.MOCK:  # callbacks are not signed, so ask Safaricom directly before trusting one
        try:
            q = daraja.stk_query(account_for(db, b.property_id), r.checkout_request_id)
        except daraja.DarajaError as e:
            log.warning("Could not double-check payment %s with M-Pesa (%s); accepting the callback", r.id, e)
        else:
            if q["result_code"] not in (0, None):
                audit(db, "payment callback rejected: M-Pesa does not confirm it", "payment_request", r.id, "mpesa", org); db.commit()
                raise HTTPException(400, "Payment not confirmed")
    if db.scalar(select(MpesaTransaction).where(MpesaTransaction.mpesa_receipt == receipt)): return {"ResultCode": 0, "ResultDesc": "Duplicate"}
    tx = MpesaTransaction(payment_request_id=r.id, mpesa_receipt=receipt, amount=amount); db.add(tx); db.flush()
    pay = Payment(bill_id=r.bill_id, transaction_id=tx.id, amount=amount); db.add(pay); db.flush()
    db.add(Receipt(payment_id=pay.id, number="RCT-" + str(pay.id).zfill(6)))
    r.status = "confirmed"
    paid = db.scalar(select(func.sum(Payment.amount)).where(Payment.bill_id == b.id)) or 0
    if paid >= b.amount: b.status = "paid"  # a short payment is recorded but the bill stays open
    else: audit(db, f"part payment: KES {paid} of {b.amount}", "bill", b.id, "mpesa", org)
    audit(db, "payment confirmed " + receipt, "payment", pay.id, "mpesa", org); db.commit()
    return {"ResultCode": 0, "ResultDesc": "Accepted"}


def stk(bill: Bill, raw_phone: str | None, db):
    """Send an M-Pesa prompt for a bill, paid into the landlord's own account. The bill stays pending until Safaricom confirms."""
    if bill.status == "paid": raise HTTPException(400, "Bill is already paid")
    account = account_for(db, bill.property_id)
    if not daraja.MOCK and not (account and account.ready):
        raise HTTPException(400, "Online payments are not set up for this property yet. Please ask your landlord.")
    msisdn = normalize_phone(raw_phone) if raw_phone else db.get(UserAccount, db.get(Tenancy, bill.tenancy_id).resident_id).phone
    recent = db.scalar(select(PaymentRequest).where(PaymentRequest.bill_id == bill.id, PaymentRequest.status == "pending",
                                                    PaymentRequest.created_at > datetime.now() - timedelta(seconds=60)))
    if recent: raise HTTPException(429, "A payment prompt was just sent for this bill. Check the phone, or wait a minute.")
    paid = db.scalar(select(func.sum(Payment.amount)).where(Payment.bill_id == bill.id)) or 0
    try:
        cid = daraja.stk_push(account, msisdn, bill.amount - paid, f"BILL{bill.id}", bill.charge_type)
    except daraja.DarajaError as e:
        raise HTTPException(502, str(e))
    r = PaymentRequest(bill_id=bill.id, phone=msisdn, amount=bill.amount - paid, checkout_request_id=cid); db.add(r); db.flush()
    audit(db, "payment request sent", "payment_request", r.id, org=org_of(db, bill.property_id)); db.commit()
    return row(r, phone=ph.local(msisdn), simulated=daraja.MOCK)


def simulate(checkout_id: str, outcome: str, db):
    if not daraja.MOCK: raise HTTPException(404, "Not found")
    r = db.scalar(select(PaymentRequest).where(PaymentRequest.checkout_request_id == checkout_id))
    if not r: raise HTTPException(404, "Payment not found")
    cb = {"CheckoutRequestID": checkout_id, "ResultCode": 0 if outcome == "success" else 1032, "ResultDesc": "Simulated"}
    if outcome == "success":
        cb["CallbackMetadata"] = {"Item": [{"Name": "Amount", "Value": r.amount}, {"Name": "MpesaReceiptNumber", "Value": "SIM" + "".join(random.choices(string.ascii_uppercase + string.digits, k=7))}]}
    return apply_callback(cb, db)


# ================= Dashboard API (every route needs a signed-in landlord or manager) =================
# Landlords can use every route for their own organization. Routes marked "landlord only" refuse managers, and every
# record is checked with scope.py so nobody can reach another organization's data, or (for managers) another property.
manager = APIRouter(prefix="/api", dependencies=[Depends(current_staff)])


# ---------- my account and staff accounts ----------
@manager.get("/staff/me")
def staff_me(s=Depends(current_staff), db=Depends(get_db)): return row(s, org=db.get(Organization, s.org_id).name)


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


def staff_out(db, s):
    return row(s, property_ids=list(db.scalars(select(PropertyManager.property_id).where(PropertyManager.staff_id == s.id))))


def assign_properties(db, me, s, pids):
    """Give a manager exactly these properties (landlords automatically see all of theirs)."""
    if s.role != "manager": return
    if set(pids) - scope.property_ids(db, me): raise HTTPException(404, "Property not found")
    db.execute(delete(PropertyManager).where(PropertyManager.staff_id == s.id))
    db.add_all([PropertyManager(property_id=p, staff_id=s.id) for p in set(pids)])


@manager.get("/staff")  # landlord only
def staff_list(me=Depends(require_landlord), db=Depends(get_db)):
    return [staff_out(db, s) for s in db.scalars(select(StaffUser).where(StaffUser.org_id == me.org_id).order_by(StaffUser.id))]


class StaffIn(BaseModel):
    email: str = Field(max_length=254); full_name: str = Name; role: str = "manager"; password: str = Field(max_length=200)
    property_ids: list[int] = []
@manager.post("/staff")  # landlord only
def staff_add(d: StaffIn, me=Depends(require_landlord), db=Depends(get_db)):
    email = d.email.strip().lower()
    if "@" not in email: raise HTTPException(400, "Enter a valid email address")
    if d.role not in ("landlord", "manager"): raise HTTPException(400, "Role must be landlord or manager")
    if err := password_problem(d.password): raise HTTPException(400, err)
    if db.scalar(select(StaffUser).where(StaffUser.email == email)): raise HTTPException(400, "That email already has an account")
    s = StaffUser(org_id=me.org_id, email=email, full_name=d.full_name.strip(), role=d.role, password_hash=hash_password(d.password)); db.add(s); db.flush()
    assign_properties(db, me, s, d.property_ids)
    audit(db, f"staff account created ({d.role})", "staff_user", s.id, details=f"{email}; properties {sorted(set(d.property_ids))}"); db.commit(); return staff_out(db, s)


class StaffUpdate(BaseModel):
    active: bool | None = None; role: str | None = None; password: str | None = Field(default=None, max_length=200); property_ids: list[int] | None = None
@manager.patch("/staff/{sid}")  # landlord only
def staff_update(sid: int, d: StaffUpdate, me=Depends(require_landlord), db=Depends(get_db)):
    s = db.get(StaffUser, sid)
    if not s or s.org_id != me.org_id: raise HTTPException(404, "Staff account not found")
    if s.id == me.id and (d.active is False or (d.role and d.role != "landlord")): raise HTTPException(400, "You can't remove your own landlord access")
    if d.role is not None:
        if d.role not in ("landlord", "manager"): raise HTTPException(400, "Role must be landlord or manager")
        s.role = d.role
        if s.role == "landlord": db.execute(delete(PropertyManager).where(PropertyManager.staff_id == s.id))
    if d.active is not None: s.active = d.active
    if d.password:
        if err := password_problem(d.password): raise HTTPException(400, err)
        s.password_hash = hash_password(d.password); s.locked_until = None; s.failed_logins = 0
    if d.property_ids is not None: assign_properties(db, me, s, d.property_ids)
    s.token_version += 1  # any change signs that person out everywhere
    ch = ["password reset" if k == "password" else f"{k}={val}" for k, val in d.model_dump(exclude_none=True).items()]
    audit(db, "staff account changed", "staff_user", sid, details=f"{s.email}: " + ", ".join(ch)); db.commit(); return staff_out(db, s)


# ---------- landlord's payment details (where the rent money goes) ----------
def payment_out(a):
    return {"configured": bool(a and a.ready), "tx_type": a.tx_type if a else "paybill", "shortcode": a.shortcode if a else "", "party_b": a.party_b if a else "",
            "has_key": bool(a and a.consumer_key), "has_secret": bool(a and a.consumer_secret), "has_passkey": bool(a and a.passkey), "simulated": daraja.MOCK}


@manager.get("/payment-account")  # landlord only
def get_payment_account(me=Depends(require_landlord), db=Depends(get_db)):
    return payment_out(db.scalar(select(PaymentAccount).where(PaymentAccount.org_id == me.org_id)))


class PaymentAccountIn(BaseModel):
    tx_type: str; shortcode: str = Field(pattern=r"^\d{5,7}$"); party_b: str | None = Field(default=None, pattern=r"^(\d{5,7})?$")
    consumer_key: str | None = Field(default=None, max_length=200); consumer_secret: str | None = Field(default=None, max_length=200)
    passkey: str | None = Field(default=None, max_length=300)
@manager.post("/payment-account")  # landlord only; leave a secret blank to keep the one already saved
def save_payment_account(d: PaymentAccountIn, me=Depends(require_landlord), db=Depends(get_db)):
    if d.tx_type not in ("paybill", "till"): raise HTTPException(400, "Type must be paybill or till")
    a = db.scalar(select(PaymentAccount).where(PaymentAccount.org_id == me.org_id))
    if not a: a = PaymentAccount(org_id=me.org_id); db.add(a)
    a.tx_type, a.shortcode, a.party_b, a.updated_at = d.tx_type, d.shortcode, d.party_b or "", datetime.now()
    for k in ("consumer_key", "consumer_secret", "passkey"):
        v = (getattr(d, k) or "").strip()
        if v: setattr(a, k, v)
    changed = any((getattr(d, k) or "").strip() for k in ("consumer_key", "consumer_secret", "passkey"))
    audit(db, "payment details saved", "payment_account", None, details=f"{a.tx_type} shortcode {a.shortcode}; secrets replaced: {'yes' if changed else 'no'}"); db.commit()
    return payment_out(a)


class TestPay(BaseModel): phone: str = Field(max_length=20)
@manager.post("/payment-account/test")  # landlord only: sends KES 1 to the landlord's own phone
def test_payment_account(d: TestPay, me=Depends(require_landlord), db=Depends(get_db)):
    a = db.scalar(select(PaymentAccount).where(PaymentAccount.org_id == me.org_id))
    try:
        daraja.stk_push(a, normalize_phone(d.phone), 1, "TEST", "PropLink test")
    except daraja.DarajaError as e:
        raise HTTPException(400, str(e))
    audit(db, "payment test sent", "payment_account", None); db.commit()
    return {"sent": True, "simulated": daraja.MOCK}


# ---------- properties and overview ----------
@manager.get("/properties")
def properties(s=Depends(current_staff), db=Depends(get_db)):
    return [row(p) for p in db.scalars(select(Property).where(Property.id.in_(scope.property_ids(db, s))).order_by(Property.id))]


class PropertyIn(BaseModel): name: str = Name; address: str = Field(min_length=1, max_length=200)
@manager.post("/properties")  # landlord only
def add_property(d: PropertyIn, me=Depends(require_landlord), db=Depends(get_db)):
    p = Property(org_id=me.org_id, name=d.name.strip(), address=d.address.strip()); db.add(p); db.flush()
    db.add(BillingConfig(property_id=p.id, charge_type="Rent", method="rent", rate=0, due_day=5))
    audit(db, "property created", "property", p.id, details=f"{p.name}, {p.address}"); db.commit(); return row(p)


@manager.get("/overview")
def overview(pid: int, s=Depends(current_staff), db=Depends(get_db)):
    scope.own_property(db, s, pid)
    n = lambda e: db.scalar(e) or 0
    units = select(func.count()).select_from(Unit).join(Building).where(Building.property_id == pid)
    out = {"outstanding": n(select(func.sum(Bill.amount)).where(Bill.property_id == pid, Bill.status != "paid")),
           "occupied": n(units.where(Unit.status == "occupied")), "total_units": n(units),
           "open_requests": n(select(func.count()).select_from(ServiceRequest).where(ServiceRequest.property_id == pid, ServiceRequest.status != "Completed"))}
    if s.role == "landlord":  # money received is for landlords only
        recent = db.scalars(select(PaymentRequest).join(Bill).where(Bill.property_id == pid).order_by(PaymentRequest.id.desc()).limit(6))
        rows = []
        for r in recent:
            b = db.get(Bill, r.bill_id); rows.append({"unit": tinfo(db, b.tenancy_id)["unit"], "charge": b.charge_type, "amount": r.amount, "status": r.status})
        out |= {"collected": n(select(func.sum(Payment.amount)).join(Bill, Bill.id == Payment.bill_id).where(Bill.property_id == pid, Bill.charge_type == "Rent")), "recent": rows}
    return out


# ---------- units ----------
@manager.get("/units")
def units(pid: int, s=Depends(current_staff), db=Depends(get_db)):
    scope.own_property(db, s, pid)
    out = []
    for u, b in db.execute(select(Unit, Building).join(Building).where(Building.property_id == pid).order_by(Building.name, Unit.id)):
        t = db.scalar(select(Tenancy).where(Tenancy.unit_id == u.id, Tenancy.end_date.is_(None)))
        out.append(row(u, building=b.name, tenancy_id=t.id if t else None, resident=db.get(UserAccount, t.resident_id).full_name if t else None))
    return out


class UnitIn(BaseModel): property_id: int; building: str = Field(min_length=1, max_length=20); number: str = Field(min_length=1, max_length=20); rent: int = Money
@manager.post("/units")  # landlord only
def add_unit(d: UnitIn, me=Depends(require_landlord), db=Depends(get_db)):
    scope.own_property(db, me, d.property_id)
    b = db.scalar(select(Building).where(Building.property_id == d.property_id, Building.name == d.building))
    if not b: b = Building(property_id=d.property_id, name=d.building); db.add(b); db.flush()
    u = Unit(building_id=b.id, number=d.number, rent=d.rent); db.add(u); db.flush(); audit(db, "create unit", "unit", u.id, details=f"block {b.name}, unit {u.number}, rent KES {u.rent}"); db.commit(); return row(u)


# ---------- residents: register, view, edit, move, remove, activation code ----------
def age(dob: date) -> int:
    t = date.today(); return t.year - dob.year - ((t.month, t.day) < (dob.month, dob.day))


def balance(db, tid):
    """What a tenancy still owes: unpaid bills minus any part payments already made toward them."""
    billed = db.scalar(select(func.sum(Bill.amount)).where(Bill.tenancy_id == tid, Bill.status != "paid")) or 0
    paid = db.scalar(select(func.sum(Payment.amount)).join(Bill, Bill.id == Payment.bill_id).where(Bill.tenancy_id == tid, Bill.status != "paid")) or 0
    return billed - paid


class ResidentIn(BaseModel):
    full_name: str = Name; date_of_birth: date; id_type: str = "national_id"
    id_number: str = Field(min_length=5, max_length=20); phone: str = Field(max_length=20)
    email: str | None = Field(default=None, max_length=254)
    guardian_name: str | None = Field(default=None, max_length=100); guardian_phone: str | None = Field(default=None, max_length=20)
    unit_id: int
@manager.post("/residents")
def register_resident(d: ResidentIn, s=Depends(current_staff), db=Depends(get_db)):
    u = scope.own_unit(db, s, d.unit_id)
    if u.status == "occupied": raise HTTPException(400, "Unit is not vacant")
    if d.id_type not in ("national_id", "passport"): raise HTTPException(400, "ID type must be national_id or passport")
    if len(clean_id(d.id_number)) < 5: raise HTTPException(400, "Enter a valid ID or passport number")
    if d.date_of_birth >= date.today(): raise HTTPException(400, "Date of birth must be in the past")
    if age(d.date_of_birth) < 18 and not (d.guardian_name and d.guardian_phone):
        raise HTTPException(400, "A parent or guardian's name and phone are required for residents under 18")
    msisdn = normalize_phone(d.phone); gphone = normalize_phone(d.guardian_phone) if d.guardian_phone else None
    h = id_index(d.id_number)
    r = db.scalar(select(UserAccount).where(UserAccount.org_id == s.org_id, UserAccount.id_hash == h))
    if r and db.scalar(select(Tenancy).where(Tenancy.resident_id == r.id, Tenancy.end_date.is_(None))):
        raise HTTPException(400, "This ID already belongs to a resident with an active tenancy")
    f = dict(full_name=d.full_name.strip(), date_of_birth=d.date_of_birth.isoformat(), id_type=d.id_type, id_number=clean_id(d.id_number),
             id_hash=h, phone=msisdn, phone_hash=blind_index(msisdn), email=d.email, guardian_name=d.guardian_name, guardian_phone=gphone)
    if r:  # a returning resident of this landlord keeps their account
        for k, v in f.items(): setattr(r, k, v)
    else:
        r = UserAccount(org_id=s.org_id, **f); db.add(r); db.flush()
    t = Tenancy(unit_id=u.id, resident_id=r.id, start_date=date.today()); u.status = "occupied"; db.add(t); db.flush()
    audit(db, "resident registered", "tenancy", t.id); db.commit()
    return {"resident_id": r.id, "tenancy_id": t.id}


@manager.get("/residents")
def residents(pid: int, s=Depends(current_staff), db=Depends(get_db)):
    scope.own_property(db, s, pid)
    q = (select(Tenancy, Unit, Building, UserAccount).join(Unit, Unit.id == Tenancy.unit_id).join(Building, Building.id == Unit.building_id)
         .join(UserAccount, UserAccount.id == Tenancy.resident_id).where(Building.property_id == pid, Tenancy.end_date.is_(None)).order_by(Building.name, Unit.number))
    return [{"resident_id": r.id, "tenancy_id": t.id, "name": r.full_name, "phone": ph.local(r.phone), "unit": u.number, "building": b.name,
             "balance": balance(db, t.id),
             "open_requests": db.scalar(select(func.count()).select_from(ServiceRequest).where(ServiceRequest.tenancy_id == t.id, ServiceRequest.status != "Completed")) or 0}
            for t, u, b, r in db.execute(q)]


@manager.get("/residents/{rid}")
def resident_detail(rid: int, s=Depends(current_staff), db=Depends(get_db)):
    r, t = scope.own_resident(db, s, rid)
    u = db.get(Unit, t.unit_id); b = db.get(Building, u.building_id)
    return {"resident_id": r.id, "tenancy_id": t.id, "name": r.full_name, "id_type": r.id_type, "id_number": r.id_number, "date_of_birth": r.date_of_birth,
            "phone": ph.local(r.phone), "email": r.email, "guardian_name": r.guardian_name, "guardian_phone": ph.local(r.guardian_phone),
            "unit": u.number, "building": b.name, "since": t.start_date.isoformat(), "balance": balance(db, t.id),
            "bills": [row(x) for x in db.scalars(select(Bill).where(Bill.tenancy_id == t.id).order_by(Bill.due_date.desc()))],
            "requests": [row(x) for x in db.scalars(select(ServiceRequest).where(ServiceRequest.tenancy_id == t.id).order_by(ServiceRequest.id.desc()))]}


class ResidentEdit(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=100); date_of_birth: date | None = None
    id_type: str | None = None; id_number: str | None = Field(default=None, min_length=5, max_length=20)
    phone: str | None = Field(default=None, max_length=20); email: str | None = Field(default=None, max_length=254)
    guardian_name: str | None = Field(default=None, max_length=100); guardian_phone: str | None = Field(default=None, max_length=20)
@manager.patch("/residents/{rid}")
def edit_resident(rid: int, d: ResidentEdit, s=Depends(current_staff), db=Depends(get_db)):
    r, _ = scope.own_resident(db, s, rid); v = d.model_dump(exclude_none=True)
    if "id_type" in v and v["id_type"] not in ("national_id", "passport"): raise HTTPException(400, "ID type must be national_id or passport")
    if "id_number" in v:
        h = id_index(v["id_number"])
        if db.scalar(select(UserAccount).where(UserAccount.org_id == s.org_id, UserAccount.id_hash == h, UserAccount.id != r.id)): raise HTTPException(400, "Another resident already has that ID")
        r.id_number = clean_id(v["id_number"]); r.id_hash = h
    old_phone = r.phone
    if "phone" in v: r.phone = normalize_phone(v["phone"]); r.phone_hash = blind_index(r.phone)
    if "guardian_phone" in v: r.guardian_phone = normalize_phone(v["guardian_phone"])
    if "full_name" in v: r.full_name = v["full_name"].strip()
    if "date_of_birth" in v: r.date_of_birth = v["date_of_birth"].isoformat()
    for k in ("id_type", "email", "guardian_name"):
        if k in v: setattr(r, k, v[k])
    what = ", ".join(sorted(v)) + (f"; phone ending {old_phone[-3:]} to {r.phone[-3:]}" if "phone" in v else "")
    audit(db, "resident details edited", "user_account", rid, details="changed: " + what); db.commit(); return {"ok": True}


@manager.post("/tenancies/{tid}/end")  # remove a resident who is leaving; history is kept
def end(tid: int, s=Depends(current_staff), db=Depends(get_db)):
    t = scope.own_tenancy(db, s, tid)
    if t.end_date: raise HTTPException(400, "Tenancy already ended")
    t.end_date = date.today(); db.get(Unit, t.unit_id).status = "vacant"
    db.get(UserAccount, t.resident_id).token_version += 1  # sign the former resident out of the app
    audit(db, "end tenancy", "tenancy", tid, details=f"unit {db.get(Unit, t.unit_id).number} is now vacant"); db.commit(); return row(t)


class TransferIn(BaseModel): unit_id: int
@manager.post("/tenancies/{tid}/transfer")  # move to another unit in the same building
def transfer(tid: int, d: TransferIn, s=Depends(current_staff), db=Depends(get_db)):
    t = scope.own_tenancy(db, s, tid)
    if t.end_date: raise HTTPException(400, "Tenancy already ended")
    old, new = db.get(Unit, t.unit_id), scope.own_unit(db, s, d.unit_id)
    if new.id == old.id: raise HTTPException(400, "Resident is already in that unit")
    if new.building_id != old.building_id: raise HTTPException(400, "Residents can only move to another unit in the same building")
    if new.status == "occupied": raise HTTPException(400, "That unit is not vacant")
    t.end_date = date.today(); old.status = "vacant"; new.status = "occupied"
    nt = Tenancy(unit_id=new.id, resident_id=t.resident_id, start_date=date.today()); db.add(nt); db.flush()
    for b in db.scalars(select(Bill).where(Bill.tenancy_id == t.id, Bill.status != "paid")): b.tenancy_id = nt.id  # unpaid bills follow them
    for q in db.scalars(select(ServiceRequest).where(ServiceRequest.tenancy_id == t.id, ServiceRequest.status != "Completed")): q.tenancy_id = nt.id
    audit(db, f"resident moved {old.number} to {new.number}", "tenancy", nt.id); db.commit(); return {"tenancy_id": nt.id}


@manager.post("/tenancies/{tid}/activation-code")  # the manager gives this to the resident; it lasts OTP_TTL_SECONDS (2 minutes)
def activation_code(tid: int, s=Depends(current_staff), db=Depends(get_db)):
    t = scope.own_tenancy(db, s, tid)
    if t.end_date: raise HTTPException(400, "Tenancy has ended")
    code = f"{secrets.randbelow(1_000_000):06d}"
    db.execute(delete(OtpCode).where(OtpCode.user_id == t.resident_id))  # one live code per resident
    db.add(OtpCode(user_id=t.resident_id, code_hash=hash_secret(code), expires_at=datetime.now() + timedelta(seconds=config.OTP_TTL_SECONDS)))
    audit(db, "activation code issued", "user_account", t.resident_id); db.commit()
    return {"code": code, "expires_in_seconds": config.OTP_TTL_SECONDS}


class MeterIn(BaseModel): unit_id: int; value: int = Field(ge=0, le=100_000_000)
@manager.post("/meter-readings")
def meter(d: MeterIn, s=Depends(current_staff), db=Depends(get_db)):
    scope.own_unit(db, s, d.unit_id)
    m = MeterReading(unit_id=d.unit_id, reading_date=date.today(), value=d.value); db.add(m); audit(db, "meter reading", "unit", d.unit_id); db.commit(); return row(m)


# ---------- billing (managers can post charges and see what residents owe) ----------
@manager.get("/billing-configs")
def configs(pid: int, s=Depends(current_staff), db=Depends(get_db)):
    scope.own_property(db, s, pid)
    return [row(c) for c in db.scalars(select(BillingConfig).where(BillingConfig.property_id == pid))]


class ConfigIn(BaseModel): property_id: int; charge_type: str = Field(min_length=1, max_length=40); method: str; rate: int = Money; due_day: int = Field(default=5, ge=1, le=28)
@manager.post("/billing-configs")  # landlord only
def add_config(d: ConfigIn, me=Depends(require_landlord), db=Depends(get_db)):
    scope.own_property(db, me, d.property_id)
    if d.method not in ("rent", "fixed", "metered"): raise HTTPException(400, "method must be rent, fixed or metered")
    c = BillingConfig(**d.model_dump()); db.add(c); db.flush(); audit(db, "billing rule created", "billing_config", c.id, details=f"{c.charge_type}, {c.method}, rate KES {c.rate}, due day {c.due_day}"); db.commit(); return row(c)


@manager.delete("/billing-configs/{cid}")  # landlord only
def del_config(cid: int, me=Depends(require_landlord), db=Depends(get_db)):
    c = scope.own_config(db, me, cid); note = f"{c.charge_type} ({c.method})"; db.delete(c)
    audit(db, "billing rule deleted", "billing_config", cid, details=note); db.commit(); return {"ok": True}


class GenIn(BaseModel): property_id: int; period: str | None = Field(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
@manager.post("/bills/generate")
def generate(d: GenIn, s=Depends(current_staff), db=Depends(get_db)):
    scope.own_property(db, s, d.property_id)
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


class BulkIn(BaseModel):
    property_id: int; charge_type: str = Field(min_length=1, max_length=40); amount: int = Field(gt=0, le=10_000_000)
    period: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$"); due_date: date
    building: str | None = None; rent: int | None = Field(default=None, ge=0, le=10_000_000)
@manager.post("/charges/bulk")  # one charge for all occupied units, one building, or units with the same rent
def bulk_charge(d: BulkIn, s=Depends(current_staff), db=Depends(get_db)):
    scope.own_property(db, s, d.property_id)
    q = (select(Tenancy).join(Unit, Unit.id == Tenancy.unit_id).join(Building, Building.id == Unit.building_id)
         .where(Building.property_id == d.property_id, Tenancy.end_date.is_(None)))
    if d.building: q = q.where(Building.name == d.building)
    if d.rent is not None: q = q.where(Unit.rent == d.rent)
    made = skipped = 0
    for t in db.scalars(q):
        if db.scalar(select(Bill).where(Bill.tenancy_id == t.id, Bill.charge_type == d.charge_type, Bill.period == d.period, Bill.service_request_id.is_(None))):
            skipped += 1; continue
        db.add(Bill(property_id=d.property_id, tenancy_id=t.id, charge_type=d.charge_type, period=d.period, amount=d.amount, due_date=d.due_date)); made += 1
    audit(db, f"bulk charge {d.charge_type} {d.period}: {made} bills", "bill",
          details=f"KES {d.amount} each; block {d.building or 'all'}; rent {d.rent if d.rent is not None else 'any'}; skipped {skipped}"); db.commit()
    return {"created": made, "skipped": skipped}


@manager.get("/bills")
def bills(pid: int, s=Depends(current_staff), db=Depends(get_db)):
    scope.own_property(db, s, pid)
    return [row(b, **tinfo(db, b.tenancy_id)) for b in db.scalars(select(Bill).where(Bill.property_id == pid).order_by(Bill.id.desc()))]


# ---------- payments (landlord only: this is where money moves) ----------
class StkIn(BaseModel): bill_id: int; phone: str | None = Field(default=None, max_length=20)
@manager.post("/payments/stk")  # landlord only
def manager_stk(d: StkIn, me=Depends(require_landlord), db=Depends(get_db)):
    return stk(scope.own_bill(db, me, d.bill_id), d.phone, db)


@manager.get("/payments")  # landlord only
def payments(pid: int, me=Depends(require_landlord), db=Depends(get_db)):
    scope.own_property(db, me, pid)
    out = []
    for r in db.scalars(select(PaymentRequest).join(Bill).where(Bill.property_id == pid).order_by(PaymentRequest.id.desc())):
        b = db.get(Bill, r.bill_id); tx = db.scalar(select(MpesaTransaction).where(MpesaTransaction.payment_request_id == r.id))
        rc = db.scalar(select(Receipt).join(Payment).where(Payment.transaction_id == tx.id)) if tx else None
        out.append(row(r, charge=b.charge_type, period=b.period, mpesa_receipt=tx.mpesa_receipt if tx else None, receipt=rc.number if rc else None,
                       **(tinfo(db, b.tenancy_id) | {"phone": ph.local(r.phone)})))
    return out


if daraja.MOCK:
    @manager.post("/mock/daraja/{checkout_id}/{outcome}")  # development simulator; does not exist when M-Pesa is live
    def manager_simulate(checkout_id: str, outcome: str, me=Depends(require_landlord), db=Depends(get_db)):
        scope.own_payment_request(db, me, checkout_id); return simulate(checkout_id, outcome, db)


# ---------- providers & maintenance ----------
@manager.get("/providers")
def providers(s=Depends(current_staff), db=Depends(get_db)):
    return [row(p, phone=ph.local(p.phone)) for p in db.scalars(select(ServiceProvider).where(ServiceProvider.org_id == s.org_id))]


class ProviderIn(BaseModel): name: str = Name; category: str = Field(min_length=1, max_length=40); phone: str = Field(max_length=20)
@manager.post("/providers")  # landlord only
def add_provider(d: ProviderIn, me=Depends(require_landlord), db=Depends(get_db)):
    p = ServiceProvider(org_id=me.org_id, name=d.name.strip(), category=d.category.strip(), phone=normalize_phone(d.phone)); db.add(p); db.flush()
    audit(db, "provider added", "service_provider", p.id); db.commit(); return row(p, phone=ph.local(p.phone))


@manager.post("/providers/{id}/toggle")  # landlord only
def toggle_provider(id: int, me=Depends(require_landlord), db=Depends(get_db)):
    p = scope.own_provider(db, me, id); p.approved = not p.approved
    audit(db, "provider approval changed", "service_provider", id); db.commit(); return row(p, phone=ph.local(p.phone))


@manager.get("/requests")
def requests(pid: int, s=Depends(current_staff), db=Depends(get_db)):
    scope.own_property(db, s, pid)
    return [row(r, provider=(db.get(ServiceProvider, r.provider_id).name if r.provider_id else None), **tinfo(db, r.tenancy_id))
            for r in db.scalars(select(ServiceRequest).where(ServiceRequest.property_id == pid).order_by(ServiceRequest.id.desc()))]


class ReqIn(BaseModel): property_id: int | None = None; unit_id: int; category: str = Field(min_length=1, max_length=40); title: str = Field(min_length=1, max_length=200)
@manager.post("/requests")
def add_request(d: ReqIn, s=Depends(current_staff), db=Depends(get_db)):
    u = scope.own_unit(db, s, d.unit_id)
    t = db.scalar(select(Tenancy).where(Tenancy.unit_id == u.id, Tenancy.end_date.is_(None)))
    if not t: raise HTTPException(400, "Unit has no active resident")
    r = ServiceRequest(property_id=scope.unit_property(db, u), tenancy_id=t.id, category=d.category, title=d.title); db.add(r); db.flush()
    audit(db, "request logged", "service_request", r.id); db.commit(); return row(r)


STATUSES = ("Submitted", "Assigned", "In Progress", "Completed")
class ReqUpdate(BaseModel): provider_id: int | None = None; status: str | None = None; cost: int | None = Field(default=None, ge=0, le=10_000_000); hours: int | None = Field(default=None, ge=0, le=10_000); work_note: str | None = Field(default=None, max_length=2000)
@manager.patch("/requests/{rid}")
def update_request(rid: int, d: ReqUpdate, s=Depends(current_staff), db=Depends(get_db)):
    r = scope.own_service(db, s, rid)
    if d.status is not None and d.status not in STATUSES: raise HTTPException(400, "Unknown status")
    if d.provider_id:
        p = scope.own_provider(db, s, d.provider_id)
        if not p.approved: raise HTTPException(400, "Provider is not approved")
        r.provider_id = p.id; r.status = "Assigned"
    for k in ("status", "cost", "hours", "work_note"):
        if getattr(d, k) is not None: setattr(r, k, getattr(d, k))
    r.updated_at = datetime.now(); audit(db, f"request now {r.status}", "service_request", rid,
          details=", ".join(f"{k}={getattr(d, k)}" for k in ("provider_id", "status", "cost", "hours") if getattr(d, k) is not None) or None); db.commit(); return row(r)


@manager.post("/requests/{rid}/clear")  # the resident is satisfied, so the manager closes the request
def clear_request(rid: int, s=Depends(current_staff), db=Depends(get_db)):
    r = scope.own_service(db, s, rid)
    if r.status == "Completed": raise HTTPException(400, "Already cleared")
    r.status = "Completed"; r.updated_at = datetime.now()
    db.add(Notification(user_id=db.get(Tenancy, r.tenancy_id).resident_id, type="update", message=f"Your request '{r.title}' has been closed"))
    audit(db, "request cleared (resident satisfied)", "service_request", rid); db.commit(); return row(r)


@manager.post("/requests/{rid}/charge")  # turn a completed job's cost into a bill on the resident's account
def charge(rid: int, s=Depends(current_staff), db=Depends(get_db)):
    r = scope.own_service(db, s, rid)
    if r.cost <= 0: raise HTTPException(400, "Record a cost first")
    if db.scalar(select(Bill).where(Bill.service_request_id == r.id)): raise HTTPException(400, "This job has already been billed")
    b = Bill(property_id=r.property_id, tenancy_id=r.tenancy_id, service_request_id=r.id, charge_type=f"Service: {r.category}", period=date.today().strftime("%Y-%m"),
             amount=r.cost, due_date=date.today() + timedelta(days=7)); db.add(b); db.flush(); audit(db, "service charge billed", "bill", b.id); db.commit(); return row(b)


# ---------- reports, audit, automation (landlord only) ----------
@manager.get("/reports")  # landlord only
def reports(pid: int, me=Depends(require_landlord), db=Depends(get_db)):
    scope.own_property(db, me, pid)
    grp = lambda e: [{"label": a, "value": int(b or 0)} for a, b in db.execute(e)]
    return {"collected": grp(select(Bill.charge_type, func.sum(Payment.amount)).join(Payment, Payment.bill_id == Bill.id).where(Bill.property_id == pid).group_by(Bill.charge_type)),
            "outstanding": grp(select(Bill.charge_type, func.sum(Bill.amount)).where(Bill.property_id == pid, Bill.status != "paid").group_by(Bill.charge_type)),
            "maintenance": grp(select(ServiceRequest.category, func.sum(ServiceRequest.cost)).where(ServiceRequest.property_id == pid).group_by(ServiceRequest.category)),
            "unresolved": db.scalar(select(func.count()).select_from(ServiceRequest).where(ServiceRequest.property_id == pid, ServiceRequest.status != "Completed"))}


@manager.get("/audit")  # landlord only
def audit_log(me=Depends(require_landlord), db=Depends(get_db)):
    return [row(a) for a in db.scalars(select(AuditLog).where(AuditLog.org_id == me.org_id).order_by(AuditLog.id.desc()).limit(100))]


@manager.get("/rules")
def rules(s=Depends(current_staff), db=Depends(get_db)):
    return [row(r) for r in db.scalars(select(Rule).where(Rule.org_id == s.org_id).order_by(Rule.id))]


class RuleIn(BaseModel): threshold: int | None = Field(default=None, ge=1, le=10_000); enabled: bool | None = None
@manager.patch("/rules/{rid}")  # landlord only
def edit_rule(rid: int, d: RuleIn, me=Depends(require_landlord), db=Depends(get_db)):
    r = db.get(Rule, rid)
    if not r or r.org_id != me.org_id: raise HTTPException(404, "Rule not found")
    if d.threshold is not None: r.threshold = d.threshold
    if d.enabled is not None: r.enabled = d.enabled
    audit(db, "automation rule changed", "rule", rid, details=f"{r.kind}: threshold {r.threshold}, {'on' if r.enabled else 'off'}"); db.commit(); return row(r)


@manager.post("/automation/run")  # landlord only
def run_rules_now(me=Depends(require_landlord), db=Depends(get_db)): return run_rules(db, me.org_id)


def run_rules(db, org_id=None):
    """Apply each organization's automation rules to its own properties (all organizations when org_id is None)."""
    log_ = []
    q = select(Rule).where(Rule.enabled)
    if org_id is not None: q = q.where(Rule.org_id == org_id)
    for r in db.scalars(q):
        pids = select(Property.id).where(Property.org_id == r.org_id)
        if r.kind == "overdue_bill":
            for b in db.scalars(select(Bill).where(Bill.property_id.in_(pids), Bill.status == "pending", Bill.due_date < date.today() - timedelta(days=r.threshold))):
                b.status = "overdue"; t = db.get(Tenancy, b.tenancy_id)
                db.add(Notification(user_id=t.resident_id, type="reminder", message=f"{b.charge_type} {b.period} (KES {b.amount}) is overdue")); log_.append(f"Bill {b.id} marked overdue, reminder sent")
        else:
            for sr in db.scalars(select(ServiceRequest).where(ServiceRequest.property_id.in_(pids), ServiceRequest.status == "Assigned", ServiceRequest.updated_at < datetime.now() - timedelta(hours=r.threshold))):
                db.add(Notification(property_id=sr.property_id, type="alert", message=f"Request #{sr.id} '{sr.title}' has had no update for {r.threshold}h")); log_.append(f"Staff alerted: request {sr.id} stalled")
    audit(db, f"automation ran ({len(log_)} actions)", "rule", None, org=org_id); db.commit(); return {"actions": log_}


@manager.get("/notifications")
def notifications(s=Depends(current_staff), db=Depends(get_db)):
    ids = scope.property_ids(db, s)
    return [row(n) for n in db.scalars(select(Notification).where(Notification.user_id.is_(None), Notification.property_id.in_(ids)).order_by(Notification.id.desc()).limit(20))]


app.include_router(manager)

from resident_api import router as resident_router  # resident mobile API  # noqa: E402
app.include_router(resident_router)
