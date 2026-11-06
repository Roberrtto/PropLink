"""Daraja (M-Pesa Express) client. MOCK=1 (default) fakes the STK push; set MOCK=0 + keys for real use."""
import os, uuid, base64
from datetime import datetime
import httpx

MOCK = os.getenv("DARAJA_MOCK", "1") == "1"
BASE = os.getenv("DARAJA_BASE", "https://sandbox.safaricom.co.ke")

def stk_push(phone: str, amount: int, ref: str) -> str:
    """Returns the CheckoutRequestID. Outcome arrives later on /api/mpesa/callback."""
    if MOCK:
        return "ws_CO_" + uuid.uuid4().hex[:16]
    key, secret = os.environ["DARAJA_KEY"], os.environ["DARAJA_SECRET"]
    shortcode, passkey = os.environ["DARAJA_SHORTCODE"], os.environ["DARAJA_PASSKEY"]
    token = httpx.get(f"{BASE}/oauth/v1/generate?grant_type=client_credentials", auth=(key, secret)).json()["access_token"]
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    pwd = base64.b64encode(f"{shortcode}{passkey}{ts}".encode()).decode()
    msisdn = "254" + phone.lstrip("0+").removeprefix("254")
    r = httpx.post(f"{BASE}/mpesa/stkpush/v1/processrequest", headers={"Authorization": f"Bearer {token}"}, json={
        "BusinessShortCode": shortcode, "Password": pwd, "Timestamp": ts, "TransactionType": "CustomerPayBillOnline",
        "Amount": amount, "PartyA": msisdn, "PartyB": shortcode, "PhoneNumber": msisdn,
        "CallBackURL": os.environ["DARAJA_CALLBACK_URL"], "AccountReference": ref, "TransactionDesc": ref})
    r.raise_for_status()
    return r.json()["CheckoutRequestID"]
