"""Order emails through Resend. Silently skipped when no API key is set."""
import html
import json
import logging
import urllib.request

from . import config

log = logging.getLogger(__name__)


def send(to, subject, html):
    if not config.RESEND_API_KEY:
        log.info("Email skipped (no RESEND_API_KEY): %s -> %s", subject, to)
        return
    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=json.dumps({"from": config.EMAIL_FROM, "to": [to], "subject": subject, "html": html}).encode(),
        headers={"Authorization": f"Bearer {config.RESEND_API_KEY}", "Content-Type": "application/json"},
    )
    try:
        urllib.request.urlopen(req, timeout=20).read()
    except Exception:
        log.exception("Email to %s failed", to)


def order_ready(order):
    link = f"{config.SITE_URL}/order/{order['token']}"
    label = config.PRODUCTS.get(order.get("product") or "resume", config.PRODUCTS["resume"])["label"]
    send(
        order["email"],
        f"Your {label.lower()} is ready - {config.SITE_NAME}",
        f"""<p>Hi {order['customer_name']},</p>
<p>Your {label.lower()} is ready. Open it, make any edits and download your files here:</p>
<p><a href="{link}">{link}</a></p>
<p>You can edit freely and regenerate up to {config.MAX_REGENERATIONS} times within {config.EDIT_WINDOW_DAYS} days.
Keep this link private; anyone with it can open your order.</p>
<p>Thank you,<br>{config.SITE_NAME}</p>""",
    )


def booking_confirmed(order):
    link = f"{config.SITE_URL}/order/{order['token']}"
    label = config.PRODUCTS[order["product"]]["label"]
    booking = (f'<p>Pick a time that suits you here: <a href="{config.CALL_BOOKING_URL}">{config.CALL_BOOKING_URL}</a></p>'
               if config.CALL_BOOKING_URL else
               "<p>I'll email you within one working day to fix a time that suits you.</p>")
    send(
        order["email"],
        f"Booking confirmed: {label} - {config.SITE_NAME}",
        f"""<p>Hi {order['customer_name']},</p>
<p>Thank you for booking the {label.lower()}. Your payment is confirmed.</p>
{booking}
<p>Your booking details: <a href="{link}">{link}</a></p>
<p>Thank you,<br>{config.OWNER_NAME}</p>""",
    )


def owner_alert(subject, lines):
    """A short note to the site owner about work that needs them (bookings, premium reviews, enquiries)."""
    if not config.OWNER_EMAIL or config.OWNER_EMAIL == "hello@example.com":
        log.info("Owner alert (no OWNER_EMAIL): %s", subject)
        return
    body = "".join(f"<p>{html.escape(str(line))}</p>" for line in lines)
    send(config.OWNER_EMAIL, subject, body)
