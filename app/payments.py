"""Razorpay Standard Checkout: create an order, then verify the signature the checkout returns."""
import razorpay

from . import config

_client = None


def enabled():
    return bool(config.RAZORPAY_KEY_ID and config.RAZORPAY_KEY_SECRET)


def client():
    global _client
    if _client is None:
        _client = razorpay.Client(auth=(config.RAZORPAY_KEY_ID, config.RAZORPAY_KEY_SECRET))
    return _client


def create_order(order):
    rzp = client().order.create({
        "amount": order["amount_paise"],
        "currency": "INR",
        "receipt": order["id"],
        "notes": {"order_id": order["id"], "email": order["email"]},
    })
    return rzp["id"]


def verify_checkout(rzp_order_id, rzp_payment_id, signature):
    try:
        client().utility.verify_payment_signature({
            "razorpay_order_id": rzp_order_id,
            "razorpay_payment_id": rzp_payment_id,
            "razorpay_signature": signature,
        })
        return True
    except razorpay.errors.SignatureVerificationError:
        return False


def verify_webhook(body: str, signature: str):
    if not config.RAZORPAY_WEBHOOK_SECRET:
        return False
    try:
        client().utility.verify_webhook_signature(body, signature, config.RAZORPAY_WEBHOOK_SECRET)
        return True
    except razorpay.errors.SignatureVerificationError:
        return False
