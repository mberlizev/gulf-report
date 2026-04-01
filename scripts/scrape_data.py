#!/usr/bin/env python3
"""
scrape_data.py — Collects daily UAE air defence data from open sources.

Sources (in priority order):
  1. Wikipedia "2026 Iranian strikes on the United Arab Emirates" — most complete log
  2. Gulf News / Khaleej Times / The National — confirm MOD figures
  3. Al Jazeera — regional context

Output: data/daily.json — structured daily data for update_html.py

Rashid's principle: fail gracefully. If a source is down, log it and continue.
"""

import json
import re
import sys
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

# Use only stdlib + requests + bs4 (minimal deps)
try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("ERROR: Install dependencies: pip install requests beautifulsoup4")
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M"
)
log = logging.getLogger("scrape")

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
DATA_FILE = DATA_DIR / "daily.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; GulfReportBot/1.0; +https://github.com/mberlizev/gulf-report)"
}

# The conflict started Feb 28 2026
START_DATE = datetime(2026, 2, 28)

# Wikipedia article — most structured running log
WIKI_URL = "https://en.wikipedia.org/wiki/2026_Iranian_strikes_on_the_United_Arab_Emirates"

# Search patterns for daily figures in Wikipedia narrative
# Pattern: "N ballistic missiles" / "N drones" / "N cruise missiles"
RE_BALLISTIC = re.compile(r'(\d+)\s*(?:ballistic\s*missiles?)', re.IGNORECASE)
RE_DRONES = re.compile(r'(\d+)\s*(?:drones?|UAVs?|Shahed)', re.IGNORECASE)
RE_CRUISE = re.compile(r'(\d+)\s*(?:cruise\s*missiles?)', re.IGNORECASE)
RE_KILLED = re.compile(r'(\d+)\s*(?:killed|dead|deaths?|fatalities)', re.IGNORECASE)
RE_INJURED = re.compile(r'(\d+)\s*(?:injured|wounded|hurt)', re.IGNORECASE)

# Date patterns in Wikipedia section headers and text
RE_DATE_HEADER = re.compile(
    r'(\d{1,2})\s*(January|February|March|April|May|June|July|August|September|October|November|December)\s*(\d{4})?',
    re.IGNORECASE
)

MONTH_MAP = {
    'january': 1, 'february': 2, 'march': 3, 'april': 4,
    'may': 5, 'june': 6, 'july': 7, 'august': 8,
    'september': 9, 'october': 10, 'november': 11, 'december': 12
}


def fetch_url(url: str, timeout: int = 30) -> Optional[str]:
    """Fetch URL content with error handling."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
        return resp.text
    except requests.RequestException as e:
        log.warning(f"Failed to fetch {url}: {e}")
        return None


def parse_wikipedia() -> dict:
    """
    Parse the Wikipedia article for daily attack data.
    Returns dict: { "2026-03-01": {"dr": N, "bm": N, "cm": N, "ck": N, "ci": N}, ... }
    """
    html = fetch_url(WIKI_URL)
    if not html:
        log.error("Wikipedia fetch failed")
        return {}

    soup = BeautifulSoup(html, "html.parser")

    # Remove references/citations to clean up text
    for ref in soup.find_all(["sup", "style", "script"]):
        ref.decompose()

    daily_data = {}
    current_date = None

    # Walk through all headings and paragraphs
    content = soup.find("div", {"id": "mw-content-text"})
    if not content:
        content = soup

    for el in content.find_all(["h2", "h3", "h4", "p", "li"]):
        text = el.get_text(strip=True)

        # Try to find date in headers
        date_match = RE_DATE_HEADER.search(text)
        if date_match and el.name in ("h2", "h3", "h4"):
            day = int(date_match.group(1))
            month_name = date_match.group(2).lower()
            year = int(date_match.group(3)) if date_match.group(3) else 2026
            month = MONTH_MAP.get(month_name, 0)
            if month:
                try:
                    current_date = datetime(year, month, day).strftime("%Y-%m-%d")
                except ValueError:
                    pass

        # Also check for inline dates in paragraphs
        if not current_date and date_match:
            day = int(date_match.group(1))
            month_name = date_match.group(2).lower()
            year = int(date_match.group(3)) if date_match.group(3) else 2026
            month = MONTH_MAP.get(month_name, 0)
            if month:
                try:
                    current_date = datetime(year, month, day).strftime("%Y-%m-%d")
                except ValueError:
                    pass

        if current_date and el.name in ("p", "li"):
            # Extract numbers from this paragraph
            bm_matches = RE_BALLISTIC.findall(text)
            dr_matches = RE_DRONES.findall(text)
            cm_matches = RE_CRUISE.findall(text)
            ck_matches = RE_KILLED.findall(text)
            ci_matches = RE_INJURED.findall(text)

            if bm_matches or dr_matches or cm_matches:
                if current_date not in daily_data:
                    daily_data[current_date] = {"dr": 0, "bm": 0, "cm": 0, "ck": None, "ci": None}

                # Take the largest number found (usually the daily total)
                if dr_matches:
                    daily_data[current_date]["dr"] = max(
                        daily_data[current_date]["dr"],
                        max(int(x) for x in dr_matches)
                    )
                if bm_matches:
                    daily_data[current_date]["bm"] = max(
                        daily_data[current_date]["bm"],
                        max(int(x) for x in bm_matches)
                    )
                if cm_matches:
                    daily_data[current_date]["cm"] = max(
                        daily_data[current_date]["cm"],
                        max(int(x) for x in cm_matches)
                    )

            # Casualty figures — these are cumulative in MOD statements
            if ck_matches:
                if current_date not in daily_data:
                    daily_data[current_date] = {"dr": 0, "bm": 0, "cm": 0, "ck": None, "ci": None}
                val = max(int(x) for x in ck_matches)
                if val < 500:  # sanity: not a launch count misread
                    daily_data[current_date]["ck"] = val

            if ci_matches:
                if current_date not in daily_data:
                    daily_data[current_date] = {"dr": 0, "bm": 0, "cm": 0, "ck": None, "ci": None}
                val = max(int(x) for x in ci_matches)
                if val < 5000:
                    daily_data[current_date]["ci"] = val

    log.info(f"Wikipedia: parsed {len(daily_data)} dated entries")
    return daily_data


def load_existing_data() -> dict:
    """Load existing daily.json if it exists."""
    if DATA_FILE.exists():
        try:
            with open(DATA_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            log.warning("Could not parse existing daily.json, starting fresh")
    return {"meta": {}, "days": {}}


def extract_existing_from_html() -> dict:
    """
    Extract the current data arrays from the HTML file as baseline.
    This is the authoritative source until we get new data from scraping.
    """
    html_file = REPO_ROOT / "uae_telegram.html"
    if not html_file.exists():
        return {}

    html = html_file.read_text(encoding="utf-8")

    def extract_array(var_name: str) -> list:
        pattern = rf"var\s+{var_name}\s*=\s*\[([\d,\s]+)\]"
        m = re.search(pattern, html)
        if m:
            return [int(x.strip()) for x in m.group(1).split(",") if x.strip()]
        return []

    dr = extract_array("DR")
    bm = extract_array("BM")
    cm = extract_array("CM")
    ck = extract_array("CK")
    ci = extract_array("CI")

    days = {}
    for i in range(len(dr)):
        date = (START_DATE + timedelta(days=i)).strftime("%Y-%m-%d")
        days[date] = {
            "dr": dr[i] if i < len(dr) else 0,
            "bm": bm[i] if i < len(bm) else 0,
            "cm": cm[i] if i < len(cm) else 0,
            "ck": ck[i] if i < len(ck) else None,
            "ci": ci[i] if i < len(ci) else None,
        }

    log.info(f"Extracted {len(days)} days from existing HTML")
    return days


def merge_data(existing: dict, scraped: dict, trust_existing_launches: bool = False) -> dict:
    """
    Merge scraped data into existing data.

    If trust_existing_launches=True, never overwrite DR/BM/CM for days that
    already exist (the HTML baseline is authoritative for launch counts).
    Wikipedia often cites cumulative totals that look like daily values.

    Casualty figures (CK/CI) can always be updated upward since they're cumulative.
    """
    merged = dict(existing)

    for date, vals in scraped.items():
        is_placeholder = (
            date in merged
            and merged[date].get("dr", 0) == 0
            and merged[date].get("bm", 0) == 0
            and merged[date].get("cm", 0) == 0
        )

        if date not in merged or is_placeholder:
            # New day or placeholder (all zeros) — add/update it
            # Sanity-check: Wikipedia cumulative totals can be 1000+; real daily max is ~400
            if vals.get("dr", 0) > 500 or vals.get("bm", 0) > 200:
                log.warning(f"Skipping suspicious day {date}: DR={vals.get('dr')} BM={vals.get('bm')} (likely cumulative)")
                continue
            if is_placeholder:
                merged[date].update(vals)
                log.info(f"FILLED placeholder: {date} — DR:{vals['dr']} BM:{vals['bm']} CM:{vals['cm']}")
            else:
                merged[date] = vals
                log.info(f"NEW day: {date} — DR:{vals['dr']} BM:{vals['bm']} CM:{vals['cm']}")
        else:
            old = merged[date]
            updated = False

            # Launch counts: only update if source is trusted
            if not trust_existing_launches:
                for key in ("dr", "bm", "cm"):
                    if vals.get(key) and vals[key] > old.get(key, 0):
                        # Sanity check: daily values shouldn't exceed reasonable max
                        if (key == "dr" and vals[key] > 500) or (key == "bm" and vals[key] > 200):
                            log.warning(f"Skipping suspicious {key}={vals[key]} for {date} (likely cumulative)")
                            continue
                        old[key] = vals[key]
                        updated = True
            else:
                # When trusting existing launches, do NOT fill in zeros from scraped data.
                # Wikipedia often cites cumulative totals ("19 cruise missiles total")
                # in the same paragraph as a specific date, making it look like a daily value.
                # Only add launch data for genuinely NEW days (handled above).
                pass

            # Casualties: always allow upward updates (cumulative)
            for key in ("ck", "ci"):
                if vals.get(key) is not None and (old.get(key) is None or vals[key] > old[key]):
                    old[key] = vals[key]
                    updated = True

            if updated:
                log.info(f"UPDATED day: {date}")

    return merged


def forward_fill_casualties(days: dict) -> dict:
    """
    Casualty figures (CK, CI) are cumulative — forward fill gaps.
    If a day has no casualty data, carry forward from the last known value.
    Also enforce monotonicity: if a scraped value is LOWER than the previous
    day's cumulative, it's a per-incident figure, not cumulative — discard it.
    """
    sorted_dates = sorted(days.keys())
    last_ck = 0
    last_ci = 0

    for date in sorted_dates:
        d = days[date]
        if d.get("ck") is not None and d["ck"] >= last_ck:
            last_ck = d["ck"]
        else:
            d["ck"] = last_ck
        if d.get("ci") is not None and d["ci"] >= last_ci:
            last_ci = d["ci"]
        else:
            d["ci"] = last_ci

    return days


def main():
    log.info("=== Gulf Report Data Scraper ===")

    # Step 1: Load baseline from existing HTML
    existing_days = extract_existing_from_html()

    # Step 2: Load any previously saved data
    saved = load_existing_data()
    if saved.get("days"):
        existing_days = merge_data(existing_days, saved["days"])

    # Step 3: Scrape Wikipedia
    wiki_data = parse_wikipedia()

    # Step 4: Merge — trust existing launch counts, only add new days or update casualties
    merged = merge_data(existing_days, wiki_data, trust_existing_launches=True)

    # Step 5: Forward-fill casualties
    merged = forward_fill_casualties(merged)

    # Step 6: Compute summary
    sorted_dates = sorted(merged.keys())
    total_dr = sum(merged[d]["dr"] for d in sorted_dates)
    total_bm = sum(merged[d]["bm"] for d in sorted_dates)
    total_cm = sum(merged[d]["cm"] for d in sorted_dates)
    total = total_dr + total_bm + total_cm
    last_date = sorted_dates[-1] if sorted_dates else "unknown"
    num_days = len(sorted_dates)

    last_ck = merged[last_date]["ck"] if last_date != "unknown" else 0
    last_ci = merged[last_date]["ci"] if last_date != "unknown" else 0

    meta = {
        "last_updated": datetime.utcnow().isoformat() + "Z",
        "last_date": last_date,
        "num_days": num_days,
        "total_launches": total,
        "total_dr": total_dr,
        "total_bm": total_bm,
        "total_cm": total_cm,
        "killed": last_ck,
        "injured": last_ci,
    }

    output = {"meta": meta, "days": merged}

    # Step 7: Save
    DATA_DIR.mkdir(exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    log.info(f"Saved {len(merged)} days to {DATA_FILE}")
    log.info(f"Summary: {num_days} days, {total} launches (DR:{total_dr} BM:{total_bm} CM:{total_cm})")
    log.info(f"Casualties: {last_ck} killed, {last_ci} injured")

    # Return non-zero if no data at all
    if not merged:
        log.error("No data collected!")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
