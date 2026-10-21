"""Order emails through Resend. Silently skipped when no API key is set."""
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
    send(
        order["email"],
        f"Your tailored resume is ready - {config.SITE_NAME}",
        f"""<p>Hi {order['customer_name']},</p>
<p>Your tailored resume is ready. Review it, make any edits and download the Word and PDF files here:</p>
<p><a href="{link}">{link}</a></p>
<p>You can edit freely and regenerate up to {config.MAX_REGENERATIONS} times within {config.EDIT_WINDOW_DAYS} days.
Keep this link private; anyone with it can open your resume.</p>
<p>Thank you,<br>{config.SITE_NAME}</p>""",
    )
