# Resume Studio

Website and paid resume-tailoring service. Customers upload up to 6 resumes and a job description, pay Rs 500 with Cashfree, and get a tailored resume in a fixed template as Word and PDF.

## How it works

- `app/main.py`: website pages, order flow, Cashfree checkout and webhook, review/edit screen, downloads, `/admin`.
- `app/ai.py`: three Claude calls. (1) Extract a fact bank from the resumes. (2) Write the tailored resume, citing fact ids for every bullet. (3) Verify every line against the fact bank and fix anything unsupported. Gap notes tell the customer what the job wants that their resumes don't show.
- `app/render.py`: the fixed Word template (python-docx), PDF via LibreOffice, page previews via poppler.
- `app/db.py`: SQLite order store. Files live under `DATA_DIR/orders/<order id>/` and are deleted after `RETENTION_DAYS`.

## Run locally

Needs Python 3.11+, LibreOffice (`soffice`) and poppler (`pdftoppm`).

```sh
pip install -r requirements.txt
cp .env.example .env          # fill in what you have
set -a; . ./.env; set +a
uvicorn app.main:app --reload
```

With no `ANTHROPIC_API_KEY` the app returns sample content. With `DEV_SKIP_PAYMENT=true` the payment page shows a test button instead of Cashfree. Never set that in production.

## Deploy (Render)

1. Push this repo to GitHub.
2. On render.com: New > Blueprint, pick the repo. `render.yaml` creates a Docker web service with a 2 GB persistent disk at `/data`.
3. Fill in the environment variables (see `.env.example`). Set `SITE_URL` to your domain, e.g. `https://resume.yourdomain.com`.
4. Settings > Custom Domains: add your domain, then add the CNAME record Render shows at your domain registrar.
5. Cashfree merchant dashboard: Developers > API Keys, generate Payment Gateway keys and set `CASHFREE_APP_ID` / `CASHFREE_SECRET_KEY` (`CASHFREE_ENV=sandbox` for test keys). Whitelist your domain under Developers > Whitelisting. Optionally add a webhook to `https://<your domain>/webhooks/cashfree` (payment success); each order also passes it as `notify_url`.
6. Open `/admin` (any username, password `ADMIN_PASSWORD`) to see orders.

## Go-live checklist

- Real contact email, phone and business address in env vars (Cashfree requires them on the site).
- Cashfree live keys; one real Rs 500 test payment, then refund it.
- `ANTHROPIC_API_KEY` set, and several real resumes tested for quality.
- `RESEND_API_KEY` and a verified sending domain, so customers get their order link by email.

## Blog

Posts are Markdown files in `app/content/blog/` (the file name is the URL slug). Each starts with a front-matter
header (title, description, date, category, keywords, summary, takeaways, cta; see `app/blog.py`). A
"## Frequently asked questions" section with "### Question" headings becomes FAQ structured data. New posts appear on
/blog, in /sitemap.xml, /blog/feed.xml and /llms.txt after the next deploy.
