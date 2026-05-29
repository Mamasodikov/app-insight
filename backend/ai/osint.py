"""OSINT: WHOIS + DNS + tech detection + subdomain enum."""

import asyncio
import socket
import ssl
import subprocess
import whois
import httpx
from datetime import datetime, timezone
from urllib.parse import urlparse


def _clean_domain(domain: str) -> str:
    parsed = urlparse(domain if "://" in domain else f"https://{domain}")
    clean = parsed.hostname or domain
    parts = clean.split(".")
    if len(parts) > 2:
        clean = ".".join(parts[-2:])
    return clean


async def whois_lookup(domain: str) -> dict:
    clean = _clean_domain(domain)

    def _lookup():
        try:
            w = whois.whois(clean)
            creation = w.creation_date[0] if isinstance(w.creation_date, list) else w.creation_date
            expiry = w.expiration_date[0] if isinstance(w.expiration_date, list) else w.expiration_date

            age_days = None
            if creation:
                try:
                    cd = creation if creation.tzinfo else creation.replace(tzinfo=timezone.utc)
                    age_days = (datetime.now(timezone.utc) - cd).days
                except Exception:
                    pass

            return {
                "domain": clean,
                "registrar": w.registrar,
                "creation_date": str(creation) if creation else None,
                "expiration_date": str(expiry) if expiry else None,
                "updated_date": str(w.updated_date[0] if isinstance(w.updated_date, list) else w.updated_date) if w.updated_date else None,
                "domain_age_days": age_days,
                "domain_age_years": round(age_days / 365.25, 1) if age_days else None,
                "name_servers": list(set(ns.lower().split()[0] for ns in w.name_servers)) if w.name_servers else [],
                "status": w.status if isinstance(w.status, list) else [w.status] if w.status else [],
                "org": w.org,
                "country": w.country,
                "state": w.state,
                "city": getattr(w, "city", None),
                "address": getattr(w, "address", None),
                "emails": list(set(w.emails)) if w.emails else [],
                "dnssec": getattr(w, "dnssec", None),
            }
        except Exception as e:
            return {"domain": clean, "error": str(e)}

    return await asyncio.get_running_loop().run_in_executor(None, _lookup)


async def dns_lookup(domain: str) -> dict:
    """Get DNS records using dig command."""
    clean = _clean_domain(domain)

    def _dig(record_type):
        try:
            result = subprocess.run(
                ["dig", "+short", clean, record_type],
                capture_output=True, text=True, timeout=5,
            )
            lines = [l.strip() for l in result.stdout.strip().split("\n") if l.strip()]
            return lines
        except Exception:
            return []

    def _run_all():
        return {
            "A": _dig("A"),
            "AAAA": _dig("AAAA"),
            "MX": _dig("MX"),
            "TXT": _dig("TXT"),
            "NS": _dig("NS"),
            "CNAME": _dig("CNAME"),
        }

    records = await asyncio.get_running_loop().run_in_executor(None, _run_all)

    # Detect hosting/email providers from records
    insights = []
    a_records = records.get("A", [])
    mx_records = " ".join(records.get("MX", [])).lower()
    txt_records = " ".join(records.get("TXT", [])).lower()
    ns_records = " ".join(records.get("NS", [])).lower()

    # Hosting detection from NS/A
    if "awsdns" in ns_records:
        insights.append("Hosted on AWS (Route 53)")
    elif "googledomains" in ns_records or "google" in ns_records:
        insights.append("DNS via Google Domains")
    elif "cloudflare" in ns_records:
        insights.append("Uses Cloudflare DNS/CDN")
    elif "yandexcloud" in ns_records or "yandex" in ns_records:
        insights.append("Hosted on Yandex Cloud")
    elif "webspace.uz" in ns_records:
        insights.append("Hosted on Webspace.uz (local UZ hosting)")

    # Email provider from MX
    if "google" in mx_records or "gmail" in mx_records:
        insights.append("Email: Google Workspace")
    elif "outlook" in mx_records or "microsoft" in mx_records:
        insights.append("Email: Microsoft 365")
    elif "yandex" in mx_records:
        insights.append("Email: Yandex Mail")
    elif "mail.ru" in mx_records:
        insights.append("Email: Mail.ru")
    elif mx_records:
        insights.append("Email: self-hosted or custom")

    # Security from TXT
    if "v=spf1" in txt_records:
        insights.append("SPF record configured")
    if "v=dmarc1" in txt_records:
        insights.append("DMARC configured")
    if "google-site-verification" in txt_records:
        insights.append("Google Search Console verified")
    if "facebook-domain-verification" in txt_records:
        insights.append("Facebook domain verified")

    return {"records": {k: v for k, v in records.items() if v}, "insights": insights}


async def ssl_info(domain: str) -> dict:
    """Get SSL certificate details."""
    clean = _clean_domain(domain)

    def _check():
        try:
            ctx = ssl.create_default_context()
            with socket.create_connection((clean, 443), timeout=5) as sock:
                with ctx.wrap_socket(sock, server_hostname=clean) as ssock:
                    cert = ssock.getpeercert()
                    subject = dict(x[0] for x in cert.get("subject", ()))
                    issuer = dict(x[0] for x in cert.get("issuer", ()))
                    sans = [entry[1] for entry in cert.get("subjectAltName", ()) if entry[0] == "DNS"]
                    return {
                        "subject": subject.get("commonName"),
                        "issuer": issuer.get("organizationName") or issuer.get("commonName"),
                        "org": subject.get("organizationName"),
                        "valid_from": cert.get("notBefore"),
                        "valid_until": cert.get("notAfter"),
                        "protocol": ssock.version(),
                        "alt_names": sans[:20],
                        "alt_names_count": len(sans),
                    }
        except Exception as e:
            return {"error": str(e)}

    return await asyncio.get_running_loop().run_in_executor(None, _check)


async def tech_detect(domain: str) -> dict:
    """Detect website technologies from HTTP response."""
    clean = _clean_domain(domain)
    techs = []

    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True, verify=False) as client:
            resp = await client.get(f"https://{clean}", headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            })
            headers = resp.headers
            body = resp.text[:5000].lower()

            # Server
            server = headers.get("server", "")
            if server:
                techs.append(f"Server: {server}")

            powered = headers.get("x-powered-by", "")
            if powered:
                techs.append(f"Runtime: {powered}")

            # Frameworks from HTML
            if "react" in body or "_next" in body or "__next" in body:
                techs.append("Frontend: React/Next.js")
            elif "vue" in body or "__vue" in body:
                techs.append("Frontend: Vue.js")
            elif "angular" in body:
                techs.append("Frontend: Angular")

            # Analytics & tools
            if "google-analytics" in body or "gtag" in body or "ga(" in body:
                techs.append("Analytics: Google Analytics")
            if "facebook.net/en_US/fbevents" in body or "fbq(" in body:
                techs.append("Analytics: Facebook Pixel")
            if "hotjar" in body:
                techs.append("Analytics: Hotjar")
            if "sentry" in body:
                techs.append("Monitoring: Sentry")
            if "intercom" in body:
                techs.append("Support: Intercom")
            if "crisp" in body:
                techs.append("Support: Crisp Chat")
            if "recaptcha" in body:
                techs.append("Security: reCAPTCHA")
            if "cloudflare" in body or "cf-ray" in headers:
                techs.append("CDN: Cloudflare")
            if "wordpress" in body or "wp-content" in body:
                techs.append("CMS: WordPress")

    except Exception:
        pass

    return {"technologies": techs}


async def enumerate_subdomains(domain: str) -> list[str]:
    clean = _clean_domain(domain)
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"https://crt.sh/?q=%.{clean}&output=json",
                headers={"User-Agent": "AppInsight/1.0"},
            )
            resp.raise_for_status()
            data = resp.json()

        subdomains = set()
        for entry in data:
            name = entry.get("name_value", "")
            for line in name.split("\n"):
                line = line.strip().lower()
                if line and "*" not in line and line.endswith(clean):
                    subdomains.add(line)
        return sorted(subdomains)
    except Exception:
        return []


async def full_domain_osint(domain: str) -> dict:
    whois_data, dns_data, ssl_data, tech_data, subdomains = await asyncio.gather(
        whois_lookup(domain),
        dns_lookup(domain),
        ssl_info(domain),
        tech_detect(domain),
        enumerate_subdomains(domain),
    )

    categories = {"api": [], "admin": [], "staging": [], "mail": [], "other": []}
    for sub in subdomains:
        if any(k in sub for k in ["api", "gateway", "backend"]):
            categories["api"].append(sub)
        elif any(k in sub for k in ["admin", "panel", "dashboard", "cms"]):
            categories["admin"].append(sub)
        elif any(k in sub for k in ["staging", "dev", "test", "beta", "sandbox"]):
            categories["staging"].append(sub)
        elif any(k in sub for k in ["mail", "smtp", "imap", "mx"]):
            categories["mail"].append(sub)
        else:
            categories["other"].append(sub)

    return {
        "whois": whois_data,
        "dns": dns_data,
        "ssl": ssl_data,
        "technologies": tech_data.get("technologies", []),
        "subdomains": subdomains,
        "subdomain_count": len(subdomains),
        "subdomain_categories": {k: v for k, v in categories.items() if v},
    }
