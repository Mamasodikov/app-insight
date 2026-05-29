---
title: AppInsight
emoji: 📊
colorFrom: indigo
colorTo: purple
sdk: docker
app_port: 7860
pinned: false
---

# AppInsight — App Intelligence Platform

Full-stack app analytics platform for investors and startup accelerators.

## Features

- **Store Analytics** — Search Play Store & App Store across all countries, view ratings, downloads, reviews
- **AI Review Analysis** — Gemini-powered sentiment analysis, topic extraction, bug reports, feature requests
- **ASO Scoring** — App Store Optimization grade (A-F) with actionable improvement tips
- **App Comparison** — Side-by-side metrics for up to 5 apps
- **Permission Analysis** — Risk scoring for requested permissions (Camera, Location, Contacts)
- **Security Scanner** — Auto-pentest public endpoints (headers, SSL, CORS, rate limiting)
- **Privacy Policy AI** — AI analysis of privacy policies (GDPR, data collection, red flags)
- **Domain Intelligence** — WHOIS, DNS records, SSL certs, tech stack detection
- **Revenue Tracking** — Connect RevenueCat, Stripe, Click.uz, Uzum
- **PDF Export** — One-click investor-ready reports

## Setup

```bash
cp .env.example .env
# Add your free Gemini API key from https://aistudio.google.com
./run.sh
```

Open http://localhost:8000
