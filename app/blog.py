"""Blog posts: Markdown files in app/content/blog with a small front-matter header.

Front matter (between --- lines), one "key: value" per line:
  title, description, date (YYYY-MM-DD), updated (optional), category, keywords,
  summary (the short direct answer shown first), takeaways (items separated by " | "),
  cta (resume, free-check, linkedin, interview, salary, claude, call, audit)
A "## Frequently asked questions" section with "### Question" headings becomes FAQ structured data.
"""
import re
from datetime import date
from pathlib import Path

import markdown

DIR = Path(__file__).parent / "content" / "blog"
FAQ_HEADING = "## Frequently asked questions"

CTAS = {
    "resume": ("Get a resume tailored to the job", "Upload your existing resumes and the job description. You get an ATS-friendly resume and cover letter, written only from your real experience.", "/build", "Build my resume"),
    "free-check": ("Free age-proof resume check", "See your score out of 100, what may be dating your resume, and the fixes, in about a minute.", "/free/resume-check", "Check my resume free"),
    "linkedin": ("Get your LinkedIn profile rewritten", "Headline, About, experience and skills, written from your real resume so recruiters find you.", "/build?product=linkedin", "Upgrade my LinkedIn"),
    "interview": ("Interview prep pack", "Likely questions for your target role with model answers built from your own experience.", "/build?product=interview", "Prepare me"),
    "salary": ("Salary negotiation script", "A word-for-word script and counter-offer email, built from your offer and your experience.", "/build?product=salary", "Get my script"),
    "claude": ("Learn Claude 1:1", "A 90-minute hands-on session: set up Claude and build a real project from your own work.", "/book/claude", "Book a session"),
    "call": ("1:1 career strategy call", "45 minutes with Bhargab on your next move, positioning and job search.", "/book/call", "Book a call"),
    "audit": ("Startup marketing audit", "A review of your brand, website, funnel and ads, with a written 90-day action plan.", "/book/audit", "Book an audit"),
}


def _parse(path):
    raw = path.read_text(encoding="utf-8")
    m = re.match(r"---\n(.*?)\n---\n(.*)", raw, re.S)
    if not m:
        raise ValueError(f"{path.name}: missing front matter")
    meta = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    body = m.group(2).strip()
    faqs = []
    if FAQ_HEADING in body:
        main, faq_md = body.split(FAQ_HEADING, 1)
        for block in re.split(r"\n### ", "\n" + faq_md.strip())[1:]:
            q, _, a = block.partition("\n")
            faqs.append({"q": q.strip(), "a": a.strip()})
        body_main = main.strip()
    else:
        body_main = body
    md = markdown.Markdown(extensions=["tables", "toc", "sane_lists"])
    html = md.convert(body_main)
    words = len(re.findall(r"\w+", body))
    published = date.fromisoformat(meta["date"])
    return {
        "slug": path.stem,
        "title": meta["title"],
        "description": meta["description"],
        "date": published,
        "updated": date.fromisoformat(meta.get("updated") or meta["date"]),
        "category": meta.get("category", "Careers"),
        "keywords": meta.get("keywords", ""),
        "summary": meta.get("summary", ""),
        "takeaways": [t.strip() for t in meta.get("takeaways", "").split("|") if t.strip()],
        "cta": CTAS.get(meta.get("cta", "resume"), CTAS["resume"]),
        "html": html,
        "toc": md.toc_tokens,
        "faqs": [{"q": f["q"], "a": f["a"], "a_html": markdown.markdown(f["a"])} for f in faqs],
        "minutes": max(2, round(words / 220)),
    }


def load():
    posts = [_parse(p) for p in sorted(DIR.glob("*.md"))]
    posts.sort(key=lambda p: (p["date"], p["title"]), reverse=True)
    return posts


POSTS = load()
BY_SLUG = {p["slug"]: p for p in POSTS}
