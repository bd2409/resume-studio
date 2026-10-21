"""Three-step tailoring pipeline: extract a fact bank, write the tailored resume, verify it.

Every step returns validated JSON (structured outputs), and the writer must cite the facts
behind each bullet so the verifier can reject anything not traceable to the customer's resumes.
"""
import base64
import json
import subprocess
import tempfile
from pathlib import Path

import anthropic
from docx import Document

from . import config, render
from .schemas import CoverLetter, LinkedInProfile, Pack, Draft, Profile, Resume, Verified

_client = None


def client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY, timeout=600, max_retries=3)
    return _client


# ---------------------------------------------------------------- reading uploads

def _docx_text(path):
    doc = Document(path)
    parts = [p.text for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                parts.append(" | ".join(dict.fromkeys(cells)))
    return "\n".join(parts)


def _convert_with_libreoffice(path, fmt):
    out_dir = tempfile.mkdtemp()
    with render._soffice_lock:
        subprocess.run(
            ["soffice", "--headless", "--convert-to", fmt, "--outdir", out_dir, str(path)],
            check=True, capture_output=True, timeout=120,
        )
    return next(Path(out_dir).glob(f"*.{fmt}"))


def resume_blocks(paths):
    """Turn uploaded files into Claude content blocks: PDFs as documents, Word files as text."""
    blocks = []
    for i, path in enumerate(paths, 1):
        path = Path(path)
        ext = path.suffix.lower()
        if ext in {".doc", ".rtf", ".odt"}:
            path, ext = _convert_with_libreoffice(path, "docx"), ".docx"
        if ext == ".pdf":
            data = base64.standard_b64encode(path.read_bytes()).decode()
            blocks.append({
                "type": "document",
                "source": {"type": "base64", "media_type": "application/pdf", "data": data},
                "title": f"Resume {i}",
            })
        elif ext == ".docx":
            blocks.append({"type": "text", "text": f"<resume index=\"{i}\">\n{_docx_text(path)}\n</resume>"})
        else:
            text = path.read_text(encoding="utf-8", errors="ignore")
            blocks.append({"type": "text", "text": f"<resume index=\"{i}\">\n{text}\n</resume>"})
    return blocks


# ---------------------------------------------------------------- prompts

EXTRACT_SYSTEM = """You are a meticulous resume analyst. You receive up to six resumes written by the same person over time. Build one complete, accurate fact bank of their career.

Rules:
- Record only what the resumes actually say. Never infer, embellish or round numbers.
- Merge the same job across resumes into one role. Keep the most complete and most recent wording of each achievement, and keep every distinct achievement.
- Keep every number, currency figure, percentage, team size, client name and tool exactly as written.
- Give each fact a short unique id (F1, F2, ...) across the whole profile.
- Header: take the most recent contact details. If a field is missing, use an empty string. The headline is the person's most recent title plus their core domain, in under 12 words.
- List any contradictions between resumes (dates, titles, figures) in conflicts."""

WRITE_SYSTEM = """You are a senior resume writer for Indian and global job markets. Customers pay for a resume that clearly beats what they could write themselves, so every line must earn its place.

You receive the candidate's fact bank (from their own resumes) and a target job description. Write a resume tailored to that job, in this fixed structure: header, PROFESSIONAL SUMMARY, KEY COMPETENCIES, PROFESSIONAL EXPERIENCE, EDUCATION, CERTIFICATIONS & RECOGNITIONS, ACHIEVEMENTS.

First, analyse the job: the target role, its must-have skills and the exact keywords an applicant tracking system will scan for.

Truthfulness (non-negotiable):
- Use only facts from the fact bank. Every experience bullet lists the fact ids it is based on.
- Never invent employers, titles, dates, degrees, certifications, tools, metrics, team sizes or results. Never change a number.
- You may reword, combine and reframe facts to show their relevance, and use the job's terminology where the underlying experience genuinely matches.
- If the job needs something the facts do not support, leave it out and add a gap note advising the customer, for example: "The role asks for Power BI. Your resumes don't mention it; add it only if you have used it."

Quality:
- Headline: target-role-aligned title plus 2 to 3 strengths, under 12 words, true to the candidate's level.
- Summary: 3 to 4 sentences, about 60 to 80 words. Years of experience, domain, 2 to 3 strongest quantified results relevant to this job, and what they bring to this role. No first person, no cliches ("results-driven", "dynamic", "go-getter", "passionate").
- Key competencies: 9 to 12 short items (2 to 4 words), ordered by relevance to the job, each backed by the fact bank, using the job's wording where accurate.
- Experience: most recent first. 4 to 6 bullets for the latest one or two relevant roles, 2 to 3 for older ones, 1 to 2 for roles over 10 years old. Order bullets by relevance to the job.
- Bullets: start with a strong, varied past-tense action verb (present tense for the current role), show scope, action and measurable result, one to two lines each. Where a bullet has a clear theme, start it with a short bold-style lead phrase followed by a colon, for example "Recurring payments: Launched ...". Use lead phrases on the main role's bullets only.
- Context: one short line on the company if known from the facts, else empty.
- Dates as "Mon YYYY - Mon YYYY" or "Mon YYYY - Present".
- Education: highest first, with grade if given.
- Certifications & recognitions: certifications and formal awards. Achievements: other standout accomplishments (awards, rankings, publications, talks, patents, notable projects) not already used as bullets. If there are none, use the strongest remaining facts rather than repeating bullets.
- Length: fits one page for under 5 years of experience, two pages at most otherwise.
- Indian conventions are fine (Rs, lakh, crore) when the source uses them. Use plain text only, no markdown."""

VERIFY_SYSTEM = """You are the quality checker for a paid resume-writing service. You receive the candidate's fact bank, the job description and a draft resume whose bullets cite fact ids. Return the final, corrected resume.

Check every line:
1. Truth: each claim, number, tool, title, date, employer and qualification must be supported by the fact bank. Remove or rewrite anything unsupported, including in the summary, headline and competencies. Numbers must match the source exactly.
2. Fit: the strongest job-relevant facts are used and ordered first; must-have keywords appear wherever they are honestly supported.
3. Writing: no repeated opening verbs within a role, no cliches, no first person, no filler, consistent tense and date format, no spelling or grammar errors, plain text only.
4. Format: sections complete; bullet counts and length follow the rules (one page under 5 years of experience, at most two pages otherwise).

List each correction you made. Keep the gap notes that still apply and add any new ones. Do not add anything that is not in the fact bank."""


COVER_SYSTEM = """You write cover letters for a paid resume service. You receive the candidate's fact bank, the job description (or just a target role) and their final tailored resume. Write a cover letter for this application.

Rules:
- 250 to 350 words in 3 or 4 paragraphs: why this role and company (only what the job description says about them), two or three of the most relevant quantified achievements, how they fit the must-have requirements, and a short confident close.
- Use only facts from the fact bank and the resume. Never invent experience, numbers, tools or knowledge of the company that is not in the job description.
- Specific, warm and professional. No cliches ("I am writing to express", "results-driven", "passionate"), no flattery, no repeating the resume line by line.
- Address the company by name only if the job description names it; otherwise use "Dear Hiring Manager,".
- Plain text only, no placeholders such as [Company]."""


LINKEDIN_SYSTEM = """You are a LinkedIn profile strategist who has helped thousands of professionals get found by recruiters. You receive the person's fact bank (from their own resumes) and the role they are targeting. Rewrite their LinkedIn profile.

Truthfulness (non-negotiable): use only facts from the fact bank. Never invent employers, titles, dates, numbers, tools or results.

Headline (max 220 characters): target role and level, 2 to 3 specialisms recruiters search for, and one proof point if it fits. Use " | " separators. No emojis, no "aspiring", no "open to work".
About (1,500 to 2,500 characters): written in first person, warm and confident. Open with a hook line about the value they create, then their story and focus, 3 to 5 quantified wins (can be a short list with "-" bullets), what they are looking for or how they help, and a closing line inviting contact. Weave in the keywords recruiters for the target role search for. Short paragraphs separated by blank lines.
Experience: for each role in the last 10 years, a description of 600 to 1,500 characters: one line of scope, then 3 to 5 achievement lines starting with "-". First person implied, no "I" at the start of every line.
Skills: 15 to 25, ordered by importance for the target role, each supported by the fact bank, using LinkedIn's standard skill names where possible.
Featured ideas, banner tagline and tips: specific to this person, practical, based on their real work.
Plain text only (no markdown asterisks or headings). Indian conventions (Rs, lakh, crore) are fine where the source uses them."""


PACK_RULES = """
Truthfulness (non-negotiable): every claim about the person must come from the fact bank. Never invent employers, titles, dates, numbers, tools, results or stories. If a strong answer needs something the fact bank does not show, say what kind of real example they should use instead of making one up.
Write for Indian and global job markets; Rs, lakh and crore are fine where relevant. Plain text only: no markdown asterisks, hashes or tables. Use '-' at the start of list lines and blank lines between paragraphs. Square-bracket placeholders are allowed only for things you cannot know, such as [Hiring manager's name] or [Company]."""

PACKS = {
    "interview": ("""You are an interview coach who has prepared thousands of candidates for interviews at Indian and global companies. You receive the candidate's fact bank (from their own resumes) and the job they are interviewing for. Write their interview prep pack.

Sections, in this order:
1. "Your 60-second introduction": one item, a natural spoken 'tell me about yourself' (130 to 170 words) aimed at this role, and a second item with a 30-second version.
2. "Questions you'll most likely be asked": 12 to 15 items. Mix role-specific and technical questions from the job's requirements, behavioural questions, and questions a sharp interviewer would ask about this resume (job changes, gaps, career switches, short stints). Each body is a model answer in their voice using STAR (Situation, Task, Action, Result) with their real numbers, 120 to 220 words, followed by a line starting 'Why this works:' with one sentence.
3. "Tricky questions and how to handle them": 4 to 6 items such as weaknesses, why leaving, salary expectations, gaps, notice period. Honest, specific answers.
4. "Questions to ask them": 6 to 8 thoughtful questions specific to this role, each with one line on why it impresses.
5. "Your proof points": 5 to 8 items, each a real achievement to keep ready, with the numbers, as a 2-line story.
6. "The day before": a practical checklist as one item.""", "medium"),
    "outreach": ("""You are a job-search strategist who writes outreach that actually gets replies. You receive the candidate's fact bank (from their own resumes) and the job or kind of role they want. Write their cold outreach pack.

Sections, in this order:
1. "Emails to hiring managers": 3 variants (direct ask, value-first, and a 'saw your post / company news' template), each with a subject line on the first line as 'Subject: ...', 90 to 140 words, with one specific proof point from their real work.
2. "LinkedIn connection notes": 5 notes under 300 characters each (hiring manager, recruiter, team member, alumni, someone who posted the job).
3. "Messages to recruiters": 2 messages (LinkedIn InMail and email), 70 to 120 words.
4. "Asking for a referral": 3 messages (ex-colleague, college alumnus, someone they don't know at the company).
5. "Follow-ups": 3 polite follow-ups (after no reply in 5 days, after applying, after an interview).
6. "How to use this pack": one item with practical steps: who to contact, how to find their emails and names, how many per day, when to send, how to track replies.
Keep every message short, human and specific; no grovelling, no 'I hope this email finds you well'.""", "medium"),
    "salary": ("""You are a salary negotiation coach for professionals in India and abroad. You receive the candidate's fact bank (from their own resumes), the role and the offer details they shared. Write their salary negotiation script.

Do not invent market salary data or claim to know what the company pays. Base the target on the numbers the candidate gave (current pay, offer, expectations, competing offers) and on their real leverage. If they gave no numbers, explain how to set the target and use clear placeholders like [your target CTC].

Sections, in this order:
1. "Your leverage": 4 to 6 items, each a real reason they are worth more (scarce skills, quantified results, competing offers or interviews they mentioned, notice period, timing).
2. "Your numbers": one item with the target to ask for, the minimum to accept, and the reasoning, using their figures (fixed vs variable, joining bonus, ESOPs, notice buyout).
3. "The phone call script": one item, word for word, from thanking them to making the ask and staying silent, then closing.
4. "The email counter-offer": one ready-to-send email with a subject line.
5. "If they say...": 6 to 8 items, each a common pushback (our best offer, budget is fixed, what is your current CTC, we pay as per band, decide by tomorrow, no joining bonus) with a calm reply.
6. "Beyond the base salary": 6 to 8 things they can negotiate instead or as well, with one line each on how to ask.
7. "Accepting well": one item with the acceptance email that confirms everything in writing.""", "medium"),
    "content": ("""You are a LinkedIn ghostwriter who builds personal brands for professionals. You receive the person's fact bank (from their own resumes) and the role or direction they want to be known for. Write their 30-day LinkedIn content kit.

Sections, in this order:
1. "Your content pillars": 3 or 4 items, each a theme they can credibly own based on their real work, with one line on why it attracts recruiters or clients.
2. "Ready-to-post posts": 12 items. Each title is the post's angle; each body is the full post, 150 to 260 words, starting with a strong one-line hook, short lines, one concrete lesson or story from their real experience (never invented), and a closing question. Mix formats: lessons learned, how-to, behind the scenes of a real project, a myth they disagree with, a career moment, a list post. No hashtag spam: at most 3 relevant hashtags at the end.
3. "Hooks to reuse": one item with 12 alternative hook lines.
4. "Your 30-day calendar": one item listing day by day which post to publish (3 posts a week) and what to do on the other days (comment on 5 posts in your field, update a section, reach out to 3 people).
5. "Growing reach": one item with practical tips on timing, comments, profile and Creator mode.""", "medium"),
}
PACK_DEFAULT_TITLES = {"interview": "Interview prep pack", "outreach": "Cold outreach pack",
                       "salary": "Salary negotiation script", "content": "LinkedIn content kit"}


def write_pack(kind: str, profile: Profile, job: str, details: str = "", instructions: str = ""):
    system, effort = PACKS[kind]
    extra = f"\n\n<details_from_candidate>\n{details}\n</details_from_candidate>" if details else ""
    extra += f"\n\n<customer_instructions>\n{instructions}\n</customer_instructions>" if instructions else ""
    return _call(
        system + "\n" + PACK_RULES,
        f"<fact_bank>\n{profile.model_dump_json(indent=1)}\n</fact_bank>\n\n<target>\n{job}\n</target>{extra}",
        Pack,
        effort=effort,
    )


def mock_pack(kind: str):
    return Pack(
        title=PACK_DEFAULT_TITLES.get(kind, "Your pack") + " (sample)",
        intro="This is sample content, shown because the AI is not connected yet. With the AI connected, every item is written from the customer's real resumes and target role.",
        sections=[
            {"heading": "First section", "intro": "How to use this section.",
             "items": [{"title": "Example item", "body": "Ready-to-use text appears here.\n\n- With list lines\n- And short paragraphs"},
                       {"title": "Another item", "body": "Each item has its own Copy button."}]},
            {"heading": "Second section", "intro": "",
             "items": [{"title": "One more", "body": "More sample content."}]},
        ],
    )


def job_brief(job_description: str, target_role: str = ""):
    """The job text the writer works from. Without a posting, the writer optimises for the target role in general."""
    if job_description.strip():
        return job_description
    role = target_role.strip() or "the candidate's current career direction"
    return (f"No specific job posting was provided. Target role: {role}. "
            "Improve the resume for this kind of role in general: infer the skills and keywords that typical postings "
            "for it in India require, and present the candidate's real experience as strongly as possible for it.")


def match_score(must_have, covered):
    """Share of the job's must-have keywords that the final resume covers."""
    must = {k.strip().lower() for k in must_have if k.strip()}
    have = {k.strip().lower() for k in covered}
    if not must:
        return None
    hit = must & have
    return {"covered": len(hit), "total": len(must), "percent": round(100 * len(hit) / len(must)),
            "missing": sorted(k for k in must_have if k.strip().lower() in must - hit)}


def _call(system, content, schema, effort):
    response = client().messages.parse(
        model=config.AI_MODEL,
        max_tokens=16000,
        system=system,
        output_config={"effort": effort},
        messages=[{"role": "user", "content": content}],
        output_format=schema,
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("The AI declined this request.")
    if response.stop_reason == "max_tokens" or response.parsed_output is None:
        raise RuntimeError("The AI response was incomplete.")
    return response.parsed_output


def extract_profile(paths):
    content = resume_blocks(paths) + [{
        "type": "text",
        "text": "Build the fact bank from the resumes above.",
    }]
    return _call(EXTRACT_SYSTEM, content, Profile, effort="medium")


def write_and_verify(profile: Profile, job_description: str, instructions: str = ""):
    """Returns (Resume, notes) where notes holds gap notes and corrections for the customer."""
    facts = profile.model_dump_json(indent=1)
    extra = f"\n\n<customer_instructions>\n{instructions}\n</customer_instructions>" if instructions else ""
    draft = _call(
        WRITE_SYSTEM,
        f"<fact_bank>\n{facts}\n</fact_bank>\n\n<job_description>\n{job_description}\n</job_description>{extra}",
        Draft,
        effort="high",
    )
    verified = _call(
        VERIFY_SYSTEM,
        f"<fact_bank>\n{facts}\n</fact_bank>\n\n<job_description>\n{job_description}\n</job_description>\n\n"
        f"<draft>\n{draft.model_dump_json(indent=1)}\n</draft>",
        Verified,
        effort="high",
    )
    notes = {
        "target_role": draft.target_role,
        "gap_notes": verified.gap_notes,
        "corrections": verified.corrections,
        "keyword_coverage": verified.keyword_coverage,
        "match": match_score(draft.must_have_keywords, verified.keyword_coverage),
        "conflicts": profile.conflicts,
    }
    return verified.resume, notes


def write_linkedin(profile: Profile, job: str, instructions: str = ""):
    extra = f"\n\n<customer_instructions>\n{instructions}\n</customer_instructions>" if instructions else ""
    return _call(
        LINKEDIN_SYSTEM,
        f"<fact_bank>\n{profile.model_dump_json(indent=1)}\n</fact_bank>\n\n<target>\n{job}\n</target>{extra}",
        LinkedInProfile,
        effort="high",
    )


def mock_linkedin():
    return LinkedInProfile(
        headline="Senior Product Manager | Payments & Fintech Platforms | Scaled UPI AutoPay to Rs 1,200 Cr | B2B SaaS",
        about=("This is sample content, shown because the AI is not connected yet.\n\n"
               "With the AI connected, this About section is written from the customer's real resumes, in first person, "
               "with their strongest quantified wins and the keywords recruiters search for."),
        experience=[{"company": "PayNova Technologies", "title": "Senior Product Manager",
                     "description": "Own merchant payments for 2M+ small businesses.\n- Launched UPI AutoPay and e-mandate flows, adding Rs 1,200 Cr in annual processed volume.\n- Cut merchant activation time from 5 days to 36 hours."}],
        skills=["Product Management", "Payments", "Fintech", "B2B SaaS", "Product Strategy", "SQL"],
        featured_ideas=["A short post on how UPI AutoPay was launched", "The Global Fintech Fest 2024 talk"],
        banner_tagline="Building payments that small businesses love",
        tips=["Add a professional photo with a plain background", "Turn on Creator mode and post weekly about payments"],
    )


def write_cover_letter(profile: Profile, job_description: str, resume: Resume):
    return _call(
        COVER_SYSTEM,
        f"<fact_bank>\n{profile.model_dump_json(indent=1)}\n</fact_bank>\n\n<job_description>\n{job_description}\n</job_description>\n\n"
        f"<resume>\n{resume.model_dump_json(indent=1)}\n</resume>",
        CoverLetter,
        effort="medium",
    )


# ---------------------------------------------------------------- mock mode for local testing

SAMPLE = Path(__file__).with_name("sample_resume.json")


def mock_generate():
    resume = Resume.model_validate(json.loads(SAMPLE.read_text()))
    notes = {
        "target_role": "Sample output (AI not connected)",
        "gap_notes": ["This is sample content. Set ANTHROPIC_API_KEY to generate real resumes."],
        "corrections": [],
        "keyword_coverage": [],
        "match": {"covered": 13, "total": 15, "percent": 87, "missing": ["Power BI", "Kafka"]},
        "conflicts": [],
    }
    return resume, notes


def mock_cover_letter(resume: Resume):
    return CoverLetter(
        greeting="Dear Hiring Manager,",
        paragraphs=[
            "This is a sample cover letter, shown because the AI is not connected yet.",
            f"With the AI connected, this letter is written from {resume.header.name}'s real experience and the job description, in 250 to 350 words.",
            "It highlights the most relevant achievements and closes with a short, confident note.",
        ],
        closing="Sincerely,",
    )
