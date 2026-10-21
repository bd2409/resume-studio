"""Content for the personal home page. Edit this file to update the site.

Figures come from Bhargab's own resume. The two most recent in-house roles are described
by industry only, at Bhargab's request.
"""
import os

PROFILE = {
    "name": "Bhargab Das",
    "initials": "BD",
    "headline": "Marketing strategist for startups and growing brands",
    "hero_title": "I build marketing engines that help startups grow.",
    "tagline": "18+ years building brand, digital and growth engines for B2B and consumer businesses. From brand identity and websites to performance marketing and e-commerce, I set up the whole system and make it deliver.",
    "location": "Gurugram, India",
    "email": os.getenv("PROFILE_EMAIL", "bhargabdas247@gmail.com"),
    "photo": "/static/bhargab.jpg",
    "linkedin": "https://www.linkedin.com/in/bhargabdas/",
    "instagram": os.getenv("INSTAGRAM_URL", "https://instagram.com/bhargavmusic"),
    "stats": [
        {"value": "18+", "label": "Years in marketing and growth"},
        {"value": "60%", "label": "Brand visibility lift from a full rebrand"},
        {"value": "~50%", "label": "Lower cost per qualified lead"},
        {"value": "10%", "label": "Of revenue from an online store built from scratch"},
    ],
    "about": [
        "Most startups don't fail for lack of a good product. They struggle because nobody has built the engine that turns that product into a brand people trust and a steady flow of customers.",
        "That engine is what I build. I've owned marketing end to end, from brand story and positioning to websites, content, performance marketing, e-commerce and the reporting that shows what's working, often with lean teams and tight budgets, working directly with founders and CEOs.",
        "My work spans robotics and AI, data centre and cloud, consumer electricals, energy management and B2B services, with brands such as Havells and Schneider Electric, and a marketing services startup I co-founded.",
    ],
    "services": [
        {"icon": "⚙️", "title": "Marketing engine setup", "text": "The full system: positioning, channels, content calendar, lead flow, tools and reporting, built so your team can run it."},
        {"icon": "✨", "title": "Brand identity and brand story", "text": "Name, positioning, messaging and visual identity that make a young company look established and feel distinct."},
        {"icon": "🖥️", "title": "Website building", "text": "Fast, conversion-focused websites that explain what you do in seconds and turn visitors into leads or sales."},
        {"icon": "📦", "title": "Packaging", "text": "Packaging that stands out on the shelf and online, and carries your brand story to the customer's hands."},
        {"icon": "📈", "title": "Digital and performance marketing", "text": "SEO, paid search and social, content and email, run against cost-per-lead and revenue, not vanity metrics."},
        {"icon": "🛒", "title": "E-commerce", "text": "Setting up and scaling your online store and marketplace presence as a real revenue channel."},
        {"icon": "🧭", "title": "Go-to-market strategy", "text": "Who to target, what to say and where to win, for a launch, a new market or a new category."},
        {"icon": "🤝", "title": "Fractional marketing leadership", "text": "Senior marketing leadership for founders who need it before they need a full-time CMO."},
    ],
    "work": [
        {"sector": "Robotics and AI company", "title": "Rebrand and AI-driven demand engine",
         "points": ["Led a full enterprise rebrand from the ground up with a 4-person team", "Brand visibility up 60% and share of voice up 45%", "Cost per sales-qualified lead cut by about 50% with AI-driven performance marketing"]},
        {"sector": "Data centre and cloud company", "title": "Digital marketing engine and attribution",
         "points": ["Integrated paid, content, email and webinar campaigns lifted qualified pipeline by about 40%", "Built attribution models to sharpen spend and channel-level ROI", "Ran digital marketing and social commerce for a 20-client portfolio delivering about 20% of company revenue at about 50% margins"]},
        {"sector": "Havells (Crabtree), home automation", "title": "Category launch and e-commerce from scratch",
         "points": ["Brand, content and channel strategy for a new category launch, including its first TV commercial", "Captured 10% market share", "Built the online store and digital commerce channel from scratch to 10% of business revenue"]},
        {"sector": "Schneider Electric, energy management", "title": "Positioning and influencer programmes",
         "points": ["Market assessments and competitor benchmarking that shaped product positioning", "Built consultant and analyst programmes through 40+ technical seminars", "Tender wins up 25%"]},
        {"sector": "FindAgency, co-founded startup", "title": "Built a B2B marketing marketplace",
         "points": ["Co-founded India's first marketplace connecting marketers with B2B service providers", "Scaled to 10 enterprise clients", "Delivered 25 to 60% pipeline growth through brand, content and demand-generation advisory"]},
    ],
    "industries": ["Robotics and AI", "Cloud and data centre", "Home automation and IoT", "Building automation",
                   "Energy management", "Solar", "Fire and security", "Enterprise software"],
    "credentials": [
        "B.Tech, Malaviya National Institute of Technology (MNIT), Jaipur",
        "MBA, Symbiosis Institute of International Business, Pune",
        "Executive Programme in Strategic Marketing, IIM Lucknow",
        "Data Science, ML and AI, MIT",
        "Google Ads and Analytics certified",
        "LinkedIn Top Voice, B2B Marketing 2023",
    ],
    "music": "When I'm not building brands, I sing. Follow my music on Instagram.",
}
