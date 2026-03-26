"""Source validation: DNS, robots.txt, HTTPS checks."""

import socket
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx


def _extract_domain(url: str) -> str:
    """Extract domain from URL (hostname without scheme)."""
    parsed = urlparse(url)
    host = parsed.netloc or parsed.path
    if host.startswith("www."):
        return host
    return host


def check_dns(domain: str) -> bool:
    """Check if domain resolves. Returns True if resolvable."""
    try:
        socket.gethostbyname(domain)
        return True
    except (socket.gaierror, OSError):
        return False


def check_https(domain: str) -> bool:
    """Check if domain serves valid HTTPS. Returns True if HTTPS works."""
    url = f"https://{domain}/"
    try:
        with httpx.Client(timeout=5.0, follow_redirects=True) as client:
            resp = client.get(url)
            return resp.status_code < 500
    except Exception:
        return False


def check_robots_txt(domain: str, path: str = "/", user_agent: str = "NewsAggregator/1.0") -> bool:
    """Check if path allowed by robots.txt. True if allowed or unreachable."""
    rp = RobotFileParser()
    rp.set_url(f"https://{domain}/robots.txt")
    try:
        rp.read()
        return rp.can_fetch(user_agent, f"https://{domain}{path}")
    except Exception:
        return False  # If robots.txt unreachable, assume disallowed per discovery doc


def validate_source(domain: str) -> dict[str, bool | list[str]]:
    """Run validation checks on a source domain.

    Returns dict with: passed (bool), dns_ok, https_ok, robots_ok, errors (list).
    """
    errors: list[str] = []
    if not domain:
        errors.append("No domain provided")
        return {
            "passed": False,
            "dns_ok": False,
            "https_ok": False,
            "robots_ok": False,
            "errors": errors,
        }

    dns_ok = check_dns(domain)
    if not dns_ok:
        errors.append("DNS resolution failed")
        return {
            "passed": False,
            "dns_ok": False,
            "https_ok": False,
            "robots_ok": False,
            "errors": errors,
        }

    https_ok = check_https(domain)
    if not https_ok:
        errors.append("HTTPS check failed")

    robots_ok = check_robots_txt(domain)
    if not robots_ok:
        errors.append("robots.txt disallows crawling")

    passed = dns_ok and https_ok and robots_ok
    return {
        "passed": passed,
        "dns_ok": dns_ok,
        "https_ok": https_ok,
        "robots_ok": robots_ok,
        "errors": errors,
    }
