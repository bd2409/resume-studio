"""Order emails through Resend. Silently skipped when no API key is set."""
import html
import json
import logging
import urllib.error
import urllib.request

from . import config

log = logging.getLogger(__name__)


def status():
    """Why emails may not be going out, in plain words. None when everything looks set up."""
    if not config.RESEND_API_KEY:
        return "RESEND_API_KEY is not set in Render, so no emails are sent (not to customers, not to you)."
    if "example.com" in config.EMAIL_FROM:
        return "EMAIL_FROM is not set in Render. It must use a domain verified in Resend, e.g. Bhargab Das <hello@bhargabdas.in>."
    return None


def _log(to, subject, result):
    try:
        from . import db
        db.log_email(to, subject, result)
    except Exception:
        log.exception("Could not log email")


def send(to, subject, html):
    if not config.RESEND_API_KEY:
        log.info("Email skipped (no RESEND_API_KEY): %s -> %s", subject, to)
        _log(to, subject, "not sent: RESEND_API_KEY missing")
        return False
    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=json.dumps({"from": config.EMAIL_FROM, "to": [to], "subject": subject, "html": html}).encode(),
        headers={"Authorization": f"Bearer {config.RESEND_API_KEY}", "Content-Type": "application/json",
                 "User-Agent": "resume-studio/1.0"},
    )
    try:
        urllib.request.urlopen(req, timeout=20).read()
        _log(to, subject, "sent")
        return True
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:250]
        log.error("Email to %s failed: %s %s", to, e.code, detail)
        _log(to, subject, f"failed: {e.code} {detail}")
    except Exception as e:
        log.exception("Email to %s failed", to)
        _log(to, subject, f"failed: {e}")
    return False


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
