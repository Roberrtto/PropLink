"""M-Pesa Express (STK push) client for Safaricom's Daraja API.

DARAJA_MOCK=1 (the development default) simulates everything: no request leaves your computer and no money moves.
With DARAJA_MOCK=0 each call uses the paying landlord's own credentials (a PaymentAccount row), so rent goes straight
to that landlord's Paybill or Till.
"""
import base64, logging, random, string, time
from datetime import datetime, timedelta, timezone
import httpx
import config

log = logging.getLogger("proplink.daraja")
MOCK = config.DARAJA_MOCK
_EAT = timezone(timedelta(hours=3))  # Kenya time, no daylight saving; Daraja timestamps use it
_tokens: dict = {}  # consumer key -> (access token, expiry)


class DarajaError(RuntimeError):
    pass


def _ready(account):
    if account is None or not account.ready:
        raise DarajaError("Online payments are not set up yet. The landlord needs to add the payment details.")


def _token(key: str, secret: str) -> str:
    hit = _tokens.get(key)
    if hit and hit[1] > time.time() + 30: return hit[0]
    try:
        r = httpx.get(f"{config.DARAJA_BASE}/oauth/v1/generate", params={"grant_type": "client_credentials"}, auth=(key, secret), timeout=15)
        r.raise_for_status()
        data = r.json(); token = data["access_token"]; ttl = int(data.get("expires_in", 3599))
    except (httpx.HTTPError, KeyError, ValueError) as e:
        raise DarajaError("Could not sign in to M-Pesa. Check the payment details in Payment settings.") from e
    _tokens[key] = (token, time.time() + ttl)
    return token


def _post(account, path: str, payload: dict):
    token = _token(account.consumer_key, account.consumer_secret)
    try:
        r = httpx.post(f"{config.DARAJA_BASE}{path}", json=payload, headers={"Authorization": f"Bearer {token}"}, timeout=20)
        return r.status_code, r.json()
    except (httpx.HTTPError, ValueError) as e:
        raise DarajaError("M-Pesa is not reachable right now. Please try again shortly.") from e


def _stamp(account):
    ts = datetime.now(_EAT).strftime("%Y%m%d%H%M%S")
    return ts, base64.b64encode(f"{account.shortcode}{account.passkey}{ts}".encode()).decode()


def stk_push(account, msisdn: str, amount: int, reference: str, description: str) -> str:
    """Ask Safaricom to show the payment prompt on msisdn's phone. Returns the CheckoutRequestID."""
    if MOCK:
        return "ws_CO_SIM" + "".join(random.choices(string.digits, k=14))
    _ready(account)
    ts, password = _stamp(account)
    payload = {
        "BusinessShortCode": account.shortcode, "Password": password, "Timestamp": ts,
        "TransactionType": "CustomerPayBillOnline" if account.tx_type == "paybill" else "CustomerBuyGoodsOnline",
        "Amount": int(amount), "PartyA": msisdn, "PartyB": account.party_b or account.shortcode, "PhoneNumber": msisdn,
        "CallBackURL": f"{config.PUBLIC_BASE_URL}/api/mpesa/callback/{config.MPESA_CALLBACK_TOKEN}",
        "AccountReference": reference[:12], "TransactionDesc": description[:13] or "Payment",
    }
    status, data = _post(account, "/mpesa/stkpush/v1/processrequest", payload)
    if status != 200 or str(data.get("ResponseCode")) != "0":
        log.warning("STK push rejected (%s): %s", status, data)
        raise DarajaError(data.get("errorMessage") or data.get("ResponseDescription") or "M-Pesa could not send the payment prompt")
    return data["CheckoutRequestID"]


def stk_query(account, checkout_id: str) -> dict:
    """Ask Safaricom what happened to a prompt. result_code 0 = paid, another number = failed or cancelled,
    None = Safaricom could not say yet (still processing)."""
    if MOCK:
        return {"result_code": 0}
    _ready(account)
    ts, password = _stamp(account)
    status, data = _post(account, "/mpesa/stkpushquery/v1/query",
                         {"BusinessShortCode": account.shortcode, "Password": password, "Timestamp": ts, "CheckoutRequestID": checkout_id})
    if "ResultCode" in data:
        try: return {"result_code": int(data["ResultCode"])}
        except (TypeError, ValueError): pass
    return {"result_code": None}