"""Cashfree Payment Gateway: create an order, send the customer to Cashfree checkout,
then confirm payment by fetching the order from Cashfree (never by trusting the browser)."""
import base64
import hashlib
import hmac
import json
import logging
import re
import time
import urllib.error
import urllib.request

from . import config

log = logging.getLogger(__name__)


def enabled():
    return bool(config.CASHFREE_APP_ID and config.CASHFREE_SECRET_KEY)


def mode():
    return "sandbox" if config.CASHFREE_ENV == "sandbox" else "production"


def _base():
    return "https://sandbox.cashfree.com/pg" if mode() == "sandbox" else "https://api.cashfree.com/pg"


def _request(method, path, body=None):
    req = urllib.request.Request(
        _base() + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "x-client-id": config.CASHFREE_APP_ID,
            "x-client-secret": config.CASHFREE_SECRET_KEY,
            "x-api-version": config.CASHFREE_API_VERSION,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as res:
            return json.loads(res.read() or b"null")
    except urllib.error.HTTPError as e:
        log.error("Cashfree %s %s failed: %s %s", method, path, e.code, e.read()[:500])
        raise


def _phone(raw):
    digits = re.sub(r"\D", "", raw or "")
    return digits[-10:] if len(digits) >= 10 else "9999999999"


def create_order(order):
    """Creates a Cashfree order and returns (cashfree_order_id, payment_session_id)."""
    cf_order_id = f"rs_{order['id']}_{int(time.time())}"[:45]
    res = _request("POST", "/orders", {
        "order_id": cf_order_id,
        "order_amount": round(order["amount_paise"] / 100, 2),
        "order_currency": "INR",
        "customer_details": {
            "customer_id": re.sub(r"[^A-Za-z0-9]", "", order["id"])[:50] or "customer",
            "customer_name": order["customer_name"][:100],
            "customer_email": order["email"],
            "customer_phone": _phone(order["phone"]),
        },
        "order_meta": {
            "return_url": f"{config.SITE_URL}/order/{order['token']}/payment-return",
            "notify_url": f"{config.SITE_URL}/webhooks/cashfree",
        },
        "order_note": config.PRODUCTS.get(order.get("product") or "resume", {}).get("label", "Resume")[:200],
    })
    return res["order_id"], res["payment_session_id"]


def session_for(order):
    """Reuses the order's Cashfree order while it can still be paid, otherwise creates a new one."""
    if order["rzp_order_id"]:
        try:
            cf = _request("GET", f"/orders/{order['rzp_order_id']}")
            if cf.get("order_status") == "ACTIVE" and cf.get("payment_session_id"):
                return cf["order_id"], cf["payment_session_id"]
        except Exception:
            log.warning("Could not reuse Cashfree order %s", order["rzp_order_id"])
    return create_order(order)


def confirmed_payment(order):
    """Returns the Cashfree payment id if the order is fully paid, otherwise None."""
    if not order["rzp_order_id"]:
        return None
    cf = _request("GET", f"/orders/{order['rzp_order_id']}")
    if cf.get("order_status") != "PAID" or round(float(cf.get("order_amount", 0)) * 100) != order["amount_paise"]:
        return None
    payment_id = cf.get("cf_order_id") or order["rzp_order_id"]
    try:
        for p in _request("GET", f"/orders/{order['rzp_order_id']}/payments") or []:
            if p.get("payment_status") == "SUCCESS":
                payment_id = p.get("cf_payment_id") or payment_id
                break
    except Exception:
        pass
    return str(payment_id)


def verify_webhook(raw: bytes, timestamp: str, signature: str):
    if not (config.CASHFREE_SECRET_KEY and timestamp and signature):
        return False
    digest = hmac.new(config.CASHFREE_SECRET_KEY.encode(), timestamp.encode() + raw, hashlib.sha256).digest()
    return hmac.compare_digest(base64.b64encode(digest).decode(), signature)
