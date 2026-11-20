"""Sends SMS (login codes). SMS_PROVIDER=console prints to the log; africastalking sends real messages."""
import logging
import httpx
import config
import phone

log = logging.getLogger("proplink.sms")


class SmsError(RuntimeError):
    pass


def send(msisdn: str, message: str) -> None:
    if config.SMS_PROVIDER == "console":
        log.warning("[SMS not sent: console mode] to %s: %s", phone.local(msisdn), message)
        return
    if config.SMS_PROVIDER != "africastalking":
        raise SmsError(f"Unknown SMS_PROVIDER {config.SMS_PROVIDER!r}")
    host = "api.sandbox.africastalking.com" if config.AT_USERNAME == "sandbox" else "api.africastalking.com"
    data = {"username": config.AT_USERNAME, "to": phone.international(msisdn), "message": message}
    if config.AT_SENDER_ID: data["from"] = config.AT_SENDER_ID
    try:
        r = httpx.post(f"https://{host}/version1/messaging", data=data, timeout=15,
                       headers={"apiKey": config.AT_API_KEY, "Accept": "application/json"})
        r.raise_for_status()
        recipients = r.json().get("SMSMessageData", {}).get("Recipients", [])
        if not recipients or recipients[0].get("status") != "Success":
            raise SmsError(f"SMS rejected: {recipients[0].get('status') if recipients else r.text[:200]}")
    except httpx.HTTPError as e:
        raise SmsError(f"SMS gateway error: {e}") from e