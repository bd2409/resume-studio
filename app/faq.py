"""FAQ page content, shared by the page and its FAQPage structured data."""
from . import config as c


def items():
    return [
        ("What do I need to get started?",
         f"At least one of your existing resumes (PDF or Word) and the job description you're applying for, or just the kind of role you want. Uploading several versions of your resume (up to {c.MAX_RESUMES}) helps us find more of your achievements."),
        ("How much does a professional resume cost?",
         f"A tailored resume with a matching cover letter costs Rs {c.PRICE_RUPEES}, paid once. There's no subscription. A LinkedIn makeover is Rs {c.PRICE_LINKEDIN}, and a resume + LinkedIn bundle is Rs {c.PRICE_BUNDLE:,}."),
        ("Will you add skills or experience I don't have?",
         "No. We only use facts from the resumes you upload. Every line is checked against them before you see it. If the job asks for something your resumes don't mention, we list it as a suggestion so you can add it yourself if it's true."),
        ("Is the resume ATS-friendly?",
         "Yes. Every design is a single-column layout with standard section headings and no tables, text boxes or graphics, so applicant tracking systems and job portals can read it correctly."),
        ("How long will my resume be?",
         "One page if you have under five years of experience, and never more than two pages otherwise. Older roles are kept short so your recent impact stands out."),
        ("How long does it take?",
         "Usually two to four minutes after payment. You'll see the progress on screen and we'll also email you a link."),
        ("What format will I get?",
         "An editable Microsoft Word (.docx) file and a PDF, in your choice of four designs. You can switch designs anytime for free."),
        ("Can I make changes?",
         f"Yes. You can edit any line on the review page for {c.EDIT_WINDOW_DAYS} days, and regenerate up to {c.MAX_REGENERATIONS} times with your own instructions, for example \"focus more on team leadership\". You can also edit the Word file anytime."),
        ("Do you help experienced professionals over 35 or 40?",
         "Yes. Our free age-proof resume check shows what may be dating your resume, and every resume we write focuses on your last 10 to 15 years of results in a modern two-page format."),
        ("Is my data safe?",
         f"Your files are used only to create your order. They're stored securely and deleted automatically after {c.RETENTION_DAYS} days. We never sell your data or use it for advertising."),
        ("Which payment methods do you accept?",
         "UPI, debit and credit cards, netbanking and popular wallets, processed securely by Cashfree Payments."),
        ("What if something goes wrong?",
         "If your resume can't be generated, we retry automatically. If it still fails, you get a full refund. See our refund policy, or contact us."),
        ("I'm applying to several jobs. Do I pay for each?",
         f"From your resume page you can order a new version for another job description for Rs {c.PRICE_VERSION}. We reuse your uploaded resumes and design, and you get a new tailored resume and cover letter."),
    ]
