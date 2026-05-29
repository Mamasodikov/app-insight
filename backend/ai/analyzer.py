import json
import asyncio
import re
from google import genai
from backend.models import ReviewItem, ReviewAnalysis


async def analyze_reviews(
    reviews: list[ReviewItem],
    app_name: str = "the app",
    api_key: str = "",
) -> ReviewAnalysis:
    if not reviews:
        return ReviewAnalysis(
            total_reviews=0,
            avg_rating=0,
            sentiment={"positive": 0, "neutral": 0, "negative": 0},
            top_topics=[],
            feature_requests=[],
            bug_reports=[],
            highlights=[],
            lowlights=[],
            summary="No reviews to analyze.",
            recommendations=[],
        )

    avg_rating = sum(r.rating for r in reviews) / len(reviews)

    review_texts = []
    for r in reviews[:500]:
        review_texts.append(f"[{r.rating}/5] {r.text[:300]}")

    reviews_block = "\n---\n".join(review_texts)

    prompt = f"""Analyze these {len(reviews)} user reviews for "{app_name}".

REVIEWS:
{reviews_block}

Return a JSON object with EXACTLY these fields:
{{
  "sentiment": {{"positive": <percent 0-100>, "neutral": <percent 0-100>, "negative": <percent 0-100>}},
  "top_topics": [
    {{"topic": "<topic name>", "count": <approx mentions>, "sentiment": "positive|negative|mixed"}}
  ],
  "feature_requests": ["<request 1>", "<request 2>", ...],
  "bug_reports": ["<bug 1>", "<bug 2>", ...],
  "highlights": ["<best quote 1>", "<best quote 2>", ...],
  "lowlights": ["<worst quote 1>", "<worst quote 2>", ...],
  "summary": "<2-3 sentence executive summary>",
  "recommendations": ["<actionable recommendation 1>", "<recommendation 2>", ...]
}}

Rules:
- top_topics: max 10, sorted by count descending
- feature_requests: max 8 most requested
- bug_reports: max 8 most reported
- highlights/lowlights: max 5 each, actual quotes from reviews
- recommendations: max 6, specific and actionable
- Return ONLY valid JSON, no markdown or explanation"""

    client = genai.Client(api_key=api_key)

    # Run sync Gemini call in thread pool to avoid blocking the event loop
    response = await asyncio.to_thread(
        client.models.generate_content,
        model="gemini-2.5-flash",
        contents=prompt,
    )

    response_text = response.text.strip()
    # Strip markdown code fences
    response_text = re.sub(r'^```(?:json)?\s*\n?', '', response_text)
    response_text = re.sub(r'\n?```\s*$', '', response_text)
    response_text = response_text.strip()

    data = json.loads(response_text)

    return ReviewAnalysis(
        total_reviews=len(reviews),
        avg_rating=round(avg_rating, 2),
        sentiment=data.get("sentiment", {}),
        top_topics=data.get("top_topics", []),
        feature_requests=data.get("feature_requests", []),
        bug_reports=data.get("bug_reports", []),
        highlights=data.get("highlights", []),
        lowlights=data.get("lowlights", []),
        summary=data.get("summary", ""),
        recommendations=data.get("recommendations", []),
    )
