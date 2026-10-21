"""Customer accounts: Google sign-in, and a signed cookie that remembers the verified email."""
import hashlib
import hmac
import json
import time
import urllib.parse
import urllib.request

from . import config

COOKIE = "rs_user"
MAX_AGE = 60 * 60 * 24 * 60  # 60 days


def enabled():
    return bool(config.GOOGLE_CLIENT_ID)


def _sig(value):
    return hmac.new(config.SECRET_KEY.encode(), value.encode(), hashlib.sha256).hexdigest()


def make_cookie(email, name=""):
    payload = json.dumps({"e": email.lower(), "n": name, "x": int(time.time()) + MAX_AGE}, separators=(",", ":"))
    return urllib.parse.quote(payload) + "." + _sig(payload)


def read_cookie(raw):
    """Returns {"email", "name"} for a valid, unexpired cookie, else None."""
    if not raw or "." not in raw:
        return None
    quoted, sig = raw.rsplit(".", 1)
    payload = urllib.parse.unquote(quoted)
    if not hmac.compare_digest(_sig(payload), sig):
        return None
    try:
        data = json.loads(payload)
    except ValueError:
        return None
    if data.get("x", 0) < time.time():
        return None
    return {"email": data["e"], "name": data.get("n", "")}


def verify_google(credential):
    """Checks a Google Identity Services ID token with Google and returns (email, name), or None."""
    url = "https://oauth2.googleapis.com/tokeninfo?id_token=" + urllib.parse.quote(credential)
    try:
        with urllib.request.urlopen(url, timeout=10) as res:
            info = json.loads(res.read())
    except Exception:
        return None
    if (info.get("aud") != config.GOOGLE_CLIENT_ID
            or info.get("iss") not in ("accounts.google.com", "https://accounts.google.com")
            or str(info.get("email_verified")).lower() != "true"
            or int(info.get("exp", 0)) < time.time()):
        return None
    return info["email"].lower(), info.get("name", "")
