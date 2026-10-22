"""Bhargab's LinkedIn posts shown on the site.

LinkedIn's API doesn't let ordinary sites read a member's posts, so we embed
them instead. Short lnkd.in links are resolved on the server (once, then
cached) to the post's id, which gives the official embed URL.
"""
import json
import logging
import re
import threading
import time
import urllib.request

from . import config

log = logging.getLogger(__name__)

# Add new post links here (the "Copy link to post" URL from LinkedIn).
POSTS = [
    "https://lnkd.in/p/gyJTxuzA",
    "https://lnkd.in/p/gqQ2yMqe",
    "https://lnkd.in/p/gx6PPdyA",
    "https://lnkd.in/p/gdKXeE8K",
    "https://lnkd.in/p/gUFdQZVc",
    "https://lnkd.in/p/gCK-2S_H",
    "https://lnkd.in/p/g2sGtZxC",
    "https://lnkd.in/p/gJ2VTvjq",
]

CACHE = config.DATA_DIR / "linkedin.json"
URN = re.compile(r"urn(?::|%3A)li(?::|%3A)(activity|share|ugcPost)(?::|%3A)(\d{15,25})")
ACTIVITY = re.compile(r"activity[-:](\d{15,25})")
_lock = threading.Lock()
_cache = {}


def _load():
    global _cache
    try:
        _cache = json.loads(CACHE.read_text())
    except Exception:
        _cache = {}


def _save():
    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(_cache))
    except Exception:
        log.exception("Could not save LinkedIn cache")


def _find_urn(text):
    m = URN.search(text)
    if m:
        return f"urn:li:{m.group(1)}:{m.group(2)}"
    m = ACTIVITY.search(text)
    if m:
        return f"urn:li:activity:{m.group(1)}"
    return None


def resolve(url):
    """Follow the short link and return (full_url, urn) or (None, None)."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; bhargabdas.in)"})
    with urllib.request.urlopen(req, timeout=15) as r:
        final = r.geturl()
        body = r.read(400_000).decode("utf-8", "ignore")
    urn = _find_urn(final) or _find_urn(body)
    if not urn:
        # lnkd.in sometimes shows an interstitial page with the target link in it.
        m = re.search(r'https://www\.linkedin\.com/(?:posts|feed/update)/[^"\'<\s]+', body)
        if m:
            final = m.group(0).replace("&amp;", "&")
            urn = _find_urn(final)
    return (final if urn else None), urn


def refresh():
    for url in POSTS:
        if _cache.get(url, {}).get("urn"):
            continue
        try:
            full, urn = resolve(url)
            if urn:
                with _lock:
                    _cache[url] = {"urn": urn, "url": full}
                    _save()
        except Exception as e:
            log.warning("LinkedIn link %s not resolved: %s", url, e)


def _loop():
    for _ in range(24):
        refresh()
        if all(_cache.get(u, {}).get("urn") for u in POSTS):
            return
        time.sleep(3600)


def start():
    _load()
    threading.Thread(target=_loop, daemon=True).start()


def posts(limit=None):
    out = []
    for url in POSTS[:limit] if limit else POSTS:
        hit = _cache.get(url) or {}
        urn = hit.get("urn")
        out.append({
            "link": hit.get("url") or url,
            "embed": f"https://www.linkedin.com/embed/feed/update/{urn}?collapsed=1" if urn else None,
        })
    return out
