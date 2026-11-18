"""Claude connector: a small remote MCP server at /mcp.

Stateless Streamable HTTP (JSON responses, no sessions, no sign-in). Two read-only tools:
- check_resume: score a pasted resume against a job description or target role.
- start_tailored_resume: a link to build the full tailored resume on the site.
Nothing the person pastes is stored; we only count checks per day (MCP_CHECKS_PER_DAY) to cap AI spend.
"""
import json
import logging
import urllib.parse

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response

from . import ai, config, db

log = logging.getLogger("mcp")
router = APIRouter()

PROTOCOL_VERSIONS = ["2025-11-25", "2025-06-18", "2025-03-26"]
MAX_RESUME = 30000
MAX_JOB = 15000


def _ref(source="claude"):
    return f"ref={source}"


def build_link(target_role="", has_job=False):
    params = {"mode": "tailor" if has_job or not target_role else "improve"}
    if target_role:
        params["target_role"] = target_role[:120]
    return f"{config.SITE_URL}/build?{urllib.parse.urlencode(params)}&{_ref()}"


TOOLS = [
    {
        "name": "check_resume",
        "title": "Check resume against a job",
        "description": (
            "Score a resume against a job description (or a target role) and return a 0-100 match score, "
            "the job keywords the resume shows and misses, its strengths, and the 3 fixes that would help most. "
            "Pass the resume as plain text. Use when someone asks how well their resume fits a job, "
            "what keywords they are missing, or how to improve their resume."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "resume_text": {"type": "string", "description": "The full resume as plain text."},
                "job_description": {"type": "string", "description": "The job posting text, if the person has one."},
                "target_role": {"type": "string", "description": "The role they are aiming for, if there is no job posting."},
            },
            "required": ["resume_text"],
        },
        "annotations": {"title": "Check resume against a job", "readOnlyHint": True, "destructiveHint": False,
                        "idempotentHint": False, "openWorldHint": False},
    },
    {
        "name": "start_tailored_resume",
        "title": "Start a tailored resume",
        "description": (
            "Get a link where the person can upload their resumes and a job description and receive a fully "
            "rewritten, job-tailored resume and cover letter in 4 designs, as editable Word and PDF files. "
            "Use when someone wants their resume rewritten or tailored, not just checked."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "target_role": {"type": "string", "description": "The role they are aiming for, to pre-fill the form."},
                "has_job_description": {"type": "boolean", "description": "True if they have a specific job posting."},
            },
        },
        "annotations": {"title": "Start a tailored resume", "readOnlyHint": True, "destructiveHint": False,
                        "idempotentHint": True, "openWorldHint": False},
    },
]

SERVER_INFO = {"name": "resume-studio", "title": "Resume Studio", "version": "1.0.0", "websiteUrl": f"{config.SITE_URL}/resume"}
INSTRUCTIONS = ("Resume Studio checks resumes against jobs and builds tailored resumes. Use check_resume for a quick score and fixes; "
                "use start_tailored_resume when the person wants the full rewrite.")


def _text_result(text, structured=None, is_error=False):
    out = {"content": [{"type": "text", "text": text}], "isError": is_error}
    if structured is not None:
        out["structuredContent"] = structured
    return out


def _format_check(r, link):
    lines = [f"Match score: {r.score}/100", "", r.verdict, ""]
    if r.strengths:
        lines += ["Strengths:"] + [f"- {s}" for s in r.strengths] + [""]
    if r.matched_keywords:
        lines += ["Keywords the resume already shows: " + ", ".join(r.matched_keywords), ""]
    if r.missing_keywords:
        lines += ["Keywords the job wants that the resume doesn't show: " + ", ".join(r.missing_keywords), ""]
    if r.top_fixes:
        lines += ["Top 3 fixes:"] + [f"{i}. {s}" for i, s in enumerate(r.top_fixes, 1)] + [""]
    lines.append(f"For a full rewrite tailored to this job (resume + cover letter, Word and PDF), the person can start here: {link}")
    return "\n".join(lines)


async def _check_resume(args):
    resume = str(args.get("resume_text") or "").strip()[:MAX_RESUME]
    job = str(args.get("job_description") or "").strip()[:MAX_JOB]
    role = str(args.get("target_role") or "").strip()[:120]
    if len(resume) < 200:
        return _text_result("Please pass the full resume text (at least a few lines of experience) as resume_text.", is_error=True)
    if db.leads_today("mcp-check") >= config.MCP_CHECKS_PER_DAY:
        return _text_result("Today's free checks are used up. Please try again tomorrow, or start a full tailored resume at "
                            + build_link(role, bool(job)), is_error=True)
    try:
        if config.AI_MODE == "mock":
            result = ai.mock_job_match_check()
        else:
            result = await run_in_threadpool(ai.job_match_check, resume, job, role)
    except Exception:
        log.exception("Connector resume check failed")
        return _text_result("Sorry, the check failed. Please try again in a minute.", is_error=True)
    # Count the check without keeping the resume or anything that identifies the person.
    db.add_enquiry("mcp-check", "", "", "", role, json.dumps({"score": result.score, "job": bool(job)}))
    link = build_link(role, bool(job))
    return _text_result(_format_check(result, link), structured={**result.model_dump(), "tailored_resume_link": link})


def _start_tailored(args):
    role = str(args.get("target_role") or "").strip()[:120]
    link = build_link(role, bool(args.get("has_job_description")))
    text = (f"The person can build a tailored resume here: {link}\n\n"
            "They upload up to 6 of their old resumes and paste the job description (or just give a target role). "
            "They get a rewritten resume in 4 designs, a matching cover letter and a job-match score, as editable Word and PDF files. "
            "The first resume and cover letter are free; after that it is Rs 500 per resume, one-time.")
    return _text_result(text, structured={"link": link})


def _error(msg_id, code, message):
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


async def _handle(msg):
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or "method" not in msg:
        return _error(msg.get("id") if isinstance(msg, dict) else None, -32600, "Invalid request")
    method, msg_id, params = msg["method"], msg.get("id"), msg.get("params") or {}
    if msg_id is None:  # notification, e.g. notifications/initialized
        return None
    if method == "initialize":
        asked = params.get("protocolVersion")
        version = asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
        return {"jsonrpc": "2.0", "id": msg_id, "result": {
            "protocolVersion": version, "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER_INFO, "instructions": INSTRUCTIONS}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": TOOLS}}
    if method == "tools/call":
        name, args = params.get("name"), params.get("arguments") or {}
        if name == "check_resume":
            return {"jsonrpc": "2.0", "id": msg_id, "result": await _check_resume(args)}
        if name == "start_tailored_resume":
            return {"jsonrpc": "2.0", "id": msg_id, "result": _start_tailored(args)}
        return _error(msg_id, -32602, f"Unknown tool: {name}")
    return _error(msg_id, -32601, f"Method not found: {method}")


@router.post("/mcp")
async def mcp_post(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(_error(None, -32700, "Parse error"), status_code=400)
    if isinstance(body, list):
        replies = [r for r in [await _handle(m) for m in body] if r is not None]
        return JSONResponse(replies) if replies else Response(status_code=202)
    reply = await _handle(body)
    return JSONResponse(reply) if reply is not None else Response(status_code=202)


@router.get("/mcp")
def mcp_get():
    # No server-to-client stream: this server only answers requests.
    return Response(status_code=405, headers={"Allow": "POST"})


@router.delete("/mcp")
def mcp_delete():
    return Response(status_code=405, headers={"Allow": "POST"})
