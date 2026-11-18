"""Emails through your own mailbox (SMTP) or Resend. Skipped, and logged, when neither is set up."""
import html
import json
import logging
import smtplib
import urllib.error
from email.message import EmailMessage
import urllib.request

from . import config

log = logging.getLogger(__name__)


def _use_smtp():
    return bool(config.SMTP_USER and config.SMTP_PASSWORD)


def method():
    """Which route emails take right now (no secret values)."""
    if _use_smtp():
        return f"own mailbox (SMTP {config.SMTP_HOST}:{config.SMTP_PORT})"
    if config.RESEND_API_KEY:
        return "Resend (SMTP_USER / SMTP_PASSWORD not set)"
    return "none"


def recent_results(limit=5):
    """The last few send results with addresses hidden, so problems show up on /healthz."""
    import re
    try:
        from . import db
        rows = db.recent_emails(limit)
    except Exception:
        return []
    hide = lambda t: re.sub(r"[\w.+-]+@[\w.-]+", "<email>", t or "")
    return [f"{r['at'][:16]} {hide(r['subject'])[:50]}: {hide(r['status'])[:160]}" for r in rows]


def status():
    """Why emails may not be going out, in plain words. None when everything looks set up."""
    if _use_smtp():
        return None
    if not config.RESEND_API_KEY:
        return ("No email account is connected, so no emails are sent (not to customers, not to you). In Render, set "
                "SMTP_USER (e.g. hello@bhargabdas.in) and SMTP_PASSWORD (that mailbox's password).")
    if "example.com" in config.EMAIL_FROM:
        return "EMAIL_FROM is not set in Render. It must use a domain verified in Resend, e.g. Bhargab Das <hello@bhargabdas.in>."
    return None


def _log(to, subject, result):
    try:
        from . import db
        db.log_email(to, subject, result)
    except Exception:
        log.exception("Could not log email")


def _send_smtp(to_list, subject, body):
    msg = EmailMessage()
    msg["From"] = config.EMAIL_FROM
    msg["To"] = ", ".join(to_list)
    msg["Subject"] = subject
    msg.set_content("Please view this email in an email app that shows HTML.")
    msg.add_alternative(body, subtype="html")
    try:
        if config.SMTP_PORT == 465:
            server = smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT, timeout=20)
        else:
            server = smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=20)
            server.ehlo()
            if server.has_extn("starttls"):
                server.starttls()
                server.ehlo()
        with server:
            if server.has_extn("auth"):
                server.login(config.SMTP_USER, config.SMTP_PASSWORD)
            server.send_message(msg)
        _log(msg["To"], subject, "sent")
        return True
    except Exception as e:
        log.exception("SMTP email to %s failed", msg["To"])
        _log(msg["To"], subject, f"failed: {type(e).__name__}: {str(e)[:200]}")
        return False


def owner_addresses():
    """OWNER_EMAIL can hold several addresses separated by commas, e.g. hello@bhargabdas.in,me@gmail.com."""
    return [a.strip() for a in (config.OWNER_EMAIL or "").split(",") if "@" in a and "example.com" not in a]


def send(to, subject, html):
    """`to` is one address or a list of addresses."""
    to_list = [to] if isinstance(to, str) else list(to)
    to = ", ".join(to_list)
    if _use_smtp():
        return _send_smtp(to_list, subject, html)
    if not config.RESEND_API_KEY:
        log.info("Email skipped (no RESEND_API_KEY): %s -> %s", subject, to)
        _log(to, subject, "not sent: RESEND_API_KEY missing")
        return False
    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=json.dumps({"from": config.EMAIL_FROM, "to": to_list, "subject": subject, "html": html}).encode(),
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
    to = owner_addresses()
    if not to:
        log.info("Owner alert (no OWNER_EMAIL): %s", subject)
        return
    body = "".join(f"<p>{html.escape(str(line))}</p>" for line in lines)
    send(to, subject, body)
