"""Admin commands.

  python manage.py gen-secrets          print new random secrets to paste into .env
  python manage.py create-admin         create a dashboard admin (asks for email, name and password)
  python manage.py reset-password EMAIL set a new password for a dashboard account and unlock it
  python manage.py run-automation       run the automation rules once (for a scheduled task)

In Docker:  docker compose exec backend python manage.py create-admin
"""
import base64, getpass, os, secrets, sys


def gen_secrets():
    print("# Paste these into .env. Keep them secret and backed up: losing FIELD_ENCRYPTION_KEY")
    print("# or BLIND_INDEX_KEY makes stored phone numbers and names unreadable.")
    print(f"JWT_SECRET={secrets.token_urlsafe(48)}")
    print(f"FIELD_ENCRYPTION_KEY={base64.urlsafe_b64encode(os.urandom(32)).decode()}")
    print(f"BLIND_INDEX_KEY={secrets.token_urlsafe(48)}")
    print(f"MPESA_CALLBACK_TOKEN={secrets.token_urlsafe(32)}")
    print(f"POSTGRES_PASSWORD={secrets.token_hex(24)}")


def ask_password():
    from security import password_problem
    while True:
        pw = getpass.getpass("Password: ")
        if err := password_problem(pw): print(err); continue
        if pw != getpass.getpass("Repeat password: "): print("Passwords don't match"); continue
        return pw


def create_admin():
    from sqlalchemy import select
    from models import Base, Session, StaffUser, engine
    from security import hash_password
    Base.metadata.create_all(engine)
    email = input("Email: ").strip().lower(); name = input("Full name: ").strip()
    if "@" not in email or not name: sys.exit("Email and name are required")
    with Session() as db:
        if db.scalar(select(StaffUser).where(StaffUser.email == email)): sys.exit("That email already has an account")
        db.add(StaffUser(email=email, full_name=name, role="admin", password_hash=hash_password(ask_password()))); db.commit()
    print(f"Admin {email} created. Sign in to the dashboard with this email and password.")


def reset_password(email):
    from sqlalchemy import select
    from models import Session, StaffUser
    from security import hash_password
    with Session() as db:
        s = db.scalar(select(StaffUser).where(StaffUser.email == email.strip().lower()))
        if not s: sys.exit("No account with that email")
        s.password_hash = hash_password(ask_password()); s.failed_logins = 0; s.locked_until = None; s.active = True; s.token_version += 1
        db.commit()
    print("Password updated; that account has been signed out everywhere.")


def run_automation():
    from models import Session
    from main import run_rules
    with Session() as db:
        db.info["actor"] = "scheduler"
        for line in run_rules(db)["actions"]: print(line)


if __name__ == "__main__":
    cmd, args = (sys.argv[1] if len(sys.argv) > 1 else ""), sys.argv[2:]
    if cmd == "gen-secrets": gen_secrets()
    elif cmd == "create-admin": create_admin()
    elif cmd == "reset-password" and args: reset_password(args[0])
    elif cmd == "run-automation": run_automation()
    else: print(__doc__)