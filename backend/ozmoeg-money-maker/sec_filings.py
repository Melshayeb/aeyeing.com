#!/usr/bin/env python3
"""
OzMoEg Money Maker — SEC EDGAR filing fetcher.

Queries the SEC public EDGAR submissions API for recent filings of interest:
  S-1  : Registration Statement
  S-3  : Simplified Registration Statement
  424B*: Prospectus (424B1, 424B2, 424B3, 424B4, 424B5)
  8-K  : Current Report

Free, no API key required. The SEC requires:
  - a custom User-Agent header
  - requests are rate-limited to 10 per second
"""
import logging
import re
import time
from functools import lru_cache
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

# Required by SEC EDGAR API guidelines.
USER_AGENT = "elshayeb@gmail.com"

# Forms we surface on the website.
INTERESTING_FORMS = {"S-1", "S-3"}
PROSPECTUS_PREFIX = "424"
CURRENT_REPORT_FORM = "8-K"

# Keep requests well under the 10/sec SEC limit.
_MIN_REQUEST_INTERVAL = 0.15  # seconds
_last_request_time = 0.0


def _rate_limited_get(url: str, params: Optional[dict] = None) -> dict:
    """Make a rate-limited GET to the SEC API and return parsed JSON."""
    global _last_request_time
    now = time.time()
    wait = _last_request_time + _MIN_REQUEST_INTERVAL - now
    if wait > 0:
        time.sleep(wait)
    _last_request_time = time.time()

    headers = {"User-Agent": USER_AGENT}
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=20)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as e:
        logger.warning("SEC EDGAR request failed for %s: %s", url, e)
        return {}


def _cik_lookup_url(ticker: str) -> str:
    return f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={ticker}&output=json"


_TICKER_TO_CIK: Optional[Dict[str, str]] = None


def _load_ticker_cik_map() -> Dict[str, str]:
    """Load the SEC's bulk ticker-to-CIK mapping once per process."""
    global _TICKER_TO_CIK
    if _TICKER_TO_CIK is not None:
        return _TICKER_TO_CIK
    url = "https://www.sec.gov/files/company_tickers.json"
    data = _rate_limited_get(url)
    mapping = {}
    for entry in data.values() if isinstance(data, dict) else data or []:
        if isinstance(entry, dict):
            ticker = str(entry.get("ticker", "")).upper()
            cik = str(entry.get("cik_str", "")).zfill(10)
            if ticker and cik:
                mapping[ticker] = cik
    _TICKER_TO_CIK = mapping
    logger.info("Loaded SEC ticker-to-CIK map for %d tickers", len(mapping))
    return mapping


def get_cik(ticker: str) -> Optional[str]:
    """Resolve a ticker to its zero-padded 10-digit CIK via the SEC bulk mapping."""
    mapping = _load_ticker_cik_map()
    return mapping.get(str(ticker).upper())


def _submissions_url(cik: str) -> str:
    return f"https://data.sec.gov/submissions/CIK{cik}.json"


@lru_cache(maxsize=256)
def get_recent_filings(ticker: str, max_age_days: int = 90, max_results: int = 5) -> List[Dict]:
    """
    Return recent interesting SEC filings for a ticker.

    Each returned dict has:
      form: str       e.g. "S-1", "8-K"
      filed: str      ISO date, e.g. "2026-01-15"
      accession: str  e.g. "0001144209-26-000123"
      description: str short label for display
    """
    cik = get_cik(ticker)
    if not cik:
        return []

    data = _rate_limited_get(_submissions_url(cik))
    if not data:
        return []

    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accessions = recent.get("accessionNumber", [])
    descriptions = recent.get("primaryDocDescription", []) or recent.get("description", [])

    if not forms:
        return []

    cutoff = _days_ago_iso(max_age_days)
    matches = []
    for idx, form in enumerate(forms):
        if not form:
            continue
        form_upper = str(form).upper()
        if not _is_interesting_form(form_upper):
            continue
        filed = str(dates[idx]) if idx < len(dates) else ""
        if filed < cutoff:
            continue
        accession = str(accessions[idx]) if idx < len(accessions) else ""
        description = str(descriptions[idx]) if idx < len(descriptions) else ""
        matches.append({
            "form": form_upper,
            "filed": filed,
            "accession": accession,
            "description": _format_description(form_upper, description),
        })
        if len(matches) >= max_results:
            break

    return matches


def _is_interesting_form(form: str) -> bool:
    if form in INTERESTING_FORMS:
        return True
    if form == CURRENT_REPORT_FORM:
        return True
    if form.startswith(PROSPECTUS_PREFIX):
        return True
    return False


def _format_description(form: str, raw: str) -> str:
    if raw and raw.lower() not in {"none", "na", "n/a"}:
        # Keep it short for the badge tooltip.
        return raw[:80] + ("..." if len(raw) > 80 else "")
    if form.startswith("424"):
        return "Prospectus"
    if form == "8-K":
        return "Current Report"
    if form == "S-1":
        return "Registration Statement"
    if form == "S-3":
        return "Simplified Registration Statement"
    return form


def _days_ago_iso(days: int) -> str:
    from datetime import datetime, timedelta, timezone
    d = datetime.now(timezone.utc) - timedelta(days=days)
    return d.strftime("%Y-%m-%d")


def summarize_filings(ticker: str, max_age_days: int = 90, max_results: int = 3) -> str:
    """
    Return a compact string like 'S-1 (Jan 15), 8-K (Jan 10)' or empty string
    if no interesting filings exist.
    """
    filings = get_recent_filings(ticker, max_age_days=max_age_days, max_results=max_results)
    if not filings:
        return ""
    parts = []
    for f in filings:
        try:
            from datetime import datetime
            filed_short = datetime.strptime(f["filed"], "%Y-%m-%d").strftime("%b %d")
        except Exception:
            filed_short = f["filed"]
        parts.append(f"{f['form']} ({filed_short})")
    return ", ".join(parts)
