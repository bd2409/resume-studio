"""Settings read from environment variables (see .env.example)."""
import os
from pathlib import Path


def _bool(name, default=False):
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


SITE_NAME = os.getenv("SITE_NAME", "Resume Studio")
SITE_URL = os.getenv("SITE_URL", "http://localhost:8000").rstrip("/")
# Optional HTML-tag verification codes for Google Search Console and Bing Webmaster Tools
GOOGLE_SITE_VERIFICATION = os.getenv("GOOGLE_SITE_VERIFICATION", "")
BING_SITE_VERIFICATION = os.getenv("BING_SITE_VERIFICATION", "")
OWNER_NAME = os.getenv("OWNER_NAME", "Bhargab")
CONTACT_EMAIL = os.getenv("CONTACT_EMAIL", "hello@example.com")
CONTACT_PHONE = os.getenv("CONTACT_PHONE", "")
BUSINESS_ADDRESS = os.getenv("BUSINESS_ADDRESS", "India")

PRICE_RUPEES = int(os.getenv("PRICE_RUPEES", "500"))
MAX_RESUMES = 6
MAX_FILE_MB = 10
MAX_REGENERATIONS = int(os.getenv("MAX_REGENERATIONS", "2"))
EDIT_WINDOW_DAYS = int(os.getenv("EDIT_WINDOW_DAYS", "7"))
RETENTION_DAYS = int(os.getenv("RETENTION_DAYS", "30"))

DATA_DIR = Path(os.getenv("DATA_DIR", "./data")).resolve()
DB_PATH = DATA_DIR / "app.db"
FILES_DIR = DATA_DIR / "orders"

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
AI_MODEL = os.getenv("AI_MODEL", "claude-opus-5-5")
# "mock" skips the AI and returns sample content, for local testing only.
AI_MODE = os.getenv("AI_MODE", "live" if ANTHROPIC_API_KEY else "mock").strip().lower()

CASHFREE_APP_ID = os.getenv("CASHFREE_APP_ID", "").strip()
CASHFREE_SECRET_KEY = os.getenv("CASHFREE_SECRET_KEY", "").strip()
# "production" or "sandbox" (test keys)
CASHFREE_ENV = os.getenv("CASHFREE_ENV", "production").strip().lower()
CASHFREE_API_VERSION = os.getenv("CASHFREE_API_VERSION", "2025-01-01")
# Lets you skip payment locally when Cashfree keys are not set. Never enable in production.
DEV_SKIP_PAYMENT = _bool("DEV_SKIP_PAYMENT", False)

RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", f"{SITE_NAME} <no-reply@example.com>")

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")

FILES_DIR.mkdir(parents=True, exist_ok=True)

# Google sign-in (customer accounts). Create an OAuth "Web application" client ID in Google Cloud Console.
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
# Signs login cookies. Set a long random value in production so logins survive restarts.
SECRET_KEY = os.getenv("SECRET_KEY", "") or os.getenv("ADMIN_PASSWORD", "") or __import__("secrets").token_hex(32)

# What customers can buy. "resume" and "linkedin" say which deliverables an order produces, "pack" names an
# AI-written pack (see ai.PACKS), "service" marks work Bhargab does personally (no AI), and "human" adds his review.
PRICE_LINKEDIN = int(os.getenv("PRICE_LINKEDIN", "799"))
PRICE_BUNDLE = int(os.getenv("PRICE_BUNDLE", "1099"))
PRICE_VERSION = int(os.getenv("PRICE_VERSION", "199"))
PRICE_INTERVIEW = int(os.getenv("PRICE_INTERVIEW", "499"))
PRICE_OUTREACH = int(os.getenv("PRICE_OUTREACH", "399"))
PRICE_SALARY = int(os.getenv("PRICE_SALARY", "299"))
PRICE_CONTENT = int(os.getenv("PRICE_CONTENT", "999"))
PRICE_PREMIUM = int(os.getenv("PRICE_PREMIUM", "2999"))
PRICE_CALL = int(os.getenv("PRICE_CALL", "1999"))
PRICE_AUDIT = int(os.getenv("PRICE_AUDIT", "7999"))
PRICE_CLAUDE = int(os.getenv("PRICE_CLAUDE", "2499"))
# Free AI resume checks per day (the lead magnet), to cap AI spend.
FREE_CHECKS_PER_DAY = int(os.getenv("FREE_CHECKS_PER_DAY", "40"))

# Optional scheduling link (Calendly, Google Calendar booking page, ...) shown after a call is paid for.
CALL_BOOKING_URL = os.getenv("CALL_BOOKING_URL", "")
# Where new bookings, premium orders and enquiries are sent.
OWNER_EMAIL = os.getenv("OWNER_EMAIL", CONTACT_EMAIL)


def _product(label, price, icon, blurb, **flags):
    base = {"resume": False, "linkedin": False, "pack": None, "service": False, "human": False}
    return {**base, "label": label, "price": price, "icon": icon, "blurb": blurb, **flags}


PRODUCTS = {
    "resume": _product("Resume + cover letter", PRICE_RUPEES, "📄",
                       "Tailored to the job, with a job-match score.", resume=True),
    "linkedin": _product("LinkedIn profile makeover", PRICE_LINKEDIN, "💼",
                         "Headline, About, experience and skills rewritten so recruiters find you.", linkedin=True),
    "bundle": _product("Resume + cover letter + LinkedIn makeover", PRICE_BUNDLE, "⭐",
                       "One consistent story everywhere recruiters look.", resume=True, linkedin=True),
    "version": _product("Extra job version (resume + cover letter)", PRICE_VERSION, "➕",
                        "A new tailored resume and cover letter for another job.", resume=True),
    "premium": _product("Done-with-you premium resume", PRICE_PREMIUM, "🤝",
                        "Resume, cover letter and LinkedIn makeover, personally reviewed by Bhargab, plus a 15-minute call.",
                        resume=True, linkedin=True, human=True),
    "interview": _product("Interview prep pack", PRICE_INTERVIEW, "🎯",
                          "Likely questions with model answers from your real experience, your intro pitch and questions to ask.",
                          pack="interview"),
    "outreach": _product("Cold outreach pack", PRICE_OUTREACH, "✉️",
                         "Emails and LinkedIn messages to hiring managers, recruiters and referrals, ready to send.",
                         pack="outreach"),
    "salary": _product("Salary negotiation script", PRICE_SALARY, "💰",
                       "What to say on the call and by email to raise your offer, with replies to common pushbacks.",
                       pack="salary"),
    "content": _product("LinkedIn content kit (30 days)", PRICE_CONTENT, "📣",
                        "12 ready-to-post LinkedIn posts from your real work, hooks and a 30-day calendar.",
                        pack="content"),
    "call": _product("1:1 career strategy call (45 min)", PRICE_CALL, "📞",
                     "A video call with Bhargab on your next move, positioning, job search or switch.", service=True),
    "audit": _product("Startup marketing audit", PRICE_AUDIT, "🚀",
                      "Bhargab reviews your brand, website, funnel and ads, then walks you through a written action plan.",
                      service=True),
    "claude": _product("Learn Claude AI for your work (1:1, 90 min)", PRICE_CLAUDE, "🤖",
                       "A hands-on session with Bhargab: set up Claude and build a real project from your own work, step by step.",
                       service=True),
}
# Products sold through the resume upload form, in display order.
CAREER_PRODUCTS = ["resume", "bundle", "linkedin", "premium", "interview", "outreach", "salary", "content"]
# Packs a customer can add to an existing order without uploading again.
ADDONS = ["linkedin", "interview", "outreach", "salary", "content"]
