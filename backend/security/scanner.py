import asyncio
import ssl
import socket
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse
import httpx
from backend.models import SecurityFinding, SecurityReport


COMMON_PATHS = [
    "/admin", "/api", "/api/v1", "/api/v2", "/swagger", "/docs", "/redoc",
    "/graphql", "/graphiql", "/.env", "/.git/config", "/.git/HEAD",
    "/wp-admin", "/wp-login.php", "/phpmyadmin", "/adminer",
    "/robots.txt", "/sitemap.xml", "/crossdomain.xml",
    "/server-status", "/server-info", "/.well-known/security.txt",
    "/debug", "/trace", "/actuator", "/actuator/health", "/actuator/env",
    "/api/swagger.json", "/openapi.json", "/api-docs",
    "/backup", "/dump", "/database", "/config", "/configuration",
    "/.DS_Store", "/web.config", "/.htaccess", "/package.json",
    "/elmah.axd", "/console", "/druid", "/login", "/register", "/signup",
]

SECURITY_HEADERS = {
    "Strict-Transport-Security": {
        "severity": "high",
        "description": "HSTS header is missing. The site doesn't enforce HTTPS connections.",
        "recommendation": "Add 'Strict-Transport-Security: max-age=31536000; includeSubDomains' header.",
    },
    "Content-Security-Policy": {
        "severity": "medium",
        "description": "CSP header is missing. The site is vulnerable to XSS attacks.",
        "recommendation": "Implement a Content-Security-Policy header with appropriate directives.",
    },
    "X-Content-Type-Options": {
        "severity": "medium",
        "description": "X-Content-Type-Options header is missing. Browser may MIME-sniff responses.",
        "recommendation": "Add 'X-Content-Type-Options: nosniff' header.",
    },
    "X-Frame-Options": {
        "severity": "medium",
        "description": "X-Frame-Options header is missing. The site may be vulnerable to clickjacking.",
        "recommendation": "Add 'X-Frame-Options: DENY' or 'SAMEORIGIN' header.",
    },
    "Referrer-Policy": {
        "severity": "low",
        "description": "Referrer-Policy header is missing. Full URL may be sent in Referer header.",
        "recommendation": "Add 'Referrer-Policy: strict-origin-when-cross-origin' header.",
    },
    "Permissions-Policy": {
        "severity": "low",
        "description": "Permissions-Policy header is missing. Browser features are not restricted.",
        "recommendation": "Add Permissions-Policy header to restrict camera, microphone, geolocation, etc.",
    },
}


async def scan_target(target_url: str) -> SecurityReport:
    scan_id = str(uuid.uuid4())[:8]
    started = datetime.utcnow().isoformat()
    findings: list[SecurityFinding] = []

    parsed = urlparse(target_url)
    if not parsed.scheme:
        target_url = f"https://{target_url}"
        parsed = urlparse(target_url)

    base_url = f"{parsed.scheme}://{parsed.netloc}"

    async with httpx.AsyncClient(
        timeout=15,
        follow_redirects=True,
        verify=False,
        headers={"User-Agent": "AppInsight-SecurityScanner/1.0"},
    ) as client:
        # 1. Basic connectivity & response headers
        try:
            resp = await client.get(base_url)
        except Exception as e:
            return SecurityReport(
                scan_id=scan_id,
                target=target_url,
                started_at=started,
                completed_at=datetime.utcnow().isoformat(),
                score=0,
                grade="F",
                findings=[SecurityFinding(
                    severity="critical",
                    category="connectivity",
                    title="Target Unreachable",
                    description=f"Could not connect to {target_url}: {e}",
                    recommendation="Verify the target URL is correct and accessible.",
                )],
                summary={"total": 1, "critical": 1},
            )

        # 2. Check security headers
        header_findings = _check_headers(resp.headers)
        findings.extend(header_findings)

        # 3. Check information disclosure
        info_findings = _check_info_disclosure(resp.headers)
        findings.extend(info_findings)

        # 4. Check cookies
        cookie_findings = _check_cookies(resp.headers)
        findings.extend(cookie_findings)

        # 5. Check CORS
        cors_findings = await _check_cors(client, base_url)
        findings.extend(cors_findings)

        # 6. SSL/TLS check
        if parsed.scheme == "https":
            ssl_findings = await _check_ssl(parsed.hostname)
            findings.extend(ssl_findings)
        else:
            findings.append(SecurityFinding(
                severity="high",
                category="transport",
                title="No HTTPS",
                description="The target is not using HTTPS. All traffic is unencrypted.",
                recommendation="Enable HTTPS with a valid TLS certificate.",
            ))

        # 7. Endpoint discovery
        endpoint_findings = await _discover_endpoints(client, base_url)
        findings.extend(endpoint_findings)

        # 8. Rate limiting check
        rate_findings = await _check_rate_limiting(client, base_url)
        findings.extend(rate_findings)

        # 9. HTTP methods check
        method_findings = await _check_methods(client, base_url)
        findings.extend(method_findings)

    completed = datetime.utcnow().isoformat()

    # Calculate score
    severity_weights = {"critical": 25, "high": 15, "medium": 8, "low": 3, "info": 0}
    penalty = sum(severity_weights.get(f.severity, 0) for f in findings)
    score = max(0, 100 - penalty)

    if score >= 90:
        grade = "A"
    elif score >= 80:
        grade = "B"
    elif score >= 65:
        grade = "C"
    elif score >= 50:
        grade = "D"
    else:
        grade = "F"

    summary = {
        "total": len(findings),
        "critical": len([f for f in findings if f.severity == "critical"]),
        "high": len([f for f in findings if f.severity == "high"]),
        "medium": len([f for f in findings if f.severity == "medium"]),
        "low": len([f for f in findings if f.severity == "low"]),
        "info": len([f for f in findings if f.severity == "info"]),
    }

    return SecurityReport(
        scan_id=scan_id,
        target=target_url,
        started_at=started,
        completed_at=completed,
        score=score,
        grade=grade,
        findings=findings,
        summary=summary,
    )


def _check_headers(headers) -> list[SecurityFinding]:
    findings = []
    for header_name, info in SECURITY_HEADERS.items():
        if header_name.lower() not in {k.lower() for k in headers.keys()}:
            findings.append(SecurityFinding(
                severity=info["severity"],
                category="headers",
                title=f"Missing {header_name}",
                description=info["description"],
                recommendation=info["recommendation"],
            ))
    return findings


def _check_info_disclosure(headers) -> list[SecurityFinding]:
    findings = []
    server = headers.get("server", "")
    if server and any(v in server.lower() for v in ["apache", "nginx", "iis", "express"]):
        findings.append(SecurityFinding(
            severity="low",
            category="information_disclosure",
            title="Server Version Disclosed",
            description=f"Server header reveals: {server}",
            evidence=f"Server: {server}",
            recommendation="Remove or genericize the Server header.",
        ))

    powered_by = headers.get("x-powered-by", "")
    if powered_by:
        findings.append(SecurityFinding(
            severity="low",
            category="information_disclosure",
            title="Technology Stack Disclosed",
            description=f"X-Powered-By header reveals: {powered_by}",
            evidence=f"X-Powered-By: {powered_by}",
            recommendation="Remove the X-Powered-By header.",
        ))

    return findings


def _check_cookies(headers) -> list[SecurityFinding]:
    findings = []
    cookies = headers.get_list("set-cookie") if hasattr(headers, "get_list") else []
    if not cookies:
        raw = headers.get("set-cookie", "")
        if raw:
            cookies = [raw]

    for cookie in cookies:
        cl = cookie.lower()
        name = cookie.split("=")[0].strip()
        issues = []
        if "secure" not in cl:
            issues.append("Secure flag missing")
        if "httponly" not in cl:
            issues.append("HttpOnly flag missing")
        if "samesite" not in cl:
            issues.append("SameSite attribute missing")

        if issues:
            findings.append(SecurityFinding(
                severity="medium",
                category="cookies",
                title=f"Insecure Cookie: {name}",
                description=f"Cookie '{name}' has security issues: {', '.join(issues)}.",
                evidence=cookie[:200],
                recommendation="Set Secure, HttpOnly, and SameSite=Strict on all cookies.",
            ))

    return findings


async def _check_cors(client: httpx.AsyncClient, base_url: str) -> list[SecurityFinding]:
    findings = []
    try:
        resp = await client.options(base_url, headers={"Origin": "https://evil.com"})
        acao = resp.headers.get("access-control-allow-origin", "")
        acac = resp.headers.get("access-control-allow-credentials", "")

        if acao == "*":
            sev = "high" if acac.lower() == "true" else "medium"
            findings.append(SecurityFinding(
                severity=sev,
                category="cors",
                title="Wildcard CORS Policy",
                description="Access-Control-Allow-Origin is set to '*', allowing any origin.",
                evidence=f"ACAO: {acao}, ACAC: {acac}",
                recommendation="Restrict CORS to specific trusted origins.",
            ))
        elif "evil.com" in acao:
            findings.append(SecurityFinding(
                severity="critical",
                category="cors",
                title="CORS Origin Reflection",
                description="The server reflects arbitrary origins in Access-Control-Allow-Origin.",
                evidence=f"Sent Origin: https://evil.com, Got ACAO: {acao}",
                recommendation="Validate origins against a strict allowlist.",
            ))
    except Exception:
        pass
    return findings


async def _check_ssl(hostname: str) -> list[SecurityFinding]:
    findings = []

    def _ssl_check():
        result = []
        try:
            ctx = ssl.create_default_context()
            with socket.create_connection((hostname, 443), timeout=10) as sock:
                with ctx.wrap_socket(sock, server_hostname=hostname) as ssock:
                    cert = ssock.getpeercert()
                    protocol = ssock.version()

                    # Check expiry
                    not_after = ssl.cert_time_to_seconds(cert["notAfter"])
                    days_left = (not_after - time.time()) / 86400
                    if days_left < 30:
                        result.append(SecurityFinding(
                            severity="high" if days_left < 7 else "medium",
                            category="ssl",
                            title="Certificate Expiring Soon",
                            description=f"SSL certificate expires in {int(days_left)} days.",
                            evidence=f"Expires: {cert['notAfter']}",
                            recommendation="Renew the SSL certificate.",
                        ))

                    # Check protocol
                    if protocol in ("TLSv1", "TLSv1.1"):
                        result.append(SecurityFinding(
                            severity="high",
                            category="ssl",
                            title="Outdated TLS Version",
                            description=f"Server supports {protocol}, which is deprecated.",
                            evidence=f"Protocol: {protocol}",
                            recommendation="Disable TLS 1.0 and 1.1. Use TLS 1.2+ only.",
                        ))
        except ssl.SSLCertVerificationError as e:
            result.append(SecurityFinding(
                severity="critical",
                category="ssl",
                title="Invalid SSL Certificate",
                description=f"SSL certificate validation failed: {e}",
                recommendation="Install a valid SSL certificate from a trusted CA.",
            ))
        except Exception:
            pass
        return result

    loop = asyncio.get_running_loop()
    findings = await loop.run_in_executor(None, _ssl_check)
    return findings


async def _discover_endpoints(client: httpx.AsyncClient, base_url: str) -> list[SecurityFinding]:
    findings = []
    sensitive_found = []

    tasks = []
    for path in COMMON_PATHS:
        tasks.append(_probe_path(client, base_url, path))

    results = await asyncio.gather(*tasks, return_exceptions=True)
    for path, result in zip(COMMON_PATHS, results):
        if isinstance(result, Exception):
            continue
        status, length, snippet = result
        if status is None:
            continue

        if status == 200:
            is_sensitive = any(s in path for s in [".env", ".git", "config", "backup", "dump", "database", ".DS_Store", ".htaccess", "web.config", "package.json", "actuator/env"])
            if is_sensitive:
                findings.append(SecurityFinding(
                    severity="critical",
                    category="exposure",
                    title=f"Sensitive File Exposed: {path}",
                    description=f"Sensitive resource accessible at {path} (HTTP {status}, {length} bytes).",
                    evidence=snippet[:200] if snippet else None,
                    recommendation=f"Block public access to {path}.",
                ))
            elif any(s in path for s in ["/admin", "/phpmyadmin", "/adminer", "/console", "/druid"]):
                findings.append(SecurityFinding(
                    severity="high",
                    category="exposure",
                    title=f"Admin Interface Found: {path}",
                    description=f"Administrative interface accessible at {path}.",
                    recommendation="Restrict admin interfaces to internal networks or require VPN.",
                ))
            elif any(s in path for s in ["/swagger", "/docs", "/redoc", "/graphiql", "/api-docs", "swagger.json", "openapi.json"]):
                findings.append(SecurityFinding(
                    severity="medium",
                    category="exposure",
                    title=f"API Documentation Exposed: {path}",
                    description=f"API documentation is publicly accessible at {path}.",
                    recommendation="Restrict API documentation to authenticated users or internal networks.",
                ))
            else:
                sensitive_found.append(path)

    if sensitive_found:
        findings.append(SecurityFinding(
            severity="info",
            category="discovery",
            title="Accessible Endpoints Found",
            description=f"Found {len(sensitive_found)} accessible endpoints: {', '.join(sensitive_found[:10])}",
            recommendation="Review whether all discovered endpoints should be publicly accessible.",
        ))

    return findings


async def _probe_path(client: httpx.AsyncClient, base_url: str, path: str):
    try:
        resp = await client.get(f"{base_url}{path}", follow_redirects=False)
        text = resp.text[:500] if resp.status_code == 200 else ""
        return resp.status_code, len(resp.content), text
    except Exception:
        return None, 0, ""


async def _check_rate_limiting(client: httpx.AsyncClient, base_url: str) -> list[SecurityFinding]:
    findings = []
    try:
        statuses = []
        for _ in range(20):
            resp = await client.get(base_url)
            statuses.append(resp.status_code)

        if all(s == 200 for s in statuses):
            findings.append(SecurityFinding(
                severity="medium",
                category="rate_limiting",
                title="No Rate Limiting Detected",
                description="20 rapid requests all returned HTTP 200. No rate limiting appears to be in place.",
                recommendation="Implement rate limiting to prevent brute force and DoS attacks.",
            ))
    except Exception:
        pass
    return findings


async def _check_methods(client: httpx.AsyncClient, base_url: str) -> list[SecurityFinding]:
    findings = []
    dangerous_methods = ["PUT", "DELETE", "PATCH", "TRACE"]

    for method in dangerous_methods:
        try:
            resp = await client.request(method, base_url)
            if resp.status_code not in (405, 404, 501, 403):
                if method == "TRACE" and resp.status_code == 200:
                    findings.append(SecurityFinding(
                        severity="medium",
                        category="methods",
                        title="TRACE Method Enabled",
                        description="HTTP TRACE method is enabled, which can be used for XST attacks.",
                        evidence=f"TRACE {base_url} returned HTTP {resp.status_code}",
                        recommendation="Disable the TRACE HTTP method.",
                    ))
        except Exception:
            pass

    return findings
