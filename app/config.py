"""Settings read from environment variables (see .env.example)."""
import os
from pathlib import Path


def _bool(name, default=False):
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


SITE_NAME = os.getenv("SITE_NAME", "Resume Studio")
SITE_URL = os.getenv("SITE_URL", "http://localhost:8000").rstrip("/")
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

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
AI_MODEL = os.getenv("AI_MODEL", "claude-opus-5-5")
# "mock" skips the AI and returns sample content, for local testing only.
AI_MODE = os.getenv("AI_MODE", "live" if ANTHROPIC_API_KEY else "mock")

RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "")
RAZORPAY_WEBHOOK_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET", "")
# Lets you skip payment locally when Razorpay keys are not set. Never enable in production.
DEV_SKIP_PAYMENT = _bool("DEV_SKIP_PAYMENT", False)

RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", f"{SITE_NAME} <no-reply@example.com>")

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")

FILES_DIR.mkdir(parents=True, exist_ok=True)
