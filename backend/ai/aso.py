"""ASO (App Store Optimization) scoring for app listings."""

import re
from backend.models import AppInfo


def score_aso(app: AppInfo) -> dict:
    scores = {}
    tips = []

    # 1. Title (max 20 pts)
    title = app.title or ""
    title_len = len(title)
    if 20 <= title_len <= 50:
        scores["title_length"] = 20
    elif 10 <= title_len < 20:
        scores["title_length"] = 15
        tips.append("Title is short — consider adding 1-2 keywords (aim for 20-50 chars)")
    elif title_len > 50:
        scores["title_length"] = 12
        tips.append("Title is too long — keep under 50 chars for readability")
    else:
        scores["title_length"] = 5
        tips.append("Title is very short — add descriptive keywords")

    # 2. Description (max 20 pts)
    desc = app.description or ""
    desc_len = len(desc)
    if desc_len >= 1000:
        scores["description"] = 20
    elif desc_len >= 500:
        scores["description"] = 15
        tips.append("Description could be longer — aim for 1000+ chars")
    elif desc_len >= 200:
        scores["description"] = 10
        tips.append("Description is thin — expand with features, benefits, and keywords")
    else:
        scores["description"] = 3
        tips.append("Description is too short — write at least 500 chars")

    # 3. Description formatting (max 10 pts)
    has_bullets = bool(re.search(r'[•\-\*✓✅🔥]', desc))
    has_sections = desc.count('\n\n') >= 2
    has_emoji = bool(re.search(r'[\U00010000-\U0010ffff]', desc))
    fmt_score = sum([has_bullets * 4, has_sections * 3, has_emoji * 3])
    scores["formatting"] = min(fmt_score, 10)
    if not has_bullets:
        tips.append("Add bullet points or list items to description for scannability")
    if not has_emoji:
        tips.append("Consider adding relevant emojis to description sections")

    # 4. Rating (max 15 pts)
    rating = app.rating or 0
    if rating >= 4.5:
        scores["rating"] = 15
    elif rating >= 4.0:
        scores["rating"] = 12
    elif rating >= 3.5:
        scores["rating"] = 8
        tips.append("Rating below 4.0 — prioritize fixing reported bugs")
    elif rating > 0:
        scores["rating"] = 4
        tips.append("Low rating hurts discoverability — address negative reviews urgently")
    else:
        scores["rating"] = 0
        tips.append("No rating data available")

    # 5. Reviews volume (max 10 pts)
    reviews = app.ratings_count or 0
    if reviews >= 10000:
        scores["review_volume"] = 10
    elif reviews >= 1000:
        scores["review_volume"] = 7
    elif reviews >= 100:
        scores["review_volume"] = 4
        tips.append("Low review count — encourage users to leave reviews")
    else:
        scores["review_volume"] = 1
        tips.append("Very few reviews — implement in-app review prompts")

    # 6. Installs (max 10 pts)
    installs_str = str(app.installs or "0").replace(",", "").replace("+", "")
    try:
        installs = int(installs_str)
    except ValueError:
        installs = 0
    if installs >= 1_000_000:
        scores["installs"] = 10
    elif installs >= 100_000:
        scores["installs"] = 7
    elif installs >= 10_000:
        scores["installs"] = 4
    else:
        scores["installs"] = 1

    # 7. Update recency (max 5 pts)
    if app.version:
        scores["update"] = 5
    else:
        scores["update"] = 0
        tips.append("No version info — ensure app is regularly updated")

    # 8. Localization (max 10 pts)
    has_local = bool(re.search(r'[^\x00-\x7F]', desc))
    has_english = bool(re.search(r'[a-zA-Z]{5,}', desc))
    if has_local and has_english:
        scores["localization"] = 10
    elif has_local or has_english:
        scores["localization"] = 6
        tips.append("Add both local language and English to description for broader reach")
    else:
        scores["localization"] = 2
        tips.append("Description has no clear language content")

    total = sum(scores.values())
    max_total = 100

    if total >= 85:
        grade = "A"
    elif total >= 70:
        grade = "B"
    elif total >= 55:
        grade = "C"
    elif total >= 40:
        grade = "D"
    else:
        grade = "F"

    return {
        "score": total,
        "max_score": max_total,
        "grade": grade,
        "breakdown": scores,
        "tips": tips,
    }
