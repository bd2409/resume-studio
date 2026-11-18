"""The Hidden Gem Test: a free 12-question quiz on Value (what you deliver) vs Visibility (how much people notice it).

Original framework for bhargabdas.in. Johari-style twist: friends can answer the same statements about you, and the
private results page shows where you and they agree or disagree.
"""

# Each statement: (axis, how the taker reads it, how a friend reads it about {n}).
QUESTIONS = [
    ("value", "I finish what I start, even when nobody is checking.",
     "{n} finishes what they start, even when nobody is checking."),
    ("visibility", "My manager or clients could name my top 3 wins without asking me.",
     "I could name {n}'s top 3 wins at work without asking them."),
    ("value", "People come to me when something is tricky or urgent.",
     "People go to {n} when something is tricky or urgent."),
    ("visibility", "In meetings I talk about results, not just how busy I've been.",
     "{n} talks about results, not just how busy they've been."),
    ("value", "In the last year my work saved real money, time or a deal.",
     "{n}'s work has saved real money, time or a deal."),
    ("visibility", "My LinkedIn profile and resume show numbers, not just duties.",
     "{n}'s LinkedIn profile shows what they've achieved, not just job titles."),
    ("value", "I fix problems even when they're outside my job description.",
     "{n} fixes problems even when they're outside their job description."),
    ("visibility", "People outside my team know what I'm good at.",
     "People outside {n}'s team know what they're good at."),
    ("value", "I pick up new tools and skills faster than most people around me.",
     "{n} picks up new tools and skills faster than most people."),
    ("visibility", "Someone recommended me for a role, project or deal in the last year.",
     "I would recommend {n} for a role, project or deal, and I have told people so."),
    ("value", "If I left tomorrow, my team would feel the gap within a week.",
     "If {n} left tomorrow, their team would feel the gap within a week."),
    ("visibility", "I share my ideas or work in public (posts, talks, demos) at least once a month.",
     "I regularly see {n} share ideas or work in public (posts, talks, demos)."),
]

CHOICES = ["Not really", "Sometimes", "Mostly", "Absolutely"]  # scored 1 to 4

TYPES = {
    "hidden-gem": {
        "emoji": "💎", "name": "The Hidden Gem", "tag": "You deliver far more than people see.",
        "share": "I'm a 💎 Hidden Gem: I deliver more than people see.",
        "color": "#2f6fd6",
        "about": "Your work is solid and people rely on you, but your value stays inside your team. Promotions, offers "
                 "and clients go to the people whose value is visible, so you are probably being underpaid or "
                 "overlooked for what you already do.",
        "strengths": ["Reliable, deep, the person people quietly depend on",
                      "Results that would impress a stranger, if they could see them"],
        "watch": "Your resume and LinkedIn likely list duties, not wins. A recruiter skimming for 7 seconds can't see what your team sees.",
        "next": ["Rewrite 3 bullets on your resume as numbers: what changed because of you",
                 "Post one 'here's what I learned' story on LinkedIn this week",
                 "Tell your manager your top 3 wins before your next review"],
    },
    "rising-star": {
        "emoji": "🚀", "name": "The Rising Star", "tag": "You do great work, and people know it.",
        "share": "I'm a 🚀 Rising Star: strong work, and people see it.",
        "color": "#1f7a4d",
        "about": "You deliver, and you make sure the right people know. That combination is rare. The risk now is "
                 "staying too long in a role that has stopped stretching you.",
        "strengths": ["Strong results with a clear story behind them",
                      "A network that knows what you're good at"],
        "watch": "Rising Stars plateau when they keep polishing the same role. Your next jump needs a resume aimed at the level above you.",
        "next": ["Aim your resume at the role one level up, not the one you have",
                 "Ask two people you've helped for a LinkedIn recommendation",
                 "Pick one bigger stage this quarter: a talk, an article, a cross-team project"],
    },
    "storyteller": {
        "emoji": "📣", "name": "The Storyteller", "tag": "People notice you. Now make the substance match.",
        "share": "I'm a 📣 Storyteller: people notice me, and I'm building the proof.",
        "color": "#c26a12",
        "about": "You're good at being seen: you speak up, share, and people remember you. That's a real skill many "
                 "people lack. Make sure the results keep up with the visibility, because interviews and due diligence "
                 "dig into proof.",
        "strengths": ["Confident, visible and well connected",
                      "Good at explaining ideas and rallying people"],
        "watch": "When visibility runs ahead of proof, the first deep interview question can expose it. Back every claim with a number.",
        "next": ["List 3 results you owned end to end, with numbers",
                 "Take on one hard, unglamorous problem and finish it",
                 "On your resume, swap adjectives for outcomes"],
    },
    "late-bloomer": {
        "emoji": "🌱", "name": "The Late Bloomer", "tag": "Your best chapter hasn't been written yet.",
        "share": "I'm a 🌱 Late Bloomer: my best chapter is coming.",
        "color": "#6b4fbf",
        "about": "Right now neither your impact nor your visibility is where it could be. That's common after a "
                 "layoff, a gap, a career switch or a role that doesn't fit. The good news: small, visible wins move "
                 "you fastest from here.",
        "strengths": ["Huge room to grow, and you were honest about it",
                      "Every small win will show up quickly"],
        "watch": "Waiting until you feel 'ready' keeps you stuck. Pick one skill and one visible win in the next 30 days.",
        "next": ["Pick one skill employers in your field ask for and learn it in 30 days",
                 "Fix your LinkedIn headline so it says what you do and for whom",
                 "Get a resume that shows your past wins clearly, even small ones"],
    },
}

THRESHOLD = 55  # percent on each axis to count as "high"


def _pct(scores):
    # 6 answers of 1..4 -> 0..100
    return round((sum(scores) - len(scores)) * 100 / (3 * len(scores))) if scores else 0


def score(answers):
    """answers: list of 12 ints 1..4 -> (value %, visibility %, type key)."""
    value = _pct([a for a, q in zip(answers, QUESTIONS) if q[0] == "value"])
    vis = _pct([a for a, q in zip(answers, QUESTIONS) if q[0] == "visibility"])
    hi_v, hi_s = value >= THRESHOLD, vis >= THRESHOLD
    kind = "rising-star" if hi_v and hi_s else "hidden-gem" if hi_v else "storyteller" if hi_s else "late-bloomer"
    return value, vis, kind


def valid(answers):
    return isinstance(answers, list) and len(answers) == len(QUESTIONS) and \
        all(isinstance(a, int) and 1 <= a <= 4 for a in answers)


def compare(self_answers, friend_answer_lists):
    """Johari-style comparison per statement: open, blind, hidden or untapped."""
    rows = {"open": [], "blind": [], "hidden": [], "untapped": []}
    for i, q in enumerate(QUESTIONS):
        avg = sum(f[i] for f in friend_answer_lists) / len(friend_answer_lists)
        me, them = self_answers[i] >= 3, avg >= 2.5
        key = "open" if me and them else "blind" if them else "hidden" if me else "untapped"
        rows[key].append(q[1])
    return rows
