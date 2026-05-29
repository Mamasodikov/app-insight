"""AI-powered privacy policy analysis using Gemini."""

import asyncio
import json
import re
import httpx
from google import genai


async def analyze_privacy_policy(policy_url: str, app_name: str, api_key: str) -> dict:
    # Fetch the privacy policy page
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        resp = await client.get(policy_url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        })
        resp.raise_for_status()
        html = resp.text

    # Strip HTML tags to get plain text
    text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()

    if len(text) < 100:
        return {"error": "Could not extract privacy policy text", "score": 0}

    # Cap at ~8000 chars for token limits
    text = text[:8000]

    from datetime import date
    today = date.today().isoformat()

    prompt = f"""Analyze this privacy policy for the app "{app_name}".
Today's date is {today}.

PRIVACY POLICY TEXT:
{text}

Return a JSON object with EXACTLY these fields:
{{
  "score": <0-100, where 100 = very privacy-friendly, 0 = major red flags>,
  "grade": "<A/B/C/D/F>",
  "data_collected": ["<type 1>", "<type 2>", ...],
  "data_shared_with": ["<third party 1>", "<third party 2>", ...],
  "red_flags": ["<concern 1>", "<concern 2>", ...],
  "good_practices": ["<positive 1>", "<positive 2>", ...],
  "gdpr_compliant": <true/false/null if unclear>,
  "data_deletion_available": <true/false/null>,
  "children_data": "<'collects'/'does not collect'/'not mentioned'>",
  "tracking": ["<tracker/SDK 1>", "<tracker 2>", ...],
  "summary": "<2-3 sentence plain-language summary of what the policy says>",
  "recommendations": ["<recommendation 1>", "<recommendation 2>", ...]
}}

Rules:
- data_collected: max 10 most important types
- red_flags: max 6 most concerning
- good_practices: max 5
- tracking: list any mentioned analytics/ad SDKs
- recommendations: max 5, for the app developer
- Return ONLY valid JSON, no markdown"""

    client = genai.Client(api_key=api_key)
    response = await asyncio.to_thread(
        client.models.generate_content,
        model="gemini-2.5-flash",
        contents=prompt,
    )

    response_text = response.text.strip()
    response_text = re.sub(r'^```(?:json)?\s*\n?', '', response_text)
    response_text = re.sub(r'\n?```\s*$', '', response_text)

    data = json.loads(response_text.strip())
    data["policy_url"] = policy_url
    data["text_length"] = len(text)
    return data
