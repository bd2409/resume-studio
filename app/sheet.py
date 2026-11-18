"""Optional: append each lead, order and download as a row in Bhargab's Google Sheet.

Set SHEET_WEBHOOK_URL to a Google Apps Script web app URL (see docs/google-sheet-leads.md).
Rows are sent in the background so a slow Google never slows the site down.
"""
import json
import logging
import threading
import urllib.request
from datetime import datetime, timedelta, timezone

from . import config

log = logging.getLogger(__name__)
IST = timezone(timedelta(hours=5, minutes=30))


def _post(row):
    try:
        req = urllib.request.Request(config.SHEET_WEBHOOK_URL, data=json.dumps(row).encode(),
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=20).read()
    except Exception:
        log.exception("Could not add row to Google Sheet")


def append(event, name="", email="", phone="", what="", price="", source="", link=""):
    if not config.SHEET_WEBHOOK_URL:
        return
    row = {"time": datetime.now(IST).strftime("%Y-%m-%d %H:%M"), "event": event, "name": name, "email": email,
           "phone": phone, "what": what, "price": price, "source": source, "link": link}
    threading.Thread(target=_post, args=(row,), daemon=True).start()
