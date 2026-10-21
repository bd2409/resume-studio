"""Content for the personal home page. Edit this file to update the site.

Drafted from public summaries of linkedin.com/in/bhargabdas (LinkedIn itself can't be read
automatically); confirm titles and dates before launch.
"""
import os

PROFILE = {
    "name": "Bhargab Das",
    "initials": "BD",
    "headline": "Head of Global Marketing at Novus Hi-Tech",
    "tagline": "Marketing and sales leader with 18 years across B2B technology, robotics, electrical and cloud businesses.",
    "location": "Gurugram, India",
    "photo": os.getenv("PROFILE_PHOTO_URL", ""),  # e.g. /static/bhargab.jpg
    "linkedin": "https://www.linkedin.com/in/bhargabdas/",
    "instagram": os.getenv("INSTAGRAM_URL", ""),
    "about": [
        "I lead marketing for technology businesses, building the brand, demand and sales engines that take products to market in India and abroad.",
        "My career spans global marketing at Novus Hi-Tech, an AVP role at Cyfuture, heading sales and marketing at Havells, five years of marketing at Schneider Electric, and founding my own agency, Findagency. I started out in technology as a programmer analyst at Cognizant.",
        "Alongside my work, I help professionals present their careers well. Through my resume service, I turn your existing resumes into one tailored to the job you want.",
    ],
    "stats": [
        {"value": "18+", "label": "Years of experience"},
        {"value": "6", "label": "Organisations, including a startup I founded"},
        {"value": "IIM Lucknow", "label": "Executive programme in strategic marketing"},
    ],
    "experience": [
        {"company": "Novus Hi-Tech", "title": "Head of Global Marketing", "dates": "2023 - Present",
         "note": "Global marketing for an autonomous robotics and mobility technology company (formerly Hi-Tech Robotic Systemz)."},
        {"company": "Cyfuture India Pvt Ltd", "title": "Assistant Vice President", "dates": "2021 - 2023", "note": ""},
        {"company": "Findagency", "title": "Founder", "dates": "2019 - 2021", "note": ""},
        {"company": "Havells India Ltd", "title": "Sales and Marketing Head", "dates": "2016 - 2019", "note": ""},
        {"company": "Schneider Electric", "title": "Marketing Manager", "dates": "2011 - 2016", "note": ""},
        {"company": "Cognizant", "title": "Programmer Analyst", "dates": "", "note": ""},
    ],
    "education": [
        {"school": "Indian Institute of Management, Lucknow", "degree": "Executive Programme in Strategic Marketing for Business Success", "dates": "2022 - 2023"},
        {"school": "Symbiosis Institute of International Business", "degree": "MBA", "dates": "2009 - 2011"},
        {"school": "Malaviya National Institute of Technology, Jaipur", "degree": "", "dates": ""},
        {"school": "Cotton College", "degree": "", "dates": ""},
    ],
    "expertise": [
        "Brand and product marketing", "B2B demand generation", "Go-to-market strategy",
        "Sales leadership", "Digital marketing", "Channel and partner marketing",
        "Marketing for technology and robotics", "Agency building",
    ],
}
