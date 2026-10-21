import base64
import json
import logging
import re
import secrets
import shutil
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi import Depends

from . import ai, auth, config, db, mailer, payments, render
from .profile import PROFILE
from .schemas import Profile, Resume

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")

BASE = Path(__file__).parent
ALLOWED_EXT = {".pdf", ".docx", ".doc", ".rtf", ".odt", ".txt"}

app = FastAPI(title=config.SITE_NAME, docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=BASE / "templates")
templates.env.globals.update(cfg=config, year=datetime.now().year, me=PROFILE, resume_templates=render.TEMPLATES)

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


def render_files(order, resume: Resume):
    docx_path, _ = output_paths(order)
    template = order.get("template") or render.DEFAULT_TEMPLATE
    render.build(resume.model_dump(), docx_path, template)
    render.to_previews(render.to_pdf(docx_path))
    if order.get("cover_json"):
        cover_docx, _ = cover_paths(order)
        render.build_cover(resume.header.model_dump(), json.loads(order["cover_json"]), cover_docx, template,
                           datetime.now().strftime("%d %B %Y"))
        render.to_pdf(cover_docx)


# ------------------------------------------------------------------ generation

def product_of(order):
    return config.PRODUCTS.get(order.get("product") or "resume", config.PRODUCTS["resume"])


def run_generation(order_id, instructions="", part="all"):
    """part: "all" on first run, or "resume" / "linkedin" when the customer regenerates one deliverable."""
    with _generation_lock:
        if order_id in _running:
            return
        _running.add(order_id)
    try:
        order = db.get_by_id(order_id)
        product = product_of(order)
        do_resume = product["resume"] and part in ("all", "resume")
        do_linkedin = product["linkedin"] and part in ("all", "linkedin")
        first_time = not order["resume_json"] and not order["linkedin_json"]
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
        if updates:
            db.update(order_id, **updates)
        if do_resume:
            db.update(order_id, progress="Creating your Word and PDF files")
            render_files(db.get_by_id(order_id), resume)
            db.update(order_id, resume_json=resume.model_dump_json(), notes_json=json.dumps(notes))
        db.update(order_id, status="ready", progress="")
        if first_time:
            mailer.order_ready(db.get_by_id(order_id))
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
    "/faq": "faq.html",
    "/contact": "contact.html",
    "/terms": "terms.html",
    "/privacy": "privacy.html",
    "/refund-policy": "refund.html",
}


def _static_page(template):
    def handler(request: Request):
        return page(request, template)
    return handler


for _path, _template in STATIC_PAGES.items():
    app.add_api_route(_path, _static_page(_template), methods=["GET"], response_class=HTMLResponse)


PUBLIC_PAGES = ["/", "/resume", "/pricing", "/faq", "/contact", "/terms", "/privacy", "/refund-policy"]


@app.get("/robots.txt", response_class=PlainTextResponse)
def robots():
    return (
        "User-agent: *\n"
        "Disallow: /order/\n"
        "Disallow: /admin\n"
        "Disallow: /webhooks/\n"
        f"Sitemap: {config.SITE_URL}/sitemap.xml\n"
    )


@app.get("/sitemap.xml")
def sitemap():
    today = datetime.now(timezone.utc).date().isoformat()
    urls = "".join(
        f"<url><loc>{config.SITE_URL}{path}</loc><lastmod>{today}</lastmod>"
        f"<priority>{'1.0' if path in ('/', '/resume') else '0.5'}</priority></url>"
        for path in PUBLIC_PAGES
    )
    xml = f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>'
    return Response(xml, media_type="application/xml")


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
    return {"ok": True}


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
    resumes: list[UploadFile] = File(...),
):
    if template not in render.TEMPLATES:
        template = render.DEFAULT_TEMPLATE
    mode = "improve" if mode == "improve" else "tailor"
    if product not in ("resume", "linkedin", "bundle"):
        product = "resume"
    if mode == "improve":
        job_description = ""
    form = {"customer_name": customer_name, "email": email, "phone": phone, "job_description": job_description,
            "template": template, "mode": mode, "target_role": target_role, "product": product}
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
    if not resumes:
        return fail("Please upload at least one resume.")
    if len(resumes) > config.MAX_RESUMES:
        return fail(f"You can upload at most {config.MAX_RESUMES} resumes.")

    saved = []
    for f in resumes:
        ext = Path(f.filename).suffix.lower()
        if ext not in ALLOWED_EXT:
            return fail(f"{f.filename}: please upload PDF or Word files.")
        data = await f.read()
        if len(data) > config.MAX_FILE_MB * 1024 * 1024:
            return fail(f"{f.filename} is larger than {config.MAX_FILE_MB} MB.")
        saved.append((ext, data))

    order = db.create_order(customer_name.strip(), email.strip(), phone.strip(), job_description.strip(),
                            [], config.PRODUCTS[product]["price"] * 100)
    up = order_dir(order["id"]) / "uploads"
    up.mkdir(parents=True, exist_ok=True)
    names = []
    for i, (ext, data) in enumerate(saved, 1):
        name = f"resume_{i}{ext}"
        (up / name).write_bytes(data)
        names.append(name)
    db.update(order["id"], files_json=json.dumps(names), template=template, target_role=target_role.strip()[:120], product=product,
              user_email=current_user_email(request))
    return RedirectResponse(f"/order/{order['token']}", status_code=303)


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
    if status == "awaiting_payment":
        return page(request, "pay.html", order=order, cashfree=checkout_open(request), cf_mode=payments.mode(),
                    payment_failed=request.query_params.get("payment") == "failed",
                    dev_skip=config.DEV_SKIP_PAYMENT, file_count=len(json.loads(order["files_json"])),
                    product=product_of(order))
    if status in ("paid", "generating"):
        return page(request, "progress.html", order=order)
    if status == "failed" and not order["resume_json"] and not order["linkedin_json"]:
        return page(request, "failed.html", order=order)
    if not order["resume_json"]:
        return RedirectResponse(f"/order/{token}/linkedin", status_code=303)
    resume = Resume.model_validate_json(order["resume_json"])
    notes = json.loads(order["notes_json"] or "{}")
    previews = sorted(order_dir(order["id"]).glob("preview-*.png"))
    cover = json.loads(order["cover_json"]) if order["cover_json"] else None
    return page(request, "review.html", order=order, resume=resume, notes=notes, cover=cover,
                pages=len(previews),
                can_edit=editable(order),
                regen_left=max(0, config.MAX_REGENERATIONS - order["regenerations"]),
                version=int(time.time()), last_failed=status == "failed",
                product=product_of(order), has_linkedin=bool(order["linkedin_json"]))


@app.get("/order/{token}/linkedin", response_class=HTMLResponse)
def linkedin_page(request: Request, token: str):
    order = load_order(token)
    if not order["linkedin_json"] or order["status"] in ("awaiting_payment", "paid", "generating"):
        return RedirectResponse(f"/order/{token}", status_code=303)
    from .schemas import LinkedInProfile
    li = LinkedInProfile.model_validate_json(order["linkedin_json"])
    return page(request, "linkedin.html", order=order, li=li, product=product_of(order),
                can_edit=editable(order), regen_left=max(0, config.MAX_REGENERATIONS - order["regenerations"]),
                last_failed=order["status"] == "failed")


@app.post("/order/{token}/new-version")
def new_version(token: str, job_description: str = Form(...)):
    """A paid follow-up: same customer and fact bank, a new job description, a new resume and cover letter."""
    parent = load_order(token)
    if not parent["paid_at"]:
        raise HTTPException(400, "This order can't be used for a new version")
    if len(job_description.strip()) < 150:
        raise HTTPException(400, "Please paste the full job description")
    child = db.create_order(parent["customer_name"], parent["email"], parent["phone"], job_description.strip(),
                            [], config.PRICE_VERSION * 100)
    src, dst = order_dir(parent["id"]) / "uploads", order_dir(child["id"]) / "uploads"
    if src.exists():
        shutil.copytree(src, dst)
    db.update(child["id"], files_json=parent["files_json"], profile_json=parent["profile_json"],
              template=parent["template"], user_email=parent["user_email"], product="version",
              parent_id=parent["id"])
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
    part = "linkedin" if part == "linkedin" else "resume"
    start_generation(background, order["id"], instructions.strip()[:1000], part)
    return RedirectResponse(f"/order/{token}" + ("/linkedin" if part == "linkedin" else ""), status_code=303)


@app.get("/order/{token}/download/{kind}")
def download(token: str, kind: str, inline: int = 0):
    order = load_order(token)
    docx_path, pdf_path = output_paths(order)
    cover_docx, cover_pdf = cover_paths(order)
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
    return page(request, "admin.html", orders=db.recent())
