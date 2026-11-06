import os, random, string
from datetime import date, datetime, timedelta
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine, String, Integer, Date, DateTime, ForeignKey, Boolean, Text, func, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
import daraja

engine = create_engine(os.getenv("DATABASE_URL", "postgresql+psycopg2://proplink:proplink@127.0.0.1:5433/proplink"))
Session = sessionmaker(engine, expire_on_commit=False)
def get_db():
    with Session() as db:
        yield db

class Base(DeclarativeBase): pass
def pk(): return mapped_column(Integer, primary_key=True)
def fk(t, null=False): return mapped_column(ForeignKey(t), nullable=null)

class Organization(Base):
    __tablename__ = "organization"; id: Mapped[int] = pk(); name: Mapped[str] = mapped_column(String)
class Property(Base):
    __tablename__ = "property"; id: Mapped[int] = pk(); org_id: Mapped[int] = fk("organization.id")
    name: Mapped[str] = mapped_column(String); address: Mapped[str] = mapped_column(String)
class Building(Base):
    __tablename__ = "building"; id: Mapped[int] = pk(); property_id: Mapped[int] = fk("property.id"); name: Mapped[str] = mapped_column(String)
class Unit(Base):
    __tablename__ = "unit"; id: Mapped[int] = pk(); building_id: Mapped[int] = fk("building.id")
    number: Mapped[str] = mapped_column(String); rent: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String, default="vacant")
class UserAccount(Base):
    __tablename__ = "user_account"; id: Mapped[int] = pk(); full_name: Mapped[str] = mapped_column(String)
    phone: Mapped[str] = mapped_column(String); role: Mapped[str] = mapped_column(String, default="resident")
class Tenancy(Base):
    __tablename__ = "tenancy"; id: Mapped[int] = pk(); unit_id: Mapped[int] = fk("unit.id"); resident_id: Mapped[int] = fk("user_account.id")
    start_date: Mapped[date] = mapped_column(Date); end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
class BillingConfig(Base):  # method: rent (unit rent) | fixed (flat rate) | metered (rate x units used)
    __tablename__ = "billing_config"; id: Mapped[int] = pk(); property_id: Mapped[int] = fk("property.id")
    charge_type: Mapped[str] = mapped_column(String); method: Mapped[str] = mapped_column(String)
    rate: Mapped[int] = mapped_column(Integer, default=0); due_day: Mapped[int] = mapped_column(Integer, default=5)
class MeterReading(Base):
    __tablename__ = "meter_reading"; id: Mapped[int] = pk(); unit_id: Mapped[int] = fk("unit.id")
    reading_date: Mapped[date] = mapped_column(Date); value: Mapped[int] = mapped_column(Integer)
class Bill(Base):
    __tablename__ = "bill"; id: Mapped[int] = pk(); property_id: Mapped[int] = fk("property.id"); tenancy_id: Mapped[int] = fk("tenancy.id")
    service_request_id: Mapped[int | None] = fk("service_request.id", True)
    charge_type: Mapped[str] = mapped_column(String); period: Mapped[str] = mapped_column(String)
    amount: Mapped[int] = mapped_column(Integer); due_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String, default="pending")  # pending | paid | overdue
class PaymentRequest(Base):  # an attempt; NOT proof of payment
    __tablename__ = "payment_request"; id: Mapped[int] = pk(); bill_id: Mapped[int] = fk("bill.id")
    phone: Mapped[str] = mapped_column(String); amount: Mapped[int] = mapped_column(Integer)
    checkout_request_id: Mapped[str] = mapped_column(String, unique=True)
    status: Mapped[str] = mapped_column(String, default="pending")  # pending | confirmed | failed
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
class MpesaTransaction(Base):  # confirmed fact, never overwritten
    __tablename__ = "mpesa_transaction"; id: Mapped[int] = pk(); payment_request_id: Mapped[int] = mapped_column(ForeignKey("payment_request.id"), unique=True)
    mpesa_receipt: Mapped[str] = mapped_column(String, unique=True); amount: Mapped[int] = mapped_column(Integer)
    confirmed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
class Payment(Base):
    __tablename__ = "payment"; id: Mapped[int] = pk(); bill_id: Mapped[int] = fk("bill.id")
    transaction_id: Mapped[int] = mapped_column(ForeignKey("mpesa_transaction.id"), unique=True)
    amount: Mapped[int] = mapped_column(Integer); paid_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
class Receipt(Base):
    __tablename__ = "receipt"; id: Mapped[int] = pk(); payment_id: Mapped[int] = mapped_column(ForeignKey("payment.id"), unique=True)
    number: Mapped[str] = mapped_column(String, unique=True); issued_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
class ServiceProvider(Base):
    __tablename__ = "service_provider"; id: Mapped[int] = pk(); name: Mapped[str] = mapped_column(String)
    category: Mapped[str] = mapped_column(String); phone: Mapped[str] = mapped_column(String); approved: Mapped[bool] = mapped_column(Boolean, default=True)
class ServiceRequest(Base):  # status: Submitted | Assigned | In Progress | Completed
    __tablename__ = "service_request"; id: Mapped[int] = pk(); property_id: Mapped[int] = fk("property.id"); tenancy_id: Mapped[int] = fk("tenancy.id")
    provider_id: Mapped[int | None] = fk("service_provider.id", True); category: Mapped[str] = mapped_column(String)
    title: Mapped[str] = mapped_column(String); status: Mapped[str] = mapped_column(String, default="Submitted")
    cost: Mapped[int] = mapped_column(Integer, default=0); hours: Mapped[int] = mapped_column(Integer, default=0)
    work_note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now); updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
class Rule(Base):  # kind: overdue_bill (days) | stalled_request (hours)
    __tablename__ = "rule"; id: Mapped[int] = pk(); kind: Mapped[str] = mapped_column(String); threshold: Mapped[int] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
class Notification(Base):
    __tablename__ = "notification"; id: Mapped[int] = pk(); user_id: Mapped[int | None] = fk("user_account.id", True)
    type: Mapped[str] = mapped_column(String); message: Mapped[str] = mapped_column(String)
    read: Mapped[bool] = mapped_column(Boolean, default=False); created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
class AuditLog(Base):
    __tablename__ = "audit_log"; id: Mapped[int] = pk(); actor: Mapped[str] = mapped_column(String); action: Mapped[str] = mapped_column(String)
    entity: Mapped[str] = mapped_column(String); entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

def row(o, **extra):
    d = {c.name: (v.isoformat() if isinstance(v := getattr(o, c.name), (date, datetime)) else v) for c in o.__table__.columns}
    return d | extra
def audit(db, action, entity, eid=None, actor="manager"):
    db.add(AuditLog(actor=actor, action=action, entity=entity, entity_id=eid))
def tinfo(db, tid):
    t = db.get(Tenancy, tid); u = db.get(Unit, t.unit_id); r = db.get(UserAccount, t.resident_id)
    return {"unit": u.number, "resident": r.full_name, "phone": r.phone}

app = FastAPI(title="PropLink Manager API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.on_event("startup")
def startup():
    Base.metadata.create_all(engine)
    with Session() as db:
        if db.scalar(select(func.count()).select_from(Organization)): return
        o = Organization(name="Riverside Holdings"); db.add(o); db.flush()
        p = Property(org_id=o.id, name="Riverside Court", address="Ngong Road, Nairobi"); db.add(p); db.flush()
        for cfg in [("Rent", "rent", 0, 5), ("Water", "metered", 150, 25), ("Internet", "fixed", 3500, 10), ("Garbage", "fixed", 1000, 28)]:
            db.add(BillingConfig(property_id=p.id, charge_type=cfg[0], method=cfg[1], rate=cfg[2], due_day=cfg[3]))
        for i, s in enumerate(["Mercy Wanjiku", "Brian Otieno", "Amina Hassan", "Peter Kamau", "Grace Njeri", "Dan Mutua", "Lucy Akinyi", "Joseph Kiptoo"]):
            blk = "ABC"[i % 3]
            b = db.scalar(select(Building).where(Building.property_id == p.id, Building.name == blk)) or Building(property_id=p.id, name=blk)
            if not b.id: db.add(b); db.flush()
            n = db.scalar(select(func.count()).select_from(Unit).where(Unit.building_id == b.id)) + 1
            u = Unit(building_id=b.id, number=f"{blk}{n}", rent=random.choice([18000, 20000, 22000]), status="occupied"); db.add(u); db.flush()
            r = UserAccount(full_name=s, phone=f"07{random.randint(10000000, 29999999)}"); db.add(r); db.flush()
            db.add(Tenancy(unit_id=u.id, resident_id=r.id, start_date=date(2026, 1, 1)))
            db.add_all([MeterReading(unit_id=u.id, reading_date=date(2026, 9, 30), value=100), MeterReading(unit_id=u.id, reading_date=date(2026, 10, 31), value=100 + random.randint(8, 20))])
        for blk in "AB":
            b = db.scalar(select(Building).where(Building.name == blk)); db.add(Unit(building_id=b.id, number=f"{blk}9", rent=19000, status="vacant"))
        db.add_all([ServiceProvider(name="FixIt Plumbers", category="Plumbing", phone="0711000111"), ServiceProvider(name="BrightSpark Electricals", category="Electrical", phone="0722000222"),
                    Rule(kind="overdue_bill", threshold=5), Rule(kind="stalled_request", threshold=48)])
        db.commit()

# ---------- Overview ----------
@app.get("/api/properties")
def properties(db=Depends(get_db)): return [row(p) for p in db.scalars(select(Property))]

@app.get("/api/overview")
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

# ---------- Properties, units, tenancies, meters ----------
@app.get("/api/units")
def units(pid: int, db=Depends(get_db)):
    out = []
    for u, b in db.execute(select(Unit, Building).join(Building).where(Building.property_id == pid).order_by(Building.name, Unit.id)):
        t = db.scalar(select(Tenancy).where(Tenancy.unit_id == u.id, Tenancy.end_date.is_(None)))
        out.append(row(u, building=b.name, tenancy_id=t.id if t else None, resident=db.get(UserAccount, t.resident_id).full_name if t else None))
    return out

class UnitIn(BaseModel): property_id: int; building: str; number: str; rent: int
@app.post("/api/units")
def add_unit(d: UnitIn, db=Depends(get_db)):
    b = db.scalar(select(Building).where(Building.property_id == d.property_id, Building.name == d.building))
    if not b: b = Building(property_id=d.property_id, name=d.building); db.add(b); db.flush()
    u = Unit(building_id=b.id, number=d.number, rent=d.rent); db.add(u); db.flush(); audit(db, "create unit", "unit", u.id); db.commit(); return row(u)

class TenancyIn(BaseModel): unit_id: int; full_name: str; phone: str
@app.post("/api/tenancies")
def assign(d: TenancyIn, db=Depends(get_db)):
    u = db.get(Unit, d.unit_id)
    if not u or u.status == "occupied": raise HTTPException(400, "Unit is not vacant")
    r = UserAccount(full_name=d.full_name, phone=d.phone); db.add(r); db.flush()
    t = Tenancy(unit_id=u.id, resident_id=r.id, start_date=date.today()); u.status = "occupied"; db.add(t); db.flush()
    audit(db, "assign resident", "tenancy", t.id); db.commit(); return row(t)

@app.post("/api/tenancies/{tid}/end")
def end(tid: int, db=Depends(get_db)):
    t = db.get(Tenancy, tid); t.end_date = date.today(); db.get(Unit, t.unit_id).status = "vacant"; audit(db, "end tenancy", "tenancy", tid); db.commit(); return row(t)

class MeterIn(BaseModel): unit_id: int; value: int
@app.post("/api/meter-readings")
def meter(d: MeterIn, db=Depends(get_db)):
    m = MeterReading(unit_id=d.unit_id, reading_date=date.today(), value=d.value); db.add(m); audit(db, "meter reading", "unit", d.unit_id); db.commit(); return row(m)

# ---------- Billing ----------
@app.get("/api/billing-configs")
def configs(pid: int, db=Depends(get_db)): return [row(c) for c in db.scalars(select(BillingConfig).where(BillingConfig.property_id == pid))]

class ConfigIn(BaseModel): property_id: int; charge_type: str; method: str; rate: int = 0; due_day: int = 5
@app.post("/api/billing-configs")
def add_config(d: ConfigIn, db=Depends(get_db)):
    if d.method not in ("rent", "fixed", "metered"): raise HTTPException(400, "method must be rent, fixed or metered")
    c = BillingConfig(**d.model_dump()); db.add(c); db.flush(); audit(db, "billing rule created", "billing_config", c.id); db.commit(); return row(c)

@app.delete("/api/billing-configs/{cid}")
def del_config(cid: int, db=Depends(get_db)):
    db.delete(db.get(BillingConfig, cid)); audit(db, "billing rule deleted", "billing_config", cid); db.commit(); return {"ok": True}

class GenIn(BaseModel): property_id: int; period: str | None = None  # "YYYY-MM"
@app.post("/api/bills/generate")
def generate(d: GenIn, db=Depends(get_db)):
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

@app.get("/api/bills")
def bills(pid: int, db=Depends(get_db)):
    return [row(b, **tinfo(db, b.tenancy_id)) for b in db.scalars(select(Bill).where(Bill.property_id == pid).order_by(Bill.id.desc()))]

# ---------- Payments (request -> confirmed transaction -> payment -> receipt) ----------
class StkIn(BaseModel): bill_id: int; phone: str | None = None
@app.post("/api/payments/stk")
def stk(d: StkIn, db=Depends(get_db)):
    b = db.get(Bill, d.bill_id)
    if not b or b.status == "paid": raise HTTPException(400, "Bill is already paid")
    phone = d.phone or tinfo(db, b.tenancy_id)["phone"]
    cid = daraja.stk_push(phone, b.amount, f"{b.charge_type}-{b.id}")
    r = PaymentRequest(bill_id=b.id, phone=phone, amount=b.amount, checkout_request_id=cid); db.add(r); db.flush()
    audit(db, "payment request sent", "payment_request", r.id); db.commit(); return row(r)  # bill stays pending

@app.post("/api/mpesa/callback")  # Daraja posts the outcome here
def callback(body: dict, db=Depends(get_db)):
    cb = body["Body"]["stkCallback"]
    r = db.scalar(select(PaymentRequest).where(PaymentRequest.checkout_request_id == cb["CheckoutRequestID"]))
    if not r: raise HTTPException(404, "Unknown checkout request")
    if r.status == "confirmed": return {"ResultCode": 0, "ResultDesc": "Already processed"}  # idempotent
    if cb["ResultCode"] != 0:
        r.status = "failed"; audit(db, "payment failed", "payment_request", r.id, "mpesa"); db.commit(); return {"ResultCode": 0, "ResultDesc": "Recorded"}
    meta = {i["Name"]: i.get("Value") for i in cb["CallbackMetadata"]["Item"]}
    if db.scalar(select(MpesaTransaction).where(MpesaTransaction.mpesa_receipt == meta["MpesaReceiptNumber"])): return {"ResultCode": 0, "ResultDesc": "Duplicate"}
    tx = MpesaTransaction(payment_request_id=r.id, mpesa_receipt=meta["MpesaReceiptNumber"], amount=int(meta["Amount"])); db.add(tx); db.flush()
    pay = Payment(bill_id=r.bill_id, transaction_id=tx.id, amount=tx.amount); db.add(pay); db.flush()
    db.add(Receipt(payment_id=pay.id, number="RCT-" + str(pay.id).zfill(6)))
    r.status = "confirmed"; db.get(Bill, r.bill_id).status = "paid"
    audit(db, "payment confirmed " + tx.mpesa_receipt, "payment", pay.id, "mpesa"); db.commit(); return {"ResultCode": 0, "ResultDesc": "Accepted"}

@app.post("/api/mock/daraja/{checkout_id}/{outcome}")  # simulator: outcome = success | fail
def simulate(checkout_id: str, outcome: str, db=Depends(get_db)):
    if not daraja.MOCK: raise HTTPException(400, "Simulator disabled when DARAJA_MOCK=0")
    r = db.scalar(select(PaymentRequest).where(PaymentRequest.checkout_request_id == checkout_id))
    cb = {"CheckoutRequestID": checkout_id, "ResultCode": 0 if outcome == "success" else 1032, "ResultDesc": "ok"}
    if outcome == "success":
        cb["CallbackMetadata"] = {"Item": [{"Name": "Amount", "Value": r.amount}, {"Name": "MpesaReceiptNumber", "Value": "".join(random.choices(string.ascii_uppercase + string.digits, k=10))}]}
    return callback({"Body": {"stkCallback": cb}}, db)

@app.get("/api/payments")
def payments(pid: int, db=Depends(get_db)):
    out = []
    for r in db.scalars(select(PaymentRequest).join(Bill).where(Bill.property_id == pid).order_by(PaymentRequest.id.desc())):
        b = db.get(Bill, r.bill_id); tx = db.scalar(select(MpesaTransaction).where(MpesaTransaction.payment_request_id == r.id))
        rc = db.scalar(select(Receipt).join(Payment).where(Payment.transaction_id == tx.id)) if tx else None
        out.append(row(r, charge=b.charge_type, period=b.period, mpesa_receipt=tx.mpesa_receipt if tx else None, receipt=rc.number if rc else None, **tinfo(db, b.tenancy_id)))
    return out

# ---------- Providers & maintenance ----------
@app.get("/api/providers")
def providers(db=Depends(get_db)): return [row(p) for p in db.scalars(select(ServiceProvider))]

class ProviderIn(BaseModel): name: str; category: str; phone: str
@app.post("/api/providers")
def add_provider(d: ProviderIn, db=Depends(get_db)):
    p = ServiceProvider(**d.model_dump()); db.add(p); db.flush(); audit(db, "provider added", "service_provider", p.id); db.commit(); return row(p)

@app.post("/api/providers/{id}/toggle")
def toggle_provider(id: int, db=Depends(get_db)):
    p = db.get(ServiceProvider, id); p.approved = not p.approved; audit(db, "provider approval changed", "service_provider", id); db.commit(); return row(p)

@app.get("/api/requests")
def requests(pid: int, db=Depends(get_db)):
    return [row(r, provider=(db.get(ServiceProvider, r.provider_id).name if r.provider_id else None), **tinfo(db, r.tenancy_id))
            for r in db.scalars(select(ServiceRequest).where(ServiceRequest.property_id == pid).order_by(ServiceRequest.id.desc()))]

class ReqIn(BaseModel): property_id: int; unit_id: int; category: str; title: str
@app.post("/api/requests")
def add_request(d: ReqIn, db=Depends(get_db)):
    t = db.scalar(select(Tenancy).where(Tenancy.unit_id == d.unit_id, Tenancy.end_date.is_(None)))
    if not t: raise HTTPException(400, "Unit has no active resident")
    r = ServiceRequest(property_id=d.property_id, tenancy_id=t.id, category=d.category, title=d.title); db.add(r); db.flush()
    audit(db, "request logged", "service_request", r.id); db.commit(); return row(r)

class ReqUpdate(BaseModel): provider_id: int | None = None; status: str | None = None; cost: int | None = None; hours: int | None = None; work_note: str | None = None
@app.patch("/api/requests/{rid}")
def update_request(rid: int, d: ReqUpdate, db=Depends(get_db)):
    r = db.get(ServiceRequest, rid)
    if d.provider_id:
        p = db.get(ServiceProvider, d.provider_id)
        if not p or not p.approved: raise HTTPException(400, "Provider is not approved")
        r.provider_id = p.id; r.status = "Assigned"
    for k in ("status", "cost", "hours", "work_note"):
        if getattr(d, k) is not None: setattr(r, k, getattr(d, k))
    r.updated_at = datetime.now(); audit(db, f"request now {r.status}", "service_request", rid); db.commit(); return row(r)

@app.post("/api/requests/{rid}/charge")  # turn a completed job's cost into a bill on the resident's account
def charge(rid: int, db=Depends(get_db)):
    r = db.get(ServiceRequest, rid)
    if r.cost <= 0: raise HTTPException(400, "Record a cost first")
    b = Bill(property_id=r.property_id, tenancy_id=r.tenancy_id, service_request_id=r.id, charge_type=f"Service: {r.category}", period=date.today().strftime("%Y-%m"),
             amount=r.cost, due_date=date.today() + timedelta(days=7)); db.add(b); db.flush(); audit(db, "service charge billed", "bill", b.id); db.commit(); return row(b)

# ---------- Reports, audit, automation ----------
@app.get("/api/reports")
def reports(pid: int, db=Depends(get_db)):
    grp = lambda e: [{"label": a, "value": int(b or 0)} for a, b in db.execute(e)]
    return {"collected": grp(select(Bill.charge_type, func.sum(Payment.amount)).join(Payment, Payment.bill_id == Bill.id).where(Bill.property_id == pid).group_by(Bill.charge_type)),
            "outstanding": grp(select(Bill.charge_type, func.sum(Bill.amount)).where(Bill.property_id == pid, Bill.status != "paid").group_by(Bill.charge_type)),
            "maintenance": grp(select(ServiceRequest.category, func.sum(ServiceRequest.cost)).where(ServiceRequest.property_id == pid).group_by(ServiceRequest.category)),
            "unresolved": db.scalar(select(func.count()).select_from(ServiceRequest).where(ServiceRequest.property_id == pid, ServiceRequest.status != "Completed"))}

@app.get("/api/audit")
def audit_log(db=Depends(get_db)): return [row(a) for a in db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(40))]

@app.get("/api/rules")
def rules(db=Depends(get_db)): return [row(r) for r in db.scalars(select(Rule).order_by(Rule.id))]

class RuleIn(BaseModel): threshold: int | None = None; enabled: bool | None = None
@app.patch("/api/rules/{rid}")
def edit_rule(rid: int, d: RuleIn, db=Depends(get_db)):
    r = db.get(Rule, rid)
    if d.threshold is not None: r.threshold = d.threshold
    if d.enabled is not None: r.enabled = d.enabled
    audit(db, "automation rule changed", "rule", rid); db.commit(); return row(r)

@app.post("/api/automation/run")  # call from a scheduler (cron) in production
def run_rules(db=Depends(get_db)):
    log = []
    for r in db.scalars(select(Rule).where(Rule.enabled)):
        if r.kind == "overdue_bill":
            for b in db.scalars(select(Bill).where(Bill.status == "pending", Bill.due_date < date.today() - timedelta(days=r.threshold))):
                b.status = "overdue"; t = db.get(Tenancy, b.tenancy_id)
                db.add(Notification(user_id=t.resident_id, type="reminder", message=f"{b.charge_type} {b.period} (KES {b.amount}) is overdue")); log.append(f"Bill {b.id} marked overdue, reminder sent")
        else:
            for s in db.scalars(select(ServiceRequest).where(ServiceRequest.status == "Assigned", ServiceRequest.updated_at < datetime.now() - timedelta(hours=r.threshold))):
                db.add(Notification(type="alert", message=f"Request #{s.id} '{s.title}' has had no update for {r.threshold}h")); log.append(f"Manager alerted: request {s.id} stalled")
    audit(db, f"automation ran ({len(log)} actions)", "rule", None, "system"); db.commit(); return {"actions": log}

@app.get("/api/notifications")
def notifications(db=Depends(get_db)): return [row(n) for n in db.scalars(select(Notification).order_by(Notification.id.desc()).limit(20))]

from resident_api import router as resident_router  # resident mobile API
app.include_router(resident_router)