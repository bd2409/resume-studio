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
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi import Depends

from . import ai, config, db, mailer, payments, render
from .profile import PROFILE
from .schemas import Profile, Resume

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")

BASE = Path(__file__).parent
ALLOWED_EXT = {".pdf", ".docx", ".doc", ".rtf", ".odt", ".txt"}

app = FastAPI(title=config.SITE_NAME, docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=BASE / "templates")
templates.env.globals.update(cfg=config, year=datetime.now().year, me=PROFILE)

_generation_lock = threading.Lock()
_running = set()


# ------------------------------------------------------------------ helpers

def page(request, name, **ctx):
    return templates.TemplateResponse(request, name, ctx)


def order_dir(order_id):
    return config.FILES_DIR / order_id


def output_paths(order):
    safe = re.sub(r"[^A-Za-z0-9]+", "_", order["customer_name"]).strip("_") or "Resume"
    d = order_dir(order["id"])
    return d / f"{safe}_Resume.docx", d / f"{safe}_Resume.pdf"


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
    render.build(resume.model_dump(), docx_path)
    render.to_previews(render.to_pdf(docx_path))


# ------------------------------------------------------------------ generation

def run_generation(order_id, instructions=""):
    with _generation_lock:
        if order_id in _running:
            return
        _running.add(order_id)
    try:
        order = db.get_by_id(order_id)
        db.update(order_id, status="generating", error="", progress="Reading your resumes")
        if config.AI_MODE == "mock":
            time.sleep(2)
            resume, notes = ai.mock_generate()
            profile = None
        else:
            if order["profile_json"]:
                profile = Profile.model_validate_json(order["profile_json"])
            else:
                files = [order_dir(order_id) / "uploads" / f for f in json.loads(order["files_json"])]
                profile = ai.extract_profile(files)
                db.update(order_id, profile_json=profile.model_dump_json())
            db.update(order_id, progress="Writing and checking your tailored resume")
            resume, notes = ai.write_and_verify(profile, order["job_description"], instructions)
        db.update(order_id, progress="Creating your Word and PDF files")
        order = db.get_by_id(order_id)
        render_files(order, resume)
        first_time = not order["resume_json"]
        db.update(order_id, status="ready", progress="", resume_json=resume.model_dump_json(),
                  notes_json=json.dumps(notes))
        if first_time:
            mailer.order_ready(db.get_by_id(order_id))
    except Exception as exc:
        log.exception("Generation failed for %s", order_id)
        db.update(order_id, status="failed", progress="", error=str(exc)[:500])
    finally:
        with _generation_lock:
            _running.discard(order_id)


def start_generation(background: BackgroundTasks, order_id, instructions=""):
    db.update(order_id, status="generating", progress="Starting")
    background.add_task(run_generation, order_id, instructions)


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
    job_description: str = Form(...),
    consent: str = Form(None),
    resumes: list[UploadFile] = File(...),
):
    form = {"customer_name": customer_name, "email": email, "phone": phone, "job_description": job_description}
    resumes = [f for f in resumes if f.filename]

    def fail(msg):
        return page(request, "build.html", error=msg, form=form)

    if not consent:
        return fail("Please agree to the terms and privacy policy to continue.")
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email.strip()):
        return fail("Please enter a valid email address.")
    if len(re.sub(r"\D", "", phone)) < 10:
        return fail("Please enter a valid phone number.")
    if len(job_description.strip()) < 150:
        return fail("Please paste the full job description (at least a few lines).")
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
                            [], config.PRICE_RUPEES * 100)
    up = order_dir(order["id"]) / "uploads"
    up.mkdir(parents=True, exist_ok=True)
    names = []
    for i, (ext, data) in enumerate(saved, 1):
        name = f"resume_{i}{ext}"
        (up / name).write_bytes(data)
        names.append(name)
    db.update(order["id"], files_json=json.dumps(names))
    return RedirectResponse(f"/order/{order['token']}", status_code=303)


@app.get("/order/{token}", response_class=HTMLResponse)
def order_page(request: Request, token: str):
    order = load_order(token)
    status = order["status"]
    if status == "awaiting_payment":
        return page(request, "pay.html", order=order, razorpay=payments.enabled() and config.AI_MODE == "live",
                    dev_skip=config.DEV_SKIP_PAYMENT, file_count=len(json.loads(order["files_json"])))
    if status in ("paid", "generating"):
        return page(request, "progress.html", order=order)
    if status == "failed" and not order["resume_json"]:
        return page(request, "failed.html", order=order)
    resume = Resume.model_validate_json(order["resume_json"])
    notes = json.loads(order["notes_json"] or "{}")
    previews = sorted(order_dir(order["id"]).glob("preview-*.png"))
    return page(request, "review.html", order=order, resume=resume, notes=notes,
                pages=len(previews),
                can_edit=editable(order),
                regen_left=max(0, config.MAX_REGENERATIONS - order["regenerations"]),
                version=int(time.time()), last_failed=status == "failed")


@app.get("/order/{token}/status")
def order_status(token: str):
    order = load_order(token)
    return {"status": order["status"], "progress": order["progress"]}


@app.post("/order/{token}/checkout")
def checkout(token: str):
    order = load_order(token)
    if order["status"] != "awaiting_payment":
        return JSONResponse({"paid": True})
    if not payments.enabled() or config.AI_MODE != "live":
        # Never take money while the AI is not connected.
        raise HTTPException(400, "Payments are not configured")
    rzp_order_id = order["rzp_order_id"] or payments.create_order(order)
    db.update(order["id"], rzp_order_id=rzp_order_id)
    return {
        "key": config.RAZORPAY_KEY_ID,
        "order_id": rzp_order_id,
        "amount": order["amount_paise"],
        "name": config.SITE_NAME,
        "description": "Tailored resume (Word + PDF)",
        "prefill": {"name": order["customer_name"], "email": order["email"], "contact": order["phone"]},
    }


@app.post("/order/{token}/verify")
async def verify(token: str, request: Request, background: BackgroundTasks):
    order = load_order(token)
    body = await request.json()
    ok = (
        body.get("razorpay_order_id") == order["rzp_order_id"]
        and payments.verify_checkout(body.get("razorpay_order_id", ""), body.get("razorpay_payment_id", ""),
                                     body.get("razorpay_signature", ""))
    )
    if not ok:
        raise HTTPException(400, "Payment could not be verified")
    if db.mark_paid(order["id"], body["razorpay_payment_id"]):
        start_generation(background, order["id"])
    return {"ok": True}


@app.post("/order/{token}/dev-pay")
def dev_pay(token: str, background: BackgroundTasks):
    if not config.DEV_SKIP_PAYMENT:
        raise HTTPException(404)
    order = load_order(token)
    if db.mark_paid(order["id"], "dev_" + secrets.token_hex(4)):
        start_generation(background, order["id"])
    return RedirectResponse(f"/order/{token}", status_code=303)


@app.post("/webhooks/razorpay")
async def razorpay_webhook(request: Request, background: BackgroundTasks):
    raw = (await request.body()).decode()
    if not payments.verify_webhook(raw, request.headers.get("X-Razorpay-Signature", "")):
        raise HTTPException(400, "Bad signature")
    event = json.loads(raw)
    if event.get("event") in ("payment.captured", "order.paid"):
        payment = event["payload"]["payment"]["entity"]
        order = db.get_by_rzp_order(payment.get("order_id"))
        if order and payment.get("amount") == order["amount_paise"] and db.mark_paid(order["id"], payment["id"]):
            start_generation(background, order["id"])
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
    render_files(order, resume)
    db.update(order["id"], resume_json=resume.model_dump_json(), status="ready")
    return RedirectResponse(f"/order/{token}?saved=1", status_code=303)


@app.post("/order/{token}/regenerate")
def regenerate(token: str, background: BackgroundTasks, instructions: str = Form("")):
    order = load_order(token)
    if not editable(order) or order["regenerations"] >= config.MAX_REGENERATIONS:
        raise HTTPException(400, "No regenerations left for this order")
    if order["status"] not in ("ready", "failed"):
        return RedirectResponse(f"/order/{token}", status_code=303)
    db.update(order["id"], regenerations=order["regenerations"] + 1)
    start_generation(background, order["id"], instructions.strip()[:1000])
    return RedirectResponse(f"/order/{token}", status_code=303)


@app.get("/order/{token}/download/{kind}")
def download(token: str, kind: str, inline: int = 0):
    order = load_order(token)
    docx_path, pdf_path = output_paths(order)
    path = {"docx": docx_path, "pdf": pdf_path}.get(kind)
    if not path or not path.exists():
        raise HTTPException(404, "File not found")
    media = ("application/vnd.openxmlformats-officedocument.wordprocessingml.document"
             if kind == "docx" else "application/pdf")
    disposition = "inline" if inline and kind == "pdf" else "attachment"
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
