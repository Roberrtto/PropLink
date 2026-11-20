"""Database connection and tables. Personal data (names, phone numbers) is encrypted at rest."""
from datetime import date, datetime
from sqlalchemy import create_engine, String, Integer, Date, DateTime, ForeignKey, Boolean, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
import config
from crypto import EncryptedString

engine = create_engine(config.DATABASE_URL, pool_pre_ping=True)
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
class UserAccount(Base):  # a resident
    __tablename__ = "user_account"; id: Mapped[int] = pk()
    full_name: Mapped[str] = mapped_column(EncryptedString)
    phone: Mapped[str] = mapped_column(EncryptedString)  # 2547XXXXXXXX, encrypted
    phone_hash: Mapped[str] = mapped_column(String(64), index=True)  # blind index for lookups
    role: Mapped[str] = mapped_column(String, default="resident")
    token_version: Mapped[int] = mapped_column(Integer, default=0)  # bump to sign the resident out everywhere
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
class StaffUser(Base):  # managers and admins who use the dashboard
    __tablename__ = "staff_user"; id: Mapped[int] = pk()
    email: Mapped[str] = mapped_column(String(254), unique=True)
    full_name: Mapped[str] = mapped_column(String(100))
    password_hash: Mapped[str] = mapped_column(String)
    role: Mapped[str] = mapped_column(String, default="manager")  # admin | manager
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    token_version: Mapped[int] = mapped_column(Integer, default=0)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_login: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
class OtpCode(Base):  # one-time login codes; only a keyed hash of the code is stored
    __tablename__ = "otp_code"; id: Mapped[int] = pk()
    phone_hash: Mapped[str] = mapped_column(String(64), index=True)
    code_hash: Mapped[str] = mapped_column(String(64))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
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
    phone: Mapped[str] = mapped_column(EncryptedString); amount: Mapped[int] = mapped_column(Integer)
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
    category: Mapped[str] = mapped_column(String); phone: Mapped[str] = mapped_column(EncryptedString); approved: Mapped[bool] = mapped_column(Boolean, default=True)
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


HIDDEN = {"password_hash", "phone_hash", "token_version", "code_hash", "failed_logins", "locked_until"}


def row(o, **extra):
    """A record as JSON, never including password hashes, lookup hashes or token versions."""
    d = {c.name: (v.isoformat() if isinstance(v := getattr(o, c.name), (date, datetime)) else v)
         for c in o.__table__.columns if c.name not in HIDDEN}
    return d | extra


def audit(db, action, entity, eid=None, actor=None):
    """actor defaults to whoever is signed in on this request (set by the auth dependencies)."""
    db.add(AuditLog(actor=actor or db.info.get("actor", "system"), action=action, entity=entity, entity_id=eid))