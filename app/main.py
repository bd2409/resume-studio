import base64
import html
import json
import logging
import re
import secrets
import shutil
import tempfile
import threading
import urllib.parse
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi import Depends
from fastapi.concurrency import run_in_threadpool

from . import ai, auth, blog, config, db, faq, linkedin, mailer, payments, render
from .profile import PROFILE
from .schemas import Profile, Resume

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")

BASE = Path(__file__).parent
ALLOWED_EXT = {".pdf", ".docx", ".doc", ".rtf", ".odt", ".txt"}

app = FastAPI(title=config.SITE_NAME, docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")


@app.get("/ai", include_in_schema=False)
def ai_page_slash():
    # The /ai pages use relative links, so they need the trailing slash.
    return RedirectResponse("/ai/", status_code=301)


# AI automations for US real-estate agents: a static services page and demo, no server-side logic.
app.mount("/ai", StaticFiles(directory=BASE / "ai_site", html=True), name="ai_site")
templates = Jinja2Templates(directory=BASE / "templates")
templates.env.globals.update(linkedin_posts=lambda limit=None: linkedin.posts(limit), cfg=config, year=datetime.now().year, me=PROFILE, resume_templates=render.TEMPLATES,
                             latest_posts=blog.POSTS[:3],
                             services_schema=[
                                 {"@type": "Offer", "price": pr["price"], "priceCurrency": "INR",
                                  "url": f"{config.SITE_URL}/book/{k}" if pr["service"] else f"{config.SITE_URL}/build?product={k}",
                                  "itemOffered": {"@type": "Service", "name": pr["label"], "description": pr["blurb"]}}
                                 for k, pr in config.PRODUCTS.items() if k != "version"])

_generation_lock = threading.Lock()
_running = set()


# ------------------------------------------------------------------ helpers

def current_user(request):
    return auth.read_cookie(request.cookies.get(auth.COOKIE)) if auth.enabled() else None


def current_user_email(request):
    user = current_user(request)
    return user["email"] if user else None


def page(request, name, **ctx):
    ctx.setdefault("user", current_user(request))
    return templates.TemplateResponse(request, name, ctx)


def order_dir(order_id):
    return config.FILES_DIR / order_id


def output_paths(order):
    safe = re.sub(r"[^A-Za-z0-9]+", "_", order["customer_name"]).strip("_") or "Resume"
    d = order_dir(order["id"])
    return d / f"{safe}_Resume.docx", d / f"{safe}_Resume.pdf"


def cover_paths(order):
    docx_path, _ = output_paths(order)
    stem = docx_path.with_name(docx_path.name.replace("_Resume.docx", "_Cover_Letter.docx"))
    return stem, stem.with_suffix(".pdf")


def load_order(token):
    order = db.get_by_token(token)
    if not order:
        raise HTTPException(404, "Order not found")
    return order


def editable(order):
    if not order["paid_at"]:
        return False
    paid = datetime.fromisoformat(order["paid_at"])
    return datetime.now(timezone.utc) - paid < timedelta(days=config.EDIT_WINDOW_DAYS)


def render_files(order, resume: Resume, trim=False):
    """Writes the Word, PDF and preview files within the 2-page limit. Returns the resume as rendered
    (with trim=True, an AI-written resume may lose its least important lines to fit)."""
    docx_path, pdf_path = output_paths(order)
    template = order.get("template") or render.DEFAULT_TEMPLATE
    data, _ = render.build_fitted(resume.model_dump(), docx_path, template, trim=trim)
    resume = Resume.model_validate(data)
    render.to_previews(pdf_path)
    if order.get("cover_json"):
        cover_docx, _ = cover_paths(order)
        render.build_cover(resume.header.model_dump(), json.loads(order["cover_json"]), cover_docx, template,
                           datetime.now().strftime("%d %B %Y"))
        render.to_pdf(cover_docx)
    return resume


# ------------------------------------------------------------------ generation

def product_of(order):
    return config.PRODUCTS.get(order.get("product") or "resume", config.PRODUCTS["resume"])


def extra_of(order):
    return json.loads(order.get("extra_json") or "{}")


def owner_alert(order, what):
    product = product_of(order)
    lines = [f"{what}: {product['label']} (Rs {order['amount_paise'] // 100})",
             f"{order['customer_name']} · {order['email']} · {order['phone']}"]
    lines += [f"{k.replace('_', ' ').capitalize()}: {v}" for k, v in extra_of(order).items() if v]
    if order.get("target_role"):
        lines.append(f"Target role: {order['target_role']}")
    lines.append(f"{config.SITE_URL}/order/{order['token']}")
    mailer.owner_alert(f"{what}: {product['label']} - {order['customer_name']}", lines)


def run_generation(order_id, instructions="", part="all"):
    """part: "all" on first run, or "resume" / "linkedin" / "pack" when the customer regenerates one deliverable."""
    with _generation_lock:
        if order_id in _running:
            return
        _running.add(order_id)
    try:
        order = db.get_by_id(order_id)
        product = product_of(order)
        if product["service"]:
            # Calls and audits are done by Bhargab himself: confirm the booking and tell him.
            if order["status"] in ("paid", "generating"):
                db.update(order_id, status="ready", progress="")
                mailer.booking_confirmed(order)
                owner_alert(order, "New booking")
            return
        do_resume = product["resume"] and part in ("all", "resume")
        do_linkedin = product["linkedin"] and part in ("all", "linkedin")
        do_pack = bool(product["pack"]) and part in ("all", "pack")
        first_time = not order["resume_json"] and not order["linkedin_json"] and not order["pack_json"]
        db.update(order_id, status="generating", error="", progress="Reading your resumes")
        updates = {}
        if config.AI_MODE == "mock":
            time.sleep(2)
            if do_resume:
                resume, notes = ai.mock_generate()
                if not order["cover_json"]:
                    updates["cover_json"] = ai.mock_cover_letter(resume).model_dump_json()
            if do_linkedin:
                updates["linkedin_json"] = ai.mock_linkedin().model_dump_json()
            if do_pack:
                updates["pack_json"] = ai.mock_pack(product["pack"]).model_dump_json()
        else:
            if order["profile_json"]:
                profile = Profile.model_validate_json(order["profile_json"])
            else:
                files = [order_dir(order_id) / "uploads" / f for f in json.loads(order["files_json"])]
                profile = ai.extract_profile(files)
                db.update(order_id, profile_json=profile.model_dump_json())
            job = ai.job_brief(order["job_description"], order["target_role"])
            if do_resume:
                db.update(order_id, progress="Writing and checking your tailored resume")
                resume, notes = ai.write_and_verify(profile, job, instructions)
                if not order["cover_json"]:
                    db.update(order_id, progress="Writing your cover letter")
                    try:
                        updates["cover_json"] = ai.write_cover_letter(profile, job, resume).model_dump_json()
                    except Exception:
                        log.exception("Cover letter failed for %s", order_id)  # the resume still ships
            if do_linkedin:
                db.update(order_id, progress="Rewriting your LinkedIn profile")
                updates["linkedin_json"] = ai.write_linkedin(profile, job, instructions).model_dump_json()
            if do_pack:
                db.update(order_id, progress=f"Writing your {product['label'].lower()}")
                details = extra_of(order).get("offer_details", "")
                updates["pack_json"] = ai.write_pack(product["pack"], profile, job, details, instructions).model_dump_json()
        if updates:
            db.update(order_id, **updates)
        if do_resume:
            db.update(order_id, progress="Creating your Word and PDF files")
            resume = render_files(db.get_by_id(order_id), resume, trim=True)
            db.update(order_id, resume_json=resume.model_dump_json(), notes_json=json.dumps(notes))
        db.update(order_id, status="ready", progress="")
        if first_time:
            mailer.order_ready(db.get_by_id(order_id))
            if product["human"]:
                owner_alert(db.get_by_id(order_id), "Premium order to review")
    except Exception as exc:
        log.exception("Generation failed for %s", order_id)
        db.update(order_id, status="failed", progress="", error=str(exc)[:500])
    finally:
        with _generation_lock:
            _running.discard(order_id)


def start_generation(background: BackgroundTasks, order_id, instructions="", part="all"):
    db.update(order_id, status="generating", progress="Starting")
    background.add_task(run_generation, order_id, instructions, part)


def cleanup_loop():
    while True:
        try:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=config.RETENTION_DAYS)).isoformat()
            for order_id in db.expired_orders(cutoff):
                if order_dir(order_id).exists():
                    shutil.rmtree(order_dir(order_id), ignore_errors=True)
                    db.purge_content(order_id)
                    log.info("Deleted files for %s (retention)", order_id)
        except Exception:
            log.exception("Cleanup failed")
        time.sleep(6 * 3600)


@app.on_event("startup")
def startup():
    db.init()
    linkedin.start()
    threading.Thread(target=cleanup_loop, daemon=True).start()
    # Resume work interrupted by a restart.
    with db.conn() as c:
        stuck = [r["id"] for r in c.execute("SELECT id FROM orders WHERE status IN ('paid', 'generating')")]
    for order_id in stuck:
        threading.Thread(target=run_generation, args=(order_id,), daemon=True).start()


# ------------------------------------------------------------------ website pages

STATIC_PAGES = {
    "/": "personal.html",
    "/resume": "home.html",
    "/pricing": "pricing.html",
    "/contact": "contact.html",
    "/terms": "terms.html",
    "/privacy": "privacy.html",
    "/refund-policy": "refund.html",
    "/services": "services.html",
    "/colleges": "colleges.html",
    "/free": "free.html",
    "/editorial-policy": "editorial.html",
}


def _static_page(template):
    def handler(request: Request):
        return page(request, template)
    return handler


for _path, _template in STATIC_PAGES.items():
    app.add_api_route(_path, _static_page(_template), methods=["GET"], response_class=HTMLResponse)


PUBLIC_PAGES = ["/", "/resume", "/blog", "/services", "/free", "/free/playbook", "/free/resume-check", "/book/claude", "/colleges", "/pricing", "/faq", "/contact", "/terms", "/privacy", "/refund-policy", "/editorial-policy", "/ai/", "/ai/demo.html"]


AI_CRAWLERS = ["GPTBot", "OAI-SearchBot", "ChatGPT-User", "ClaudeBot", "Claude-SearchBot", "Claude-User",
               "PerplexityBot", "Google-Extended", "Applebot-Extended", "Bingbot"]


@app.get("/robots.txt", response_class=PlainTextResponse)
def robots():
    private = "Disallow: /order/\nDisallow: /admin\nDisallow: /webhooks/\nDisallow: /account\n"
    # Search engines and AI assistants are welcome on the public pages, so they can cite and recommend the site.
    ai_rules = "".join(f"User-agent: {bot}\nAllow: /\n{private}\n" for bot in AI_CRAWLERS)
    return f"User-agent: *\nAllow: /\n{private}\n{ai_rules}Sitemap: {config.SITE_URL}/sitemap.xml\n"


@app.get("/sitemap.xml")
def sitemap():
    today = datetime.now(timezone.utc).date().isoformat()
    entries = [(path, today, "1.0" if path in ("/", "/resume") else "0.7" if path in ("/blog", "/services", "/free") else "0.5")
               for path in PUBLIC_PAGES]
    entries += [(f"/blog/{p['slug']}", p["updated"].isoformat(), "0.8") for p in blog.POSTS]
    urls = "".join(f"<url><loc>{config.SITE_URL}{path}</loc><lastmod>{mod}</lastmod><priority>{prio}</priority></url>"
                   for path, mod, prio in entries)
    xml = f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>'
    return Response(xml, media_type="application/xml")


@app.get("/llms.txt", response_class=PlainTextResponse)
def llms_txt():
    """A plain-text guide to the site for AI assistants (the llms.txt convention)."""
    u = config.SITE_URL
    lines = [f"# {config.SITE_NAME} by {PROFILE['name']}", "",
             f"> {PROFILE['name']} is a marketing strategist for startups based in India. {config.SITE_NAME} ({u}/resume) "
             "writes job-tailored, ATS-friendly resumes and cover letters from a customer's own existing resumes, "
             "checking every line against their real experience. It also offers LinkedIn makeovers, interview, outreach and "
             "salary negotiation packs, free tools for professionals over 35, 1:1 Claude AI coaching, career calls and "
             "startup marketing audits.", "",
             "## Services and prices (one-time, in Indian rupees)"]
    for key, pr in config.PRODUCTS.items():
        if key == "version":
            continue
        link = f"{u}/book/{key}" if pr["service"] else f"{u}/build?product={key}"
        lines.append(f"- [{pr['label']}]({link}): Rs {pr['price']:,}. {pr['blurb']}")
    lines += ["", "## Free tools",
              f"- [Free age-proof resume check]({u}/free/resume-check): score out of 100 and fixes for experienced professionals",
              f"- [35+ Career Comeback Playbook]({u}/free/playbook): resume and LinkedIn fixes plus 15 Claude prompts",
              "", "## Key facts",
              "- Resumes use only facts from the customer's own uploaded resumes; nothing is invented.",
              "- Output: editable Word and PDF, four ATS-friendly single-column designs, one page under 5 years of experience, two pages at most otherwise.",
              f"- Edits for {config.EDIT_WINDOW_DAYS} days, {config.MAX_REGENERATIONS} free regenerations; files deleted after {config.RETENTION_DAYS} days.",
              "- Payments by UPI, cards, netbanking and wallets through Cashfree.",
              "", "## Guides"]
    lines += [f"- [{p['title']}]({u}/blog/{p['slug']}): {p['summary']}" for p in blog.POSTS]
    lines += ["", "## More", f"- [About {PROFILE['name']}]({u}/)", f"- [All services]({u}/services)", f"- [Pricing]({u}/pricing)",
              f"- [FAQ]({u}/faq)", f"- [Contact]({u}/contact)"]
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------ blog and FAQ

def _faq_schema(pairs):
    return {"@type": "FAQPage", "mainEntity": [
        {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in pairs]}


@app.get("/faq", response_class=HTMLResponse)
def faq_page(request: Request):
    items = faq.items()
    return page(request, "faq.html", faqs=items, schema={"@context": "https://schema.org", **_faq_schema(items)})


@app.get("/blog", response_class=HTMLResponse)
def blog_index(request: Request):
    schema = {"@context": "https://schema.org", "@type": "Blog", "name": f"{config.SITE_NAME} blog",
              "url": f"{config.SITE_URL}/blog",
              "author": {"@type": "Person", "name": PROFILE["name"], "url": f"{config.SITE_URL}/"},
              "blogPost": [{"@type": "BlogPosting", "headline": p["title"], "url": f"{config.SITE_URL}/blog/{p['slug']}",
                            "datePublished": p["date"].isoformat()} for p in blog.POSTS]}
    return page(request, "blog_index.html", posts=blog.POSTS, schema=schema)


@app.get("/blog/feed.xml")
def blog_feed():
    from email.utils import format_datetime
    from xml.sax.saxutils import escape
    items = "".join(
        f"<item><title>{escape(p['title'])}</title><link>{config.SITE_URL}/blog/{p['slug']}</link>"
        f"<guid>{config.SITE_URL}/blog/{p['slug']}</guid><description>{escape(p['description'])}</description>"
        f"<pubDate>{format_datetime(datetime(p['date'].year, p['date'].month, p['date'].day, tzinfo=timezone.utc))}</pubDate></item>"
        for p in blog.POSTS)
    xml = (f'<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>{escape(config.SITE_NAME)} blog</title>'
           f"<link>{config.SITE_URL}/blog</link><description>Career guides by {escape(PROFILE['name'])}</description>{items}</channel></rss>")
    return Response(xml, media_type="application/rss+xml")


@app.get("/blog/{slug}", response_class=HTMLResponse)
def blog_post(request: Request, slug: str):
    post = blog.BY_SLUG.get(slug)
    if not post:
        raise HTTPException(404)
    url = f"{config.SITE_URL}/blog/{slug}"
    graph = [
        {"@type": "BlogPosting", "@id": url + "#article", "headline": post["title"], "description": post["description"],
         "abstract": post["summary"], "datePublished": post["date"].isoformat(), "dateModified": post["updated"].isoformat(),
         "keywords": post["keywords"], "articleSection": post["category"], "inLanguage": "en-IN", "mainEntityOfPage": url,
         "image": config.SITE_URL + PROFILE["photo"],
         "author": {"@type": "Person", "name": PROFILE["name"], "url": f"{config.SITE_URL}/", "sameAs": [PROFILE["linkedin"]]},
         "publisher": {"@type": "Organization", "name": config.SITE_NAME, "url": f"{config.SITE_URL}/resume"}},
        {"@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Home", "item": f"{config.SITE_URL}/"},
            {"@type": "ListItem", "position": 2, "name": "Blog", "item": f"{config.SITE_URL}/blog"},
            {"@type": "ListItem", "position": 3, "name": post["title"], "item": url}]},
    ]
    if post["faqs"]:
        graph.append(_faq_schema([(f["q"], f["a"]) for f in post["faqs"]]))
    related = [p for p in blog.POSTS if p["slug"] != slug and p["category"] == post["category"]]
    related += [p for p in blog.POSTS if p["slug"] != slug and p not in related]
    return page(request, "blog_post.html", post=post, related=related[:3],
                schema={"@context": "https://schema.org", "@graph": graph}, og_type="article")


# ------------------------------------------------------------------ accounts

def _safe_next(target):
    return target if target and target.startswith("/") and not target.startswith("//") else "/account"


@app.get("/signin", response_class=HTMLResponse)
def signin(request: Request, next: str = "/account"):
    if current_user(request):
        return RedirectResponse(_safe_next(next), status_code=303)
    return page(request, "signin.html", next=_safe_next(next), google_enabled=auth.enabled())


@app.post("/auth/google")
async def auth_google(request: Request):
    """Receives the Google ID token from the sign-in button (same-origin fetch) and starts a session."""
    body = await request.json()
    result = auth.verify_google(body.get("credential", "")) if auth.enabled() else None
    if not result:
        raise HTTPException(400, "Sign-in failed. Please try again.")
    email, name = result
    response = JSONResponse({"next": _safe_next(body.get("next"))})
    response.set_cookie(auth.COOKIE, auth.make_cookie(email, name), max_age=auth.MAX_AGE, httponly=True,
                        secure=config.SITE_URL.startswith("https"), samesite="lax")
    return response


@app.get("/signout")
def signout():
    response = RedirectResponse("/resume", status_code=303)
    response.delete_cookie(auth.COOKIE)
    return response


@app.get("/account", response_class=HTMLResponse)
def account(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse("/signin?next=/account", status_code=303)
    orders = [o for o in db.orders_for_email(user["email"]) if o["status"] != "awaiting_payment" or o["user_email"]]
    for o in orders:
        o["has_preview"] = (order_dir(o["id"]) / "preview-1.png").exists()
        o["notes"] = json.loads(o["notes_json"] or "{}")
    return page(request, "account.html", orders=orders)


@app.get("/healthz")
def healthz():
    # Setup status without any secret values, so the owner can see why checkout is hidden.
    return {"ok": True, "ai_connected": config.AI_MODE == "live", "cashfree_keys_set": payments.enabled(),
            "cashfree_mode": payments.mode(), "checkout_for_everyone": payments.enabled() and config.AI_MODE == "live"
            and payments.mode() == "production",
            "linkedin_posts_embedded": f"{sum(1 for p in linkedin.posts() if p['embed'])} of {len(linkedin.POSTS)}"}


# ------------------------------------------------------------------ order flow

@app.get("/build", response_class=HTMLResponse)
def build_form(request: Request):
    return page(request, "build.html", error=None, form={})


@app.post("/build", response_class=HTMLResponse)
async def build_submit(
    request: Request,
    customer_name: str = Form(...),
    email: str = Form(...),
    phone: str = Form(...),
    job_description: str = Form(""),
    mode: str = Form("tailor"),
    product: str = Form("resume"),
    target_role: str = Form(""),
    consent: str = Form(None),
    template: str = Form(render.DEFAULT_TEMPLATE),
    offer_details: str = Form(""),
    resumes: list[UploadFile] = File(...),
):
    if template not in render.TEMPLATES:
        template = render.DEFAULT_TEMPLATE
    mode = "improve" if mode == "improve" else "tailor"
    if product not in config.CAREER_PRODUCTS:
        product = "resume"
    if mode == "improve":
        job_description = ""
    form = {"customer_name": customer_name, "email": email, "phone": phone, "job_description": job_description,
            "template": template, "mode": mode, "target_role": target_role, "product": product,
            "offer_details": offer_details}
    resumes = [f for f in resumes if f.filename]

    def fail(msg):
        return page(request, "build.html", error=msg, form=form)

    if not consent:
        return fail("Please agree to the terms and privacy policy to continue.")
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email.strip()):
        return fail("Please enter a valid email address.")
    if len(re.sub(r"\D", "", phone)) < 10:
        return fail("Please enter a valid phone number.")
    if mode == "tailor" and len(job_description.strip()) < 150:
        return fail("Please paste the full job description (at least a few lines).")
    if mode == "improve" and len(target_role.strip()) < 3:
        return fail("Please tell us the kind of role you're aiming for.")
    if product == "salary" and len(offer_details.strip()) < 20:
        return fail("Please tell us about the offer: the company, role and the numbers you have.")
    if not resumes:
        return fail("Please upload at least one resume.")
    saved, error = await read_uploads(resumes)
    if error:
        return fail(error)

    order = db.create_order(customer_name.strip(), email.strip(), phone.strip(), job_description.strip(),
                            [], config.PRODUCTS[product]["price"] * 100)
    extra = {"offer_details": offer_details.strip()[:3000]} if product == "salary" else {}
    db.update(order["id"], files_json=json.dumps(store_uploads(order["id"], saved)), template=template,
              target_role=target_role.strip()[:120], product=product, extra_json=json.dumps(extra),
              user_email=current_user_email(request))
    return RedirectResponse(f"/order/{order['token']}", status_code=303)


async def read_uploads(files):
    """Returns ([(ext, bytes)], error message or None)."""
    if len(files) > config.MAX_RESUMES:
        return [], f"You can upload at most {config.MAX_RESUMES} resumes."
    saved = []
    for f in files:
        ext = Path(f.filename).suffix.lower()
        if ext not in ALLOWED_EXT:
            return [], f"{f.filename}: please upload PDF or Word files."
        data = await f.read()
        if len(data) > config.MAX_FILE_MB * 1024 * 1024:
            return [], f"{f.filename} is larger than {config.MAX_FILE_MB} MB."
        saved.append((ext, data))
    return saved, None


def store_uploads(order_id, saved):
    up = order_dir(order_id) / "uploads"
    up.mkdir(parents=True, exist_ok=True)
    names = []
    for i, (ext, data) in enumerate(saved, 1):
        name = f"resume_{i}{ext}"
        (up / name).write_bytes(data)
        names.append(name)
    return names


BOOKING_FIELDS = {
    "call": [("topic", "What would you like to discuss?", True), ("linkedin_url", "Your LinkedIn profile (optional)", False),
             ("preferred_times", "Days and times that suit you", False)],
    "audit": [("company", "Company or brand name", True), ("website", "Website or app link", True),
              ("stage", "Stage and size (for example: seed, 12 people, Rs 40 lakh monthly revenue)", True),
              ("goals", "What do you want marketing to achieve in the next 6 months?", True),
              ("channels", "What are you doing in marketing today? (optional)", False)],
    "claude": [("work", "Your work or business (for example: HR head at a manufacturing company)", True),
               ("goal", "What would you like Claude to help you do? A project, report, task or workflow", True),
               ("level", "Have you used ChatGPT, Claude or other AI tools before? (optional)", False),
               ("preferred_times", "Days and times that suit you", False)],
}


@app.get("/book/{product}", response_class=HTMLResponse)
def book_form(request: Request, product: str):
    if product not in BOOKING_FIELDS:
        raise HTTPException(404)
    return page(request, "book.html", key=product, product=config.PRODUCTS[product],
                fields=BOOKING_FIELDS[product], error=None, form={})


@app.post("/book/{product}", response_class=HTMLResponse)
async def book_submit(request: Request, product: str):
    if product not in BOOKING_FIELDS:
        raise HTTPException(404)
    f = await request.form()
    g = lambda k: (f.get(k) or "").strip() if isinstance(f.get(k), str) else ""  # noqa: E731
    form = {k: g(k) for k in ["customer_name", "email", "phone"] + [n for n, _, _ in BOOKING_FIELDS[product]]}

    def fail(msg):
        return page(request, "book.html", key=product, product=config.PRODUCTS[product],
                    fields=BOOKING_FIELDS[product], error=msg, form=form)

    if not g("consent"):
        return fail("Please agree to the terms and privacy policy to continue.")
    if len(form["customer_name"]) < 2:
        return fail("Please enter your name.")
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", form["email"]):
        return fail("Please enter a valid email address.")
    if len(re.sub(r"\D", "", form["phone"])) < 10:
        return fail("Please enter a valid phone number.")
    for name, label, required in BOOKING_FIELDS[product]:
        if required and len(form[name]) < 2:
            return fail(f"Please fill in: {label}")
    files = [x for x in f.getlist("resumes") if getattr(x, "filename", "")]
    saved, error = await read_uploads(files)
    if error:
        return fail(error)
    order = db.create_order(form["customer_name"], form["email"], form["phone"], "", [],
                            config.PRODUCTS[product]["price"] * 100)
    extra = {name: form[name][:2000] for name, _, _ in BOOKING_FIELDS[product]}
    db.update(order["id"], product=product, extra_json=json.dumps(extra), user_email=current_user_email(request),
              files_json=json.dumps(store_uploads(order["id"], saved)) if saved else "[]")
    return RedirectResponse(f"/order/{order['token']}", status_code=303)


# ------------------------------------------------------------------ free lead magnets (for 35+ professionals)

def _valid_email(email):
    return re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email or "") is not None


@app.get("/free/playbook", response_class=HTMLResponse)
def playbook(request: Request, t: str = ""):
    reader = auth.read_cookie(t) if t else None
    if reader:
        return page(request, "playbook.html", reader=reader)
    return page(request, "playbook_gate.html", error=None, form={})


@app.post("/free/playbook", response_class=HTMLResponse)
async def playbook_signup(request: Request):
    f = await request.form()
    form = {k: (f.get(k) or "").strip()[:200] for k in ("name", "email", "phone", "age_band")}
    if len(form["name"]) < 2 or not _valid_email(form["email"]):
        return page(request, "playbook_gate.html", error="Please enter your name and a valid email.", form=form)
    if not db.lead_for("playbook", form["email"]):
        db.add_enquiry("playbook", form["name"], form["email"], form["phone"], "", f"Age: {form['age_band']}")
    token = auth.make_cookie(form["email"], form["name"])
    link = f"{config.SITE_URL}/free/playbook?t={urllib.parse.quote(token)}"
    mailer.send(form["email"], f"Your 35+ Career Comeback Playbook - {config.SITE_NAME}",
                f"<p>Hi {html.escape(form['name'])},</p><p>Here's your playbook: <a href=\"{link}\">{link}</a></p>"
                f"<p>Bhargab</p>")
    return RedirectResponse(f"/free/playbook?t={urllib.parse.quote(token)}", status_code=303)


@app.get("/free/resume-check", response_class=HTMLResponse)
def resume_check_form(request: Request, t: str = ""):
    reader = auth.read_cookie(t) if t else None
    lead = db.lead_for("resume-check", reader["email"]) if reader else None
    if lead and lead["details"].startswith("{"):
        return page(request, "resume_check.html", result=json.loads(lead["details"]), person=lead["name"])
    return page(request, "resume_check.html", result=None, error=None, form={})


@app.post("/free/resume-check", response_class=HTMLResponse)
async def resume_check_submit(request: Request):
    f = await request.form()
    form = {k: (f.get(k) or "").strip()[:200] if isinstance(f.get(k), str) else "" for k in ("name", "email", "phone", "target_role", "consent")}

    def fail(msg):
        return page(request, "resume_check.html", result=None, error=msg, form=form)

    if len(form["name"]) < 2 or not _valid_email(form["email"]):
        return fail("Please enter your name and a valid email.")
    if not form["consent"]:
        return fail("Please agree to the privacy policy so we can read your resume.")
    token = urllib.parse.quote(auth.make_cookie(form["email"], form["name"]))
    if db.lead_for("resume-check", form["email"]):
        return RedirectResponse(f"/free/resume-check?t={token}", status_code=303)  # one free check per email
    if db.leads_today("resume-check") >= config.FREE_CHECKS_PER_DAY:
        return fail("Today's free checks are all used up. Please come back tomorrow, or get your full resume rewritten now.")
    upload = f.get("resume")
    if not getattr(upload, "filename", ""):
        return fail("Please upload your resume.")
    saved, error = await read_uploads([upload])
    if error:
        return fail(error)
    ext, data = saved[0]
    tmp = Path(tempfile.mkdtemp()) / f"resume{ext}"
    tmp.write_bytes(data)
    try:
        if config.AI_MODE == "mock":
            result = ai.mock_resume_check()
        else:
            result = await run_in_threadpool(ai.resume_check, tmp, form["target_role"])
    except Exception:
        log.exception("Free resume check failed")
        return fail("Sorry, we couldn't read that file. Please try a PDF or Word version.")
    finally:
        shutil.rmtree(tmp.parent, ignore_errors=True)  # the free check keeps no copy of the resume
    db.add_enquiry("resume-check", form["name"], form["email"], form["phone"], form["target_role"], result.model_dump_json())
    link = f"{config.SITE_URL}/free/resume-check?t={token}"
    mailer.send(form["email"], f"Your free resume check: {result.score}/100 - {config.SITE_NAME}",
                f"<p>Hi {html.escape(form['name'])},</p><p>Your resume scored {result.score}/100. "
                f"See your full results and fixes here: <a href=\"{link}\">{link}</a></p><p>Bhargab</p>")
    return RedirectResponse(f"/free/resume-check?t={token}", status_code=303)


@app.post("/enquiry", response_class=HTMLResponse)
async def enquiry(request: Request):
    """College, bootcamp and company enquiries for bulk plans. No payment; Bhargab follows up."""
    f = await request.form()
    g = lambda k: (f.get(k) or "").strip()[:2000]  # noqa: E731
    form = {k: g(k) for k in ("name", "email", "phone", "org", "role", "students", "details")}
    error = None
    if len(form["name"]) < 2 or len(form["org"]) < 2:
        error = "Please enter your name and your institution."
    elif not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", form["email"]):
        error = "Please enter a valid email address."
    elif len(re.sub(r"\D", "", form["phone"])) < 10:
        error = "Please enter a valid phone number."
    if error:
        return page(request, "colleges.html", error=error, form=form)
    details = f"Role: {form['role']}\nStudents per year: {form['students']}\n{form['details']}"
    db.add_enquiry("college", form["name"], form["email"], form["phone"], form["org"], details)
    mailer.owner_alert(f"College enquiry: {form['org']}",
                       [f"{form['name']} ({form['role']}) · {form['email']} · {form['phone']}", form["org"],
                        f"Students per year: {form['students']}", form["details"]])
    return page(request, "colleges.html", sent=True, form={})


def is_owner(request: Request):
    """True when the browser sends the admin password (it does after signing in at /admin)."""
    auth = request.headers.get("authorization", "")
    if not config.ADMIN_PASSWORD or not auth.lower().startswith("basic "):
        return False
    try:
        password = base64.b64decode(auth[6:]).decode().partition(":")[2]
    except Exception:
        return False
    return secrets.compare_digest(password, config.ADMIN_PASSWORD)


def checkout_open(request: Request):
    """Real payments for everyone in production; sandbox (test) checkout only for the owner."""
    if not payments.enabled() or config.AI_MODE != "live":
        return False
    return payments.mode() == "production" or is_owner(request)


@app.get("/order/{token}", response_class=HTMLResponse)
def order_page(request: Request, token: str):
    order = load_order(token)
    status = order["status"]
    product = product_of(order)
    if status == "awaiting_payment":
        return page(request, "pay.html", order=order, cashfree=checkout_open(request), cf_mode=payments.mode(),
                    payment_failed=request.query_params.get("payment") == "failed",
                    dev_skip=config.DEV_SKIP_PAYMENT, file_count=len(json.loads(order["files_json"])),
                    product=product, extra=extra_of(order))
    if status in ("paid", "generating"):
        return page(request, "progress.html", order=order)
    if product["service"]:
        return page(request, "booked.html", order=order, product=product, extra=extra_of(order))
    if status == "failed" and not (order["resume_json"] or order["linkedin_json"] or order["pack_json"]):
        return page(request, "failed.html", order=order)
    if not order["resume_json"]:
        if order["linkedin_json"]:
            return RedirectResponse(f"/order/{token}/linkedin", status_code=303)
        if order["pack_json"]:
            return RedirectResponse(f"/order/{token}/pack", status_code=303)
        return page(request, "failed.html", order=order, expired=True)
    resume = Resume.model_validate_json(order["resume_json"])
    notes = json.loads(order["notes_json"] or "{}")
    previews = sorted(order_dir(order["id"]).glob("preview-*.png"))
    cover = json.loads(order["cover_json"]) if order["cover_json"] else None
    return page(request, "review.html", order=order, resume=resume, notes=notes, cover=cover,
                pages=len(previews),
                can_edit=editable(order),
                regen_left=max(0, config.MAX_REGENERATIONS - order["regenerations"]),
                version=int(time.time()), last_failed=status == "failed",
                product=product, has_linkedin=bool(order["linkedin_json"]), addons=addons_for(order))


def addons_for(order):
    """Packs this customer can add without uploading again (only ones the order doesn't already include)."""
    if not order["paid_at"] or not order["files_json"] or order["files_json"] == "[]":
        return []
    own = product_of(order)
    return [(k, config.PRODUCTS[k]) for k in config.ADDONS
            if not (k == "linkedin" and own["linkedin"]) and own["pack"] != k]


@app.get("/order/{token}/pack", response_class=HTMLResponse)
def pack_page(request: Request, token: str):
    order = load_order(token)
    if not order["pack_json"] or order["status"] in ("awaiting_payment", "paid", "generating"):
        return RedirectResponse(f"/order/{token}", status_code=303)
    return page(request, "pack.html", order=order, pack=json.loads(order["pack_json"]), product=product_of(order),
                can_edit=editable(order), regen_left=max(0, config.MAX_REGENERATIONS - order["regenerations"]),
                last_failed=order["status"] == "failed", addons=addons_for(order))


@app.get("/order/{token}/linkedin", response_class=HTMLResponse)
def linkedin_page(request: Request, token: str):
    order = load_order(token)
    if not order["linkedin_json"] or order["status"] in ("awaiting_payment", "paid", "generating"):
        return RedirectResponse(f"/order/{token}", status_code=303)
    from .schemas import LinkedInProfile
    li = LinkedInProfile.model_validate_json(order["linkedin_json"])
    return page(request, "linkedin.html", order=order, li=li, product=product_of(order),
                can_edit=editable(order), regen_left=max(0, config.MAX_REGENERATIONS - order["regenerations"]),
                last_failed=order["status"] == "failed", addons=addons_for(order))


@app.post("/order/{token}/new-version")
def new_version(token: str, job_description: str = Form(...)):
    """A paid follow-up: same customer and fact bank, a new job description, a new resume and cover letter."""
    if len(job_description.strip()) < 150:
        raise HTTPException(400, "Please paste the full job description")
    return _child_order(load_order(token), "version", job_description.strip())


@app.post("/order/{token}/addon")
def addon(token: str, product: str = Form(...), offer_details: str = Form("")):
    """Adds a pack (interview prep, outreach, ...) built from the same resumes and target job."""
    parent = load_order(token)
    if product not in dict(addons_for(parent)):
        raise HTTPException(400, "This add-on isn't available for this order")
    extra = {"offer_details": offer_details.strip()[:3000]} if product == "salary" else {}
    return _child_order(parent, product, parent["job_description"], extra)


def _child_order(parent, product, job_description, extra=None):
    """Same customer and fact bank as a paid order; nothing to upload again."""
    if not parent["paid_at"] or parent["files_json"] in (None, "", "[]"):
        raise HTTPException(400, "This order can't be used for that")
    child = db.create_order(parent["customer_name"], parent["email"], parent["phone"], job_description,
                            [], config.PRODUCTS[product]["price"] * 100)
    src, dst = order_dir(parent["id"]) / "uploads", order_dir(child["id"]) / "uploads"
    if src.exists():
        shutil.copytree(src, dst)
    db.update(child["id"], files_json=parent["files_json"], profile_json=parent["profile_json"],
              template=parent["template"], target_role=parent["target_role"], user_email=parent["user_email"],
              product=product, parent_id=parent["id"], extra_json=json.dumps(extra or {}))
    return RedirectResponse(f"/order/{child['token']}", status_code=303)


@app.get("/order/{token}/status")
def order_status(token: str):
    order = load_order(token)
    return {"status": order["status"], "progress": order["progress"]}


@app.post("/order/{token}/checkout")
def checkout(token: str, request: Request):
    order = load_order(token)
    if order["status"] != "awaiting_payment":
        return JSONResponse({"paid": True})
    if not checkout_open(request):
        # Never take money while the AI is not connected, and keep test checkout to the owner.
        raise HTTPException(400, "Payments are not configured")
    cf_order_id, session_id = payments.session_for(order)
    db.update(order["id"], rzp_order_id=cf_order_id)
    return {"payment_session_id": session_id, "mode": payments.mode()}


def _confirm_payment(order, background):
    """Checks with Cashfree and starts generation once. Returns True if the order is paid."""
    if order["status"] != "awaiting_payment":
        return True
    payment_id = payments.confirmed_payment(order)
    if not payment_id:
        return False
    if db.mark_paid(order["id"], payment_id):
        start_generation(background, order["id"])
    return True


@app.get("/order/{token}/payment-return")
def payment_return(token: str, background: BackgroundTasks):
    order = load_order(token)
    try:
        paid = _confirm_payment(order, background)
    except Exception:
        log.exception("Payment check failed for %s", order["id"])
        paid = False
    return RedirectResponse(f"/order/{token}" + ("" if paid else "?payment=failed"), status_code=303)


@app.post("/order/{token}/dev-pay")
def dev_pay(token: str, background: BackgroundTasks):
    if not config.DEV_SKIP_PAYMENT:
        raise HTTPException(404)
    order = load_order(token)
    if db.mark_paid(order["id"], "dev_" + secrets.token_hex(4)):
        start_generation(background, order["id"])
    return RedirectResponse(f"/order/{token}", status_code=303)


@app.post("/order/{token}/owner-pay")
def owner_pay(token: str, background: BackgroundTasks, creds: HTTPBasicCredentials = Depends(HTTPBasic())):
    """Lets the site owner run an order without payment (tests, or clients who paid directly)."""
    admin_auth(creds)
    order = load_order(token)
    if db.mark_paid(order["id"], "owner_" + secrets.token_hex(4)):
        start_generation(background, order["id"])
    return RedirectResponse(f"/order/{token}", status_code=303)


@app.post("/webhooks/cashfree")
async def cashfree_webhook(request: Request, background: BackgroundTasks):
    raw = await request.body()
    if not payments.verify_webhook(raw, request.headers.get("x-webhook-timestamp", ""),
                                   request.headers.get("x-webhook-signature", "")):
        raise HTTPException(400, "Bad signature")
    event = json.loads(raw)
    cf_order_id = ((event.get("data") or {}).get("order") or {}).get("order_id")
    order = db.get_by_rzp_order(cf_order_id) if cf_order_id else None
    if order:
        # Confirm with Cashfree's API rather than trusting the payload.
        _confirm_payment(order, background)
    return {"ok": True}


@app.post("/order/{token}/retry")
def retry(token: str, background: BackgroundTasks):
    order = load_order(token)
    if order["status"] == "failed":
        start_generation(background, order["id"])
    return RedirectResponse(f"/order/{token}", status_code=303)


def _lines(text):
    return [ln.strip(" \t-•▪*") for ln in (text or "").splitlines() if ln.strip(" \t-•▪*")]


@app.post("/order/{token}/save")
async def save(token: str, request: Request):
    order = load_order(token)
    if order["status"] not in ("ready", "failed") or not order["resume_json"] or not editable(order):
        raise HTTPException(400, "This resume can no longer be edited")
    f = await request.form()
    g = lambda k: (f.get(k) or "").strip()  # noqa: E731

    jobs, edus = [], []
    i = 0
    while f"job-{i}-company" in f:
        if g(f"job-{i}-company") and not g(f"job-{i}-delete"):
            jobs.append({
                "company": g(f"job-{i}-company"), "location": g(f"job-{i}-location"),
                "title": g(f"job-{i}-title"), "dates": g(f"job-{i}-dates"),
                "context": g(f"job-{i}-context"), "bullets": _lines(f.get(f"job-{i}-bullets")),
            })
        i += 1
    i = 0
    while f"edu-{i}-degree" in f:
        if g(f"edu-{i}-degree") and not g(f"edu-{i}-delete"):
            edus.append({
                "degree": g(f"edu-{i}-degree"), "institution": g(f"edu-{i}-institution"),
                "dates": g(f"edu-{i}-dates"), "grade": g(f"edu-{i}-grade"),
            })
        i += 1

    resume = Resume.model_validate({
        "header": {k: g(f"h-{k}") for k in ("name", "headline", "email", "phone", "linkedin", "location")},
        "summary": g("summary"),
        "competencies": _lines(f.get("competencies")),
        "experience": jobs,
        "education": edus,
        "certifications": _lines(f.get("certifications")),
        "achievements": _lines(f.get("achievements")),
    })
    if order["cover_json"] and "cover-body" in f:
        paragraphs = [x.strip() for x in re.split(r"\n\s*\n", f.get("cover-body") or "") if x.strip()]
        if paragraphs:
            order["cover_json"] = json.dumps({"greeting": g("cover-greeting") or "Dear Hiring Manager,",
                                              "paragraphs": paragraphs, "closing": g("cover-closing") or "Sincerely,"})
            db.update(order["id"], cover_json=order["cover_json"])
    render_files(order, resume)
    db.update(order["id"], resume_json=resume.model_dump_json(), status="ready")
    return RedirectResponse(f"/order/{token}?saved=1", status_code=303)


@app.post("/order/{token}/template")
def change_template(token: str, template: str = Form(...)):
    """Re-renders the same content in another design; no AI call, so it doesn't use a regeneration."""
    order = load_order(token)
    if not editable(order) or not order["resume_json"] or template not in render.TEMPLATES:
        raise HTTPException(400, "Cannot change the design now")
    db.update(order["id"], template=template)
    order["template"] = template
    render_files(order, Resume.model_validate_json(order["resume_json"]))
    return RedirectResponse(f"/order/{token}?saved=1", status_code=303)


@app.post("/order/{token}/regenerate")
def regenerate(token: str, background: BackgroundTasks, instructions: str = Form(""), part: str = Form("resume")):
    order = load_order(token)
    if not editable(order) or order["regenerations"] >= config.MAX_REGENERATIONS:
        raise HTTPException(400, "No regenerations left for this order")
    if order["status"] not in ("ready", "failed"):
        return RedirectResponse(f"/order/{token}", status_code=303)
    db.update(order["id"], regenerations=order["regenerations"] + 1)
    part = part if part in ("linkedin", "pack") else "resume"
    start_generation(background, order["id"], instructions.strip()[:1000], part)
    return RedirectResponse(f"/order/{token}" + ("" if part == "resume" else "/" + part), status_code=303)


@app.get("/order/{token}/download/{kind}")
def download(token: str, kind: str, inline: int = 0):
    order = load_order(token)
    docx_path, pdf_path = output_paths(order)
    cover_docx, cover_pdf = cover_paths(order)
    if kind == "pack-docx" and order["pack_json"]:
        pack = json.loads(order["pack_json"])
        safe = re.sub(r"[^A-Za-z0-9]+", "_", f"{order['customer_name']} {product_of(order)['label']}").strip("_")
        out = order_dir(order["id"]) / f"{safe}.docx"
        render.build_pack(pack, out, order["customer_name"])
        return FileResponse(out, filename=out.name, headers={"Cache-Control": "no-store"},
                            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    path = {"docx": docx_path, "pdf": pdf_path, "cover-docx": cover_docx, "cover-pdf": cover_pdf}.get(kind)
    if not path or not path.exists():
        raise HTTPException(404, "File not found")
    is_pdf = kind.endswith("pdf")
    media = "application/pdf" if is_pdf else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    disposition = "inline" if inline and is_pdf else "attachment"
    return FileResponse(path, media_type=media, filename=path.name, content_disposition_type=disposition,
                        headers={"Cache-Control": "no-store"})


@app.get("/order/{token}/preview/{n}.png")
def preview(token: str, n: int):
    order = load_order(token)
    pages = sorted(order_dir(order["id"]).glob("preview-*.png"))
    if not 1 <= n <= len(pages):
        raise HTTPException(404)
    return FileResponse(pages[n - 1], media_type="image/png", headers={"Cache-Control": "no-store"})


# ------------------------------------------------------------------ admin

security = HTTPBasic()


def admin_auth(creds: HTTPBasicCredentials = Depends(security)):
    if not config.ADMIN_PASSWORD or not secrets.compare_digest(creds.password, config.ADMIN_PASSWORD):
        raise HTTPException(401, headers={"WWW-Authenticate": "Basic"})


@app.get("/admin", response_class=HTMLResponse, dependencies=[Depends(admin_auth)])
def admin(request: Request):
    orders = db.recent()
    for o in orders:
        o["label"] = product_of(o)["label"]
        o["extra"] = json.loads(o["extra_json"] or "{}")
    leads = db.enquiries(500)
    for e in leads:
        e["score"] = json.loads(e["details"]).get("score") if e["details"].startswith("{") else None
    return page(request, "admin.html", orders=orders, enquiries=leads)


@app.get("/admin/leads.csv", dependencies=[Depends(admin_auth)])
def leads_csv():
    import csv
    import io
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["received_utc", "type", "name", "email", "phone", "institution_or_target", "details"])
    for e in db.enquiries(100000):
        details = f"score {json.loads(e['details']).get('score')}" if e["details"].startswith("{") else e["details"]
        w.writerow([e["created_at"], e["kind"], e["name"], e["email"], e["phone"], e["org"], details])
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=leads.csv"})
