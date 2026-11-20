"""Kenyan mobile numbers. Stored as 2547XXXXXXXX / 2541XXXXXXXX (the format M-Pesa and SMS gateways use)."""
import re


class InvalidPhone(ValueError):
    pass


def normalize(raw: str) -> str:
    """Accepts 0712 345 678, 712345678, +254712345678, 254712345678 (also 01XX numbers)."""
    d = re.sub(r"\D", "", raw or "")
    if d.startswith("254"): d = d[3:]
    elif d.startswith("0"): d = d[1:]
    if not re.fullmatch(r"[17]\d{8}", d):
        raise InvalidPhone("Enter a valid Kenyan mobile number, e.g. 0712 345 678")
    return "254" + d


def local(msisdn: str) -> str:
    """2547XXXXXXXX -> 07XXXXXXXX for display."""
    return "0" + msisdn[3:] if msisdn and msisdn.startswith("254") else msisdn


def international(msisdn: str) -> str:
    return "+" + msisdn