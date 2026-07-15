# validator.py

"""
Email permutation generation and validation engine.

Validation priority chain
--------------------------
1. Reacher  (self-hosted, reacher_url required)
   – Open-source Rust service hosted on Glitch.com (free, no CC) or any VPS.
   – Probes from a real datacenter IP → works for Google Workspace & Microsoft 365.
   – Unlimited, zero cost.  Setup: see setup_reacher.sh / GLITCH_SETUP.md.

2. Hunter.io Email Finder API  (hunter_key required)
   – Takes (first, last, domain) → best email + verification in 1 API call.
   – 25 free finds/month; no credit card needed.

3. ZeroBounce  (zerobounce_key required)
   – Verifies individual permutations concurrently (100 free credits/month, no CC).
   – app.zerobounce.net — free signup, paste key in Settings.

4. AbstractAPI Email Validation  (abstract_key required)
   – 100 free verifications/month, no CC.

5. SMTP probing  (no config needed, last-resort fallback)
   – Direct SMTP RCPT TO from the user's machine.
   – Blocked by Google/Microsoft on residential IPs; works for self-hosted mail.

Nothing in this module imports PySide6.
"""

from __future__ import annotations

import json
import random
import smtplib
import socket
import string
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed, Future
from dataclasses import dataclass
from enum import Enum
from typing import Callable

import dns.resolver


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

class VerificationStatus(str, Enum):
    VALID        = "Valid"
    INVALID      = "Invalid"
    CATCH_ALL    = "Catch-all"
    UNVERIFIABLE = "Unverifiable"
    UNKNOWN      = "Unknown"


@dataclass
class ValidationResult:
    email: str
    status: VerificationStatus
    detail: str


# ---------------------------------------------------------------------------
# Tuning constants
# ---------------------------------------------------------------------------

_FROM_ADDR       = "verify@gmail.com"
_CONNECT_TIMEOUT = 3
_CMD_TIMEOUT     = 2
_PORTS           = [25, 587]
_MX_LIMIT        = 3
_MAX_WORKERS     = 4
_HTTP_TIMEOUT    = 8   # seconds for API calls

# Several providers (Hunter.io especially) sit behind a WAF/CDN that blocks the
# default "Python-urllib/x.y" User-Agent with a 403 HTML page. Every outbound
# HTTP request must send a browser-like User-Agent to get through.
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def _http_get_json(url: str) -> dict:
    """GET a URL with the required headers and return parsed JSON."""
    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "User-Agent": _USER_AGENT,
    })
    with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
        return json.loads(resp.read())


# ---------------------------------------------------------------------------
# Permutation generation
# ---------------------------------------------------------------------------

def generate_permutations(first: str, last: str, domain: str) -> list[str]:
    """Return the 10 most common corporate email patterns."""
    f  = first.lower().strip()
    l  = last.lower().strip()
    fi = f[0] if f else ""
    li = l[0] if l else ""
    d  = domain.lower().strip()

    patterns = [
        f"{f}.{l}@{d}",
        f"{fi}{l}@{d}",
        f"{f}@{d}",
        f"{f}{l}@{d}",
        f"{f}{li}@{d}",
        f"{l}@{d}",
        f"{f}_{l}@{d}",
        f"{fi}.{l}@{d}",
        f"{l}.{f}@{d}",
        f"{l}{fi}@{d}",
    ]

    seen: set[str] = set()
    unique: list[str] = []
    for p in patterns:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    return unique[:10]


# ---------------------------------------------------------------------------
# DNS helpers (used by SMTP path)
# ---------------------------------------------------------------------------

def _get_mx_hosts(domain: str) -> list[str]:
    records = dns.resolver.resolve(domain, "MX")
    sorted_records = sorted(records, key=lambda r: r.preference)
    return [str(r.exchange).rstrip(".") for r in sorted_records[:_MX_LIMIT]]


# ---------------------------------------------------------------------------
# PATH 1 — Hunter.io Email Finder
# ---------------------------------------------------------------------------

def _validate_via_hunter(
    first: str,
    last: str,
    domain: str,
    api_key: str,
    log: Callable[[str], None] | None = None,
) -> ValidationResult | None:
    """
    Call Hunter.io's Email Finder endpoint.
    Returns a ValidationResult or None if no email could be found.
    Uses exactly 1 API credit.
    """
    def emit(msg: str) -> None:
        if log: log(msg)

    emit(f"[INFO] Hunter.io: searching for {first} {last} @ {domain}...")

    params = urllib.parse.urlencode({
        "domain":     domain,
        "first_name": first,
        "last_name":  last,
        "api_key":    api_key,
    })
    url = f"https://api.hunter.io/v2/email-finder?{params}"

    try:
        payload = _http_get_json(url)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        emit(f"[ERROR] Hunter.io HTTP {exc.code}: {body[:120]}")
        return None
    except Exception as exc:
        emit(f"[ERROR] Hunter.io request failed: {exc}")
        return None

    data       = payload.get("data") or {}
    email      = data.get("email")
    score      = data.get("score", 0)
    accept_all = data.get("accept_all", False)
    v_status   = (data.get("verification") or {}).get("status", "")

    if not email:
        emit("[INFO] Hunter.io: no email found for this person.")
        return None

    emit(f"[INFO] Hunter.io: {email}  score={score}  verification={v_status or 'n/a'}")

    if accept_all:
        return ValidationResult(
            email, VerificationStatus.CATCH_ALL,
            f"Hunter.io — accept-all domain (score {score})",
        )
    if v_status == "valid":
        return ValidationResult(
            email, VerificationStatus.VALID,
            f"Hunter.io verified valid (score {score})",
        )
    if v_status in ("invalid", "disposable"):
        return ValidationResult(
            email, VerificationStatus.INVALID,
            f"Hunter.io marked {v_status} (score {score})",
        )
    if score >= 70:
        return ValidationResult(
            email, VerificationStatus.VALID,
            f"Hunter.io high-confidence (score {score}, unverified)",
        )

    return ValidationResult(
        email, VerificationStatus.UNKNOWN,
        f"Hunter.io low-confidence (score {score})",
    )


# ---------------------------------------------------------------------------
# PATH 2 — ZeroBounce
# ---------------------------------------------------------------------------

def _check_zerobounce(email: str, api_key: str) -> tuple[VerificationStatus, str]:
    """
    Validate a single email via ZeroBounce v2 API.
    status values: valid | invalid | catch-all | unknown | spamtrap | abuse | do_not_mail
    """
    params = urllib.parse.urlencode({"api_key": api_key, "email": email, "ip_address": ""})
    url    = f"https://api.zerobounce.net/v2/validate?{params}"

    data = _http_get_json(url)

    status     = (data.get("status") or "unknown").lower()
    sub_status = data.get("sub_status", "")

    if status == "valid":
        return VerificationStatus.VALID, f"ZeroBounce valid (sub: {sub_status})"
    if status == "catch-all":
        return VerificationStatus.CATCH_ALL, "ZeroBounce catch-all domain"
    if status == "invalid":
        return VerificationStatus.INVALID, f"ZeroBounce invalid (sub: {sub_status})"
    return VerificationStatus.UNKNOWN, f"ZeroBounce {status}"


def _validate_via_zerobounce(
    first: str,
    last: str,
    domain: str,
    api_key: str,
    log: Callable[[str], None] | None = None,
) -> ValidationResult | None:
    """Verify all permutations concurrently via ZeroBounce."""
    def emit(msg: str) -> None:
        if log: log(msg)

    perms = generate_permutations(first, last, domain)
    emit(f"[INFO] ZeroBounce: verifying {len(perms)} permutations...")

    found: ValidationResult | None = None

    def _probe(email: str) -> tuple[str, VerificationStatus, str]:
        status, detail = _check_zerobounce(email, api_key)
        return email, status, detail

    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
        future_to_email: dict[Future, str] = {
            pool.submit(_probe, email): email for email in perms
        }
        for future in as_completed(future_to_email):
            email = future_to_email[future]
            try:
                _, status, detail = future.result()
            except Exception as exc:
                emit(f"[WARN] ZeroBounce error for {email}: {exc}")
                continue

            emit(f"[INFO] ZeroBounce {email} → {status.value}")

            if status in (VerificationStatus.VALID, VerificationStatus.CATCH_ALL):
                found = ValidationResult(email, status, detail)
                for f in future_to_email:
                    f.cancel()
                break

    if found:
        emit(f"[SUCCESS] ZeroBounce: {found.email} ({found.status.value})")
    else:
        emit("[INFO] ZeroBounce: no deliverable address found.")
    return found


# ---------------------------------------------------------------------------
# PATH 3 — Abstract Email Reputation
# ---------------------------------------------------------------------------
#
# NOTE: this uses Abstract's *Email Reputation* product (not "Email Validation"
# — they are separate APIs with separate keys and different response schemas).
# The Reputation API does a real-time MX + SMTP check from Abstract's datacenter
# IPs, so it works on Google Workspace / Microsoft 365 domains.
#
# Free tier is rate-limited to ~1 request/second, so permutations are probed
# SEQUENTIALLY (not concurrently) with a small delay and 429 back-off.

_ABSTRACT_RATE_DELAY = 1.1   # seconds between calls (free tier ~1/sec)


def _check_abstract(email: str, api_key: str) -> tuple[VerificationStatus, str]:
    """
    Check a single email via Abstract's Email Reputation API.
    Returns (VerificationStatus, detail_string).
    """
    params = urllib.parse.urlencode({"api_key": api_key, "email": email})
    url    = f"https://emailreputation.abstractapi.com/v1/?{params}"

    data = _http_get_json(url)

    deliver = data.get("email_deliverability") or {}
    quality = data.get("email_quality") or {}

    status      = (deliver.get("status") or "unknown").lower()
    detail_code = deliver.get("status_detail", "")
    is_catchall = quality.get("is_catchall", False)
    score       = quality.get("score", "?")

    if is_catchall:
        return VerificationStatus.CATCH_ALL, f"Abstract catch-all (score {score})"
    if status == "deliverable":
        return VerificationStatus.VALID, f"Abstract deliverable (score {score})"
    if status == "undeliverable":
        return VerificationStatus.INVALID, f"Abstract undeliverable ({detail_code})"
    return VerificationStatus.UNKNOWN, f"Abstract {status} (score {score})"


def _validate_via_abstract(
    first: str,
    last: str,
    domain: str,
    api_key: str,
    log: Callable[[str], None] | None = None,
) -> ValidationResult | None:
    """
    Verify permutations SEQUENTIALLY via Abstract Email Reputation, respecting
    the free-tier rate limit. Returns first VALID/CATCH_ALL result, or None.
    """
    def emit(msg: str) -> None:
        if log: log(msg)

    perms = generate_permutations(first, last, domain)
    emit(f"[INFO] Abstract Reputation: verifying up to {len(perms)} permutations "
         f"(rate-limited, ~1/sec)...")

    found: ValidationResult | None = None

    for i, email in enumerate(perms):
        # Simple 429 back-off: try once, on rate-limit wait and retry once more.
        for attempt in range(2):
            try:
                status, detail = _check_abstract(email, api_key)
                break
            except urllib.error.HTTPError as exc:
                if exc.code == 429 and attempt == 0:
                    emit(f"[WARN] Abstract rate-limited on {email}; backing off...")
                    time.sleep(_ABSTRACT_RATE_DELAY * 2)
                    continue
                emit(f"[WARN] Abstract HTTP {exc.code} for {email}")
                status, detail = VerificationStatus.UNKNOWN, f"HTTP {exc.code}"
                break
            except Exception as exc:
                emit(f"[WARN] Abstract error for {email}: {exc}")
                status, detail = VerificationStatus.UNKNOWN, str(exc)
                break

        emit(f"[INFO] Abstract {email} → {status.value}")

        if status in (VerificationStatus.VALID, VerificationStatus.CATCH_ALL):
            found = ValidationResult(email, status, detail)
            break

        # Space out remaining calls to stay under the rate limit
        if i < len(perms) - 1:
            time.sleep(_ABSTRACT_RATE_DELAY)

    if found:
        emit(f"[SUCCESS] Abstract: {found.email} ({found.status.value})")
    else:
        emit("[INFO] Abstract: no deliverable address found.")
    return found


# ---------------------------------------------------------------------------
# PATH 4 — Reacher (self-hosted, no API key needed beyond the URL)
# ---------------------------------------------------------------------------

def _check_reacher(email: str, endpoint: str) -> tuple[VerificationStatus, str]:
    """
    POST one email to a Reacher /v0/check_email endpoint.
    Returns (VerificationStatus, detail).

    Reacher response fields used:
      is_reachable  : "safe" | "risky" | "invalid" | "unknown"
      smtp.is_catch_all   : bool
      smtp.is_deliverable : bool
      smtp.is_disabled    : bool  (account exists but deactivated)
      smtp.has_full_inbox : bool
    """
    body = json.dumps({"to_email": email}).encode()
    req  = urllib.request.Request(
        endpoint,
        data=body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": _USER_AGENT,
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())

    is_reachable = data.get("is_reachable", "unknown")
    smtp         = data.get("smtp") or {}
    is_catch_all   = smtp.get("is_catch_all",   False)
    is_deliverable = smtp.get("is_deliverable",  False)
    is_disabled    = smtp.get("is_disabled",     False)

    if is_catch_all:
        return VerificationStatus.CATCH_ALL, "Reacher: catch-all domain"
    if is_reachable == "safe" or is_deliverable:
        return VerificationStatus.VALID, f"Reacher: {is_reachable}"
    if is_reachable == "risky":
        # Exists but has issue (full inbox, disabled). Still the right address.
        note = "disabled" if is_disabled else "risky"
        return VerificationStatus.VALID, f"Reacher: mailbox {note} — address exists"
    if is_reachable == "invalid":
        return VerificationStatus.INVALID, "Reacher: mailbox does not exist"
    return VerificationStatus.UNKNOWN, f"Reacher: {is_reachable}"


def _validate_via_reacher(
    first: str,
    last: str,
    domain: str,
    reacher_url: str,
    log: Callable[[str], None] | None = None,
) -> ValidationResult | None:
    """
    Probe all permutations concurrently against a self-hosted Reacher instance.
    Returns the first VALID or CATCH_ALL result, or None.
    """
    def emit(msg: str) -> None:
        if log: log(msg)

    perms    = generate_permutations(first, last, domain)
    endpoint = f"{reacher_url.rstrip('/')}/v0/check_email"
    emit(f"[INFO] Reacher: probing {len(perms)} permutations via {endpoint}...")

    found: ValidationResult | None = None

    def _probe(email: str) -> tuple[str, VerificationStatus, str]:
        status, detail = _check_reacher(email, endpoint)
        return email, status, detail

    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
        future_to_email: dict[Future, str] = {
            pool.submit(_probe, email): email for email in perms
        }

        for future in as_completed(future_to_email):
            email = future_to_email[future]
            try:
                _, status, detail = future.result()
            except Exception as exc:
                emit(f"[WARN] Reacher error for {email}: {exc}")
                continue

            emit(f"[INFO] Reacher {email} → {status.value}")

            if status in (VerificationStatus.VALID, VerificationStatus.CATCH_ALL):
                found = ValidationResult(email, status, detail)
                for f in future_to_email:
                    f.cancel()
                break
            elif status == VerificationStatus.INVALID:
                pass   # keep trying other permutations

    if found:
        emit(f"[SUCCESS] Reacher: {found.email} ({found.status.value})")
    else:
        emit("[INFO] Reacher: no deliverable address found.")
    return found


# ---------------------------------------------------------------------------
# PATH 5 — SMTP (last-resort fallback, no config needed)
# ---------------------------------------------------------------------------

def _random_fake_address(domain: str) -> str:
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=10))
    return f"zz_fake_{suffix}@{domain}"


def _try_open_smtp(mx_host: str, port: int) -> smtplib.SMTP | None:
    try:
        smtp = smtplib.SMTP(timeout=_CONNECT_TIMEOUT)
        smtp.connect(mx_host, port)
        smtp.sock.settimeout(_CMD_TIMEOUT)
        smtp.ehlo_or_helo_if_needed()
        smtp.mail(_FROM_ADDR)
        return smtp
    except Exception:
        return None


def _race_connect(mx_hosts: list[str]) -> smtplib.SMTP | None:
    """Try every MX × port combo in parallel; return first working connection."""
    combos = [(h, p) for h in mx_hosts for p in _PORTS]
    with ThreadPoolExecutor(max_workers=len(combos)) as pool:
        futures = {pool.submit(_try_open_smtp, h, p): (h, p) for h, p in combos}
        result: smtplib.SMTP | None = None
        for f in as_completed(futures):
            smtp = f.result()
            if smtp is not None and result is None:
                result = smtp
                for other in futures:
                    other.cancel()
    return result


def _probe_rcpt(mx_hosts: list[str], email: str) -> tuple[int, str]:
    smtp = _race_connect(mx_hosts)
    if smtp is None:
        raise ConnectionError("All MX hosts / ports unreachable")
    try:
        code, raw = smtp.rcpt(email)
        return code, raw.decode(errors="replace")
    finally:
        try:
            smtp.quit()
        except Exception:
            pass


def _validate_via_smtp(
    first: str,
    last: str,
    domain: str,
    log: Callable[[str], None] | None = None,
) -> ValidationResult | None:
    """SMTP RCPT TO probing — best-effort fallback when no API key is set."""
    def emit(msg: str) -> None:
        if log: log(msg)

    perms = generate_permutations(first, last, domain)

    emit(f"[INFO] SMTP: resolving MX for {domain}...")
    try:
        mx_hosts = _get_mx_hosts(domain)
    except Exception as exc:
        emit(f"[ERROR] MX lookup failed: {exc}")
        return None

    emit(f"[INFO] MX: {', '.join(mx_hosts)}")

    # Catch-all check
    emit("[INFO] SMTP: catch-all probe...")
    try:
        fake_code, _ = _probe_rcpt(mx_hosts, _random_fake_address(domain))
        if fake_code == 250:
            emit(f"[WARN] {domain} is catch-all.")
            return ValidationResult(perms[0], VerificationStatus.CATCH_ALL,
                                    "Domain accepts all addresses")
        emit("[INFO] Not catch-all.")
    except Exception as exc:
        emit(f"[WARN] Catch-all probe error: {exc}; continuing.")

    # Concurrent permutation probes
    emit(f"[INFO] SMTP: probing {len(perms)} permutations concurrently...")
    found: ValidationResult | None = None

    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
        future_to_email: dict[Future, str] = {
            pool.submit(_probe_rcpt, mx_hosts, email): email for email in perms
        }
        for future in as_completed(future_to_email):
            email = future_to_email[future]
            try:
                code, msg = future.result()
            except Exception as exc:
                emit(f"[WARN] SMTP probe error for {email}: {exc}")
                continue

            if code == 250:
                emit(f"[SUCCESS] SMTP 250 OK: {email}")
                found = ValidationResult(email, VerificationStatus.VALID, msg)
                for f in future_to_email:
                    f.cancel()
                break
            elif code == 550:
                emit(f"[INFO] SMTP 550 invalid: {email}")
            else:
                emit(f"[WARN] SMTP {code} for {email}")

    if found is None:
        emit("[INFO] SMTP: no valid address confirmed.")
    return found


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def find_valid_email(
    first: str,
    last: str,
    domain: str,
    log: Callable[[str], None] | None = None,
    reacher_url: str | None = None,
    hunter_key: str | None = None,
    zerobounce_key: str | None = None,
    abstract_key: str | None = None,
) -> ValidationResult | None:
    """
    Find and validate an email address using the best available method.

    Priority: Reacher → Hunter.io → ZeroBounce → AbstractAPI → SMTP
    Stack free tiers to maximise monthly capacity:
      Hunter  25/month  +  ZeroBounce 100/month  +  AbstractAPI 100/month  = 225 free/month
    """
    def emit(msg: str) -> None:
        if log: log(msg)

    if reacher_url:
        emit("[INFO] Validation method: Reacher (self-hosted)")
        return _validate_via_reacher(first, last, domain, reacher_url, log=log)

    if hunter_key:
        emit("[INFO] Validation method: Hunter.io Email Finder")
        return _validate_via_hunter(first, last, domain, hunter_key, log=log)

    if zerobounce_key:
        emit("[INFO] Validation method: ZeroBounce")
        return _validate_via_zerobounce(first, last, domain, zerobounce_key, log=log)

    if abstract_key:
        emit("[INFO] Validation method: AbstractAPI")
        return _validate_via_abstract(first, last, domain, abstract_key, log=log)

    emit("[INFO] Validation method: SMTP (no API key or Reacher URL configured)")
    emit("[HINT] Sign up free at zerobounce.net or hunter.io and add your key in Settings.")
    return _validate_via_smtp(first, last, domain, log=log)
