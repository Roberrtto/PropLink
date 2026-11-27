"""Database connection and tables. Personal data (names, IDs, phone numbers) is encrypted at rest.

Who owns what:
  organization (a landlord's company)
    ├─ staff_user      landlords and managers; every staff account belongs to one organization
    ├─ payment_account the landlord's own M-Pesa Paybill/Till details (encrypted)
    ├─ user_account    residents of that organization
    ├─ service_provider
    └─ property → building → unit → tenancy → bills, payments, service requests
  property_manager     which properties each manager may see (landlords see all of their own)
"""
from datetime import date, datetime
from sqlalchemy import create_engine, String, Integer, Date, DateTime, ForeignKey, Boolean, Text, UniqueConstraint
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


class Organization(Base):  # a landlord or property company; the boundary between customers
    __tablename__ = "organization"; id: Mapped[int] = pk()
    name: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class PaymentAccount(Base):  # where this landlord's rent money goes; secrets are encrypted
    __tablename__ = "payment_account"; id: Mapped[int] = pk()
    org_id: Mapped[int] = mapped_column(ForeignKey("organization.id"), unique=True)
    tx_type: Mapped[str] = mapped_column(String, default="paybill")  # paybill | till
    shortcode: Mapped[str] = mapped_column(String, default="")  # business shortcode (for a till: its store / head-office number)
    party_b: Mapped[str] = mapped_column(String, default="")  # the till number (tills only); blank = same as shortcode
    consumer_key: Mapped[str | None] = mapped_column(EncryptedString, nullable=True)
    consumer_secret: Mapped[str | None] = mapped_column(EncryptedString, nullable=True)
    passkey: Mapped[str | None] = mapped_column(EncryptedString, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    @property
    def ready(self) -> bool:
        return bool(self.shortcode and self.consumer_key and self.consumer_secret and self.passkey)


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
    __tablename__ = "user_account"
    __table_args__ = (UniqueConstraint("org_id", "id_hash"),)
    id: Mapped[int] = pk()
    org_id: Mapped[int] = fk("organization.id")
    full_name: Mapped[str] = mapped_column(EncryptedString)
    date_of_birth: Mapped[str] = mapped_column(EncryptedString)  # ISO date, encrypted
    id_type: Mapped[str] = mapped_column(String, default="national_id")  # national_id | passport
    id_number: Mapped[str] = mapped_column(EncryptedString)
    id_hash: Mapped[str] = mapped_column(String(64), index=True)  # blind index for lookups
    phone: Mapped[str] = mapped_column(EncryptedString)  # 2547XXXXXXXX, used for M-Pesa
    phone_hash: Mapped[str] = mapped_column(String(64), index=True)
    email: Mapped[str | None] = mapped_column(EncryptedString, nullable=True)
    guardian_name: Mapped[str | None] = mapped_column(EncryptedString, nullable=True)
    guardian_phone: Mapped[str | None] = mapped_column(EncryptedString, nullable=True)
    password_hash: Mapped[str | None] = mapped_column(String, nullable=True)  # None until the resident activates
    role: Mapped[str] = mapped_column(String, default="resident")
    token_version: Mapped[int] = mapped_column(Integer, default=0)  # bump to sign the resident out everywhere
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class StaffUser(Base):  # landlords and managers who use the dashboard
    __tablename__ = "staff_user"; id: Mapped[int] = pk()
    org_id: Mapped[int] = fk("organization.id")
    email: Mapped[str] = mapped_column(String(254), unique=True)
    full_name: Mapped[str] = mapped_column(String(100))
    password_hash: Mapped[str] = mapped_column(String)
    role: Mapped[str] = mapped_column(String, default="manager")  # landlord | manager
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    token_version: Mapped[int] = mapped_column(Integer, default=0)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_login: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class PropertyManager(Base):  # which properties a manager may see
    __tablename__ = "property_manager"
    __table_args__ = (UniqueConstraint("property_id", "staff_id"),)
    id: Mapped[int] = pk(); property_id: Mapped[int] = fk("property.id"); staff_id: Mapped[int] = fk("staff_user.id")


class OtpCode(Base):  # one-time activation codes issued by a manager; only a keyed hash of the code is stored
    __tablename__ = "otp_code"; id: Mapped[int] = pk()
    user_id: Mapped[int] = mapped_column(ForeignKey("user_account.id"), index=True)
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


class ServiceProvider(Base):  # each landlord keeps their own list of providers
    __tablename__ = "service_provider"; id: Mapped[int] = pk(); org_id: Mapped[int] = fk("organization.id"); name: Mapped[str] = mapped_column(String)
    category: Mapped[str] = mapped_column(String); phone: Mapped[str] = mapped_column(EncryptedString); approved: Mapped[bool] = mapped_column(Boolean, default=True)


class ServiceRequest(Base):  # status: Submitted | Assigned | In Progress | Completed
    __tablename__ = "service_request"; id: Mapped[int] = pk(); property_id: Mapped[int] = fk("property.id"); tenancy_id: Mapped[int] = fk("tenancy.id")
    provider_id: Mapped[int | None] = fk("service_provider.id", True); category: Mapped[str] = mapped_column(String)
    title: Mapped[str] = mapped_column(String); status: Mapped[str] = mapped_column(String, default="Submitted")
    cost: Mapped[int] = mapped_column(Integer, default=0); hours: Mapped[int] = mapped_column(Integer, default=0)
    work_note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now); updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class Rule(Base):  # kind: overdue_bill (days) | stalled_request (hours); each organization has its own
    __tablename__ = "rule"; id: Mapped[int] = pk(); org_id: Mapped[int] = fk("organization.id")
    kind: Mapped[str] = mapped_column(String); threshold: Mapped[int] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Notification(Base):  # user_id set = for a resident; property_id set = an alert for that property's staff
    __tablename__ = "notification"; id: Mapped[int] = pk(); user_id: Mapped[int | None] = fk("user_account.id", True)
    property_id: Mapped[int | None] = fk("property.id", True)
    type: Mapped[str] = mapped_column(String); message: Mapped[str] = mapped_column(String)
    read: Mapped[bool] = mapped_column(Boolean, default=False); created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class AuditLog(Base):  # a standalone history: it names records instead of linking to them, so it outlives them
    __tablename__ = "audit_log"; id: Mapped[int] = pk(); org_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    actor: Mapped[str] = mapped_column(String)  # who, as text: an email, "resident #3" or "mpesa"
    actor_id: Mapped[int | None] = fk("staff_user.id", True)  # the staff account, when a staff member did it
    action: Mapped[str] = mapped_column(String)
    entity: Mapped[str] = mapped_column(String); entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)  # what changed, in words (never secrets or full ID numbers)
    at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


def new_rules(org_id):
    """The default automation rules every new organization starts with."""
    return [Rule(org_id=org_id, kind="overdue_bill", threshold=5), Rule(org_id=org_id, kind="stalled_request", threshold=48)]


HIDDEN = {"password_hash", "phone_hash", "id_hash", "token_version", "code_hash", "failed_logins", "locked_until",
          "consumer_key", "consumer_secret", "passkey"}


def row(o, **extra):
    """A record as JSON, never including password hashes, lookup hashes, token versions or payment secrets."""
    d = {c.name: (v.isoformat() if isinstance(v := getattr(o, c.name), (date, datetime)) else v)
         for c in o.__table__.columns if c.name not in HIDDEN}
    return d | extra


def audit(db, action, entity, eid=None, actor=None, org=None, actor_id=None, details=None):
    """Record who did what. actor, organization and staff id default to whoever is signed in on this request
    (set by the auth dependencies). details says what changed; keep secrets and full ID numbers out of it."""
    if actor_id is None and not actor: actor_id = db.info.get("actor_id")
    db.add(AuditLog(org_id=org if org is not None else db.info.get("org"), actor=actor or db.info.get("actor", "system"),
                    actor_id=actor_id, action=action, entity=entity, entity_id=eid, details=details))