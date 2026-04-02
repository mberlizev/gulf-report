#!/usr/bin/env python3
"""
scrape_data.py — Collects daily UAE air defence data per DASHBOARD_RECIPE.md.

UPDATE PROCEDURE (Section 7):
  1. Search: UAE MOD missiles drones [today's date] intercepted
  2. Extract: daily BM, CM, DR counts from MOD statement
  3. Update arrays: append new day to DR[], BM[], CM[], CK[], CI[]

Sources (in priority order per recipe):
  1. MOD UAE — @modgovae on X/Twitter
  2. Gulf News — gulfnews.com
  3. The National — thenationalnews.com
  4. Khaleej Times — khaleejtimes.com
  5. Wikipedia — "2026 Iranian strikes on the United Arab Emirates"

Output: data/daily.json — structured daily data for update_html.py

Rashid's principle: fail gracefully. If a source is down, log it and continue.
"""

import json
import re
import sys
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, List, Tuple

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("ERROR: Install dependencies: pip install requests beautifulsoup4 lxml")
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
NEWS_FILE = DATA_DIR / "news.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}

# The conflict started Feb 28 2026
START_DATE = datetime(2026, 2, 28)

# === SOURCE URLs ===
WIKI_URL = "https://en.wikipedia.org/wiki/2026_Iranian_strikes_on_the_United_Arab_Emirates"

# News search URLs (we try Google News RSS as a free search proxy)
SEARCH_TEMPLATES = [
    "https://news.google.com/rss/search?q={query}&hl=en&gl=AE&ceid=AE:en",
]

# Direct source URLs for daily scraping
GULF_NEWS_URL = "https://gulfnews.com/uae"
NATIONAL_URL = "https://www.thenationalnews.com/uae/"
KHALEEJ_URL = "https://www.khaleejtimes.com/uae"

# === REGEX PATTERNS ===
RE_BALLISTIC = re.compile(r'(\d+)\s*(?:ballistic\s*missiles?)', re.IGNORECASE)
RE_DRONES = re.compile(r'(\d+)\s*(?:drones?|UAVs?|Shahed)', re.IGNORECASE)
RE_CRUISE = re.compile(r'(\d+)\s*(?:cruise\s*missiles?)', re.IGNORECASE)
RE_KILLED = re.compile(r'(\d+)\s*(?:killed|dead|deaths?|fatalities)', re.IGNORECASE)
RE_INJURED = re.compile(r'(\d+)\s*(?:injured|wounded|hurt)', re.IGNORECASE)
RE_INTERCEPTED = re.compile(r'(?:intercepted|shot\s*down|destroyed)\s*(\d+)', re.IGNORECASE)
RE_TOTAL_LAUNCHES = re.compile(r'(\d+)\s*(?:projectiles?|launches?|targets?|objects?)', re.IGNORECASE)
RE_CUMULATIVE_CONTEXT = re.compile(
    r'(?:total|cumulative|since|overall|to\s+date|so\s+far|all\s+told|combined|more\s+than)',
    re.IGNORECASE
)

RE_DATE_HEADER = re.compile(
    r'(\d{1,2})\s*(January|February|March|April|May|June|July|August|'
    r'September|October|November|December)\s*(\d{4})?',
    re.IGNORECASE
)

MONTH_MAP = {
    'january': 1, 'february': 2, 'march': 3, 'april': 4,
    'may': 5, 'june': 6, 'july': 7, 'august': 8,
    'september': 9, 'october': 10, 'november': 11, 'december': 12
}


def fetch_url(url, timeout=30):
    """Fetch URL content with error handling."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
        return resp.text
    except requests.RequestException as e:
        log.warning("Failed to fetch %s: %s", url, e)
        return None


def search_news(query, max_results=10):
    """
    Search for news articles using Google News RSS feed.
    Returns list of dicts: [{"title": ..., "link": ..., "source": ..., "date": ...}]
    """
    results = []
    encoded_query = requests.utils.quote(query)

    for template in SEARCH_TEMPLATES:
        url = template.format(query=encoded_query)
        xml = fetch_url(url)
        if not xml:
            continue

        soup = BeautifulSoup(xml, "xml")
        items = soup.find_all("item")

        for item in items[:max_results]:
            title = item.find("title")
            link = item.find("link")
            pub_date = item.find("pubDate")
            source_tag = item.find("source")

            results.append({
                "title": title.get_text(strip=True) if title else "",
                "link": link.get_text(strip=True) if link else "",
                "source": source_tag.get_text(strip=True) if source_tag else "",
                "date": pub_date.get_text(strip=True) if pub_date else "",
            })

        if results:
            break

    log.info("Search '%s': found %d results", query[:50], len(results))
    return results


def _filter_cumulative_matches(pattern, text):
    """
    Return only regex match values whose surrounding context (±80 chars)
    does NOT contain cumulative keywords like 'total', 'since', 'overall'.
    Falls back to all matches if every match is filtered out.
    """
    all_vals = []
    daily_vals = []
    for m in pattern.finditer(text):
        val = int(m.group(1))
        all_vals.append(val)
        start = max(0, m.start() - 80)
        end = min(len(text), m.end() + 80)
        window = text[start:end]
        if not RE_CUMULATIVE_CONTEXT.search(window):
            daily_vals.append(val)
    return daily_vals if daily_vals else all_vals


def extract_daily_figures_from_text(text):
    """
    Extract BM, DR, CM counts from a text block (MOD statement or article).
    Returns dict with keys: dr, bm, cm (or None if not found).

    Strategy: filter out numbers that appear near cumulative keywords,
    then take the MEDIAN of remaining matches (more robust than max,
    which often grabs weekly/cumulative totals).
    """
    figures = {"dr": None, "bm": None, "cm": None}

    dr_vals = _filter_cumulative_matches(RE_DRONES, text)
    bm_vals = _filter_cumulative_matches(RE_BALLISTIC, text)
    cm_vals = _filter_cumulative_matches(RE_CRUISE, text)

    def pick(vals, hard_cap):
        if not vals:
            return None
        vals = sorted(vals)
        # Use median — less sensitive to outlier cumulative mentions
        median = vals[len(vals) // 2]
        return median if median < hard_cap else None

    figures["dr"] = pick(dr_vals, 500)
    figures["bm"] = pick(bm_vals, 200)
    figures["cm"] = pick(cm_vals, 100)

    return figures


def extract_casualties_from_text(text):
    """Extract cumulative killed/injured from text."""
    result = {"ck": None, "ci": None}

    ck_matches = RE_KILLED.findall(text)
    ci_matches = RE_INJURED.findall(text)

    if ck_matches:
        val = max(int(x) for x in ck_matches)
        if val < 500:  # sanity
            result["ck"] = val
    if ci_matches:
        val = max(int(x) for x in ci_matches)
        if val < 5000:  # sanity
            result["ci"] = val

    return result


def scrape_mod_statement_from_search(target_date):
    """
    Recipe Step 1: Search for UAE MOD statement for a specific date.
    Query: UAE MOD missiles drones [date] intercepted
    Returns figures dict or empty dict.
    """
    date_str = target_date.strftime("%B %d %Y")
    queries = [
        'UAE MOD "%s" missiles drones intercepted' % date_str,
        "UAE air defence today %s casualties latest" % target_date.strftime("%B %Y"),
        "UAE ministry defense %s intercepted drones ballistic" % date_str,
    ]

    for query in queries:
        articles = search_news(query)
        for article in articles:
            # Try to fetch the article content
            if not article.get("link"):
                continue

            html = fetch_url(article["link"])
            if not html:
                continue

            soup = BeautifulSoup(html, "html.parser")
            # Remove scripts, styles, nav
            for tag in soup.find_all(["script", "style", "nav", "header", "footer"]):
                tag.decompose()

            text = soup.get_text(" ", strip=True)
            figures = extract_daily_figures_from_text(text)
            casualties = extract_casualties_from_text(text)

            # Need at least drones or ballistic to consider valid
            if figures["dr"] is not None or figures["bm"] is not None:
                log.info("MOD search hit: %s (source: %s)", article["title"][:60], article["source"])
                result = {
                    "dr": figures["dr"] or 0,
                    "bm": figures["bm"] or 0,
                    "cm": figures["cm"] or 0,
                }
                if casualties["ck"] is not None:
                    result["ck"] = casualties["ck"]
                if casualties["ci"] is not None:
                    result["ci"] = casualties["ci"]
                return result

    log.warning("No MOD statement found for %s", date_str)
    return {}


def scrape_gulf_news(target_date):
    """Try Gulf News for daily figures."""
    html = fetch_url(GULF_NEWS_URL)
    if not html:
        return {}

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(["script", "style"]):
        tag.decompose()

    # Look for articles mentioning intercepted/missiles/drones
    articles = soup.find_all("article")
    if not articles:
        articles = soup.find_all("div", class_=re.compile(r"article|story|card"))

    for article in articles[:20]:
        text = article.get_text(" ", strip=True)
        if any(kw in text.lower() for kw in ["intercept", "missile", "drone", "ballistic", "air defence"]):
            figures = extract_daily_figures_from_text(text)
            if figures["dr"] is not None or figures["bm"] is not None:
                log.info("Gulf News hit: %s", text[:80])
                return {
                    "dr": figures["dr"] or 0,
                    "bm": figures["bm"] or 0,
                    "cm": figures["cm"] or 0,
                }

    log.info("Gulf News: no matching articles found")
    return {}


def scrape_khaleej_times(target_date):
    """Try Khaleej Times for daily figures."""
    html = fetch_url(KHALEEJ_URL)
    if not html:
        return {}

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(["script", "style"]):
        tag.decompose()

    articles = soup.find_all("article")
    if not articles:
        articles = soup.find_all("div", class_=re.compile(r"article|story|card"))

    for article in articles[:20]:
        text = article.get_text(" ", strip=True)
        if any(kw in text.lower() for kw in ["intercept", "missile", "drone", "ballistic", "air defence", "gulf_defense"]):
            figures = extract_daily_figures_from_text(text)
            if figures["dr"] is not None or figures["bm"] is not None:
                log.info("Khaleej Times hit: %s", text[:80])
                return {
                    "dr": figures["dr"] or 0,
                    "bm": figures["bm"] or 0,
                    "cm": figures["cm"] or 0,
                }

    log.info("Khaleej Times: no matching articles found")
    return {}


def parse_wikipedia():
    """
    Parse Wikipedia article for daily attack data (cross-reference source).
    Returns dict: { "2026-03-01": {"dr": N, "bm": N, "cm": N, "ck": N, "ci": N}, ... }
    """
    html = fetch_url(WIKI_URL)
    if not html:
        log.error("Wikipedia fetch failed")
        return {}

    soup = BeautifulSoup(html, "html.parser")

    # Remove references/citations
    for ref in soup.find_all(["sup", "style", "script"]):
        ref.decompose()

    daily_data = {}
    current_date = None

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
            bm_matches = RE_BALLISTIC.findall(text)
            dr_matches = RE_DRONES.findall(text)
            cm_matches = RE_CRUISE.findall(text)
            ck_matches = RE_KILLED.findall(text)
            ci_matches = RE_INJURED.findall(text)

            if bm_matches or dr_matches or cm_matches:
                if current_date not in daily_data:
                    daily_data[current_date] = {"dr": 0, "bm": 0, "cm": 0, "ck": None, "ci": None}

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

            if ck_matches:
                if current_date not in daily_data:
                    daily_data[current_date] = {"dr": 0, "bm": 0, "cm": 0, "ck": None, "ci": None}
                val = max(int(x) for x in ck_matches)
                if val < 500:
                    daily_data[current_date]["ck"] = val

            if ci_matches:
                if current_date not in daily_data:
                    daily_data[current_date] = {"dr": 0, "bm": 0, "cm": 0, "ck": None, "ci": None}
                val = max(int(x) for x in ci_matches)
                if val < 5000:
                    daily_data[current_date]["ci"] = val

    log.info("Wikipedia: parsed %d dated entries", len(daily_data))
    return daily_data


def scrape_news_items():
    """
    Recipe Step 7: Search for latest news for the Trends tab.
    Categories: school/IB, ceasefire, new tactics, visa, aviation.
    Returns list of news dicts.
    """
    news_queries = [
        ("school", "UAE schools exams distance learning schedule 2026"),
        ("economy", "UAE economy business prices cost of living 2026"),
        ("visa", "UAE visa residence permit rules update 2026"),
        ("aviation", "Dubai Abu Dhabi airport flights status open 2026"),
        ("daily", "UAE daily life safety shelters civil defence advisory 2026"),
    ]

    all_news = []

    for category, query in news_queries:
        articles = search_news(query, max_results=3)
        for article in articles[:2]:  # Top 2 per category
            all_news.append({
                "category": category,
                "title": article.get("title", ""),
                "source": article.get("source", ""),
                "link": article.get("link", ""),
                "date": article.get("date", ""),
            })

    log.info("News: collected %d items across %d categories", len(all_news), len(news_queries))
    return all_news


def extract_existing_from_html():
    """
    Extract current data arrays from HTML as authoritative baseline.
    """
    html_file = REPO_ROOT / "uae_telegram.html"
    if not html_file.exists():
        return {}

    html = html_file.read_text(encoding="utf-8")

    def extract_array(var_name):
        pattern = r"var\s+%s\s*=\s*\[([\d,\s]+)\]" % var_name
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

    log.info("Extracted %d days from existing HTML", len(days))
    return days


def load_existing_data():
    """Load existing daily.json if it exists."""
    if DATA_FILE.exists():
        try:
            with open(DATA_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            log.warning("Could not parse existing daily.json, starting fresh")
    return {"meta": {}, "days": {}}


def _rolling_avg(days_dict, date_str, key, window=7):
    """
    Compute rolling average for `key` over the last `window` days before `date_str`.
    Returns the average, or None if fewer than 3 prior data points exist.
    """
    sorted_dates = sorted(d for d in days_dict if d < date_str)
    recent = sorted_dates[-window:]
    vals = [days_dict[d].get(key, 0) for d in recent]
    if len(vals) < 3:
        return None
    return sum(vals) / len(vals)


def _is_outlier(days_dict, date_str, key, value, multiplier=4.0):
    """
    Returns True if `value` is suspiciously high compared to the rolling average.
    Uses a multiplier threshold (default 4x) with a minimum floor so that
    real spikes at low averages aren't wrongly rejected.
    """
    avg = _rolling_avg(days_dict, date_str, key)
    if avg is None:
        return False  # not enough history to judge
    floor = max(avg * multiplier, 20)  # never reject values below 20
    if value > floor:
        log.warning(
            "OUTLIER detected: %s %s=%d vs 7d-avg=%.1f (threshold=%.0f)",
            date_str, key, value, avg, floor
        )
        return True
    return False


def merge_data(existing, scraped, trust_existing_launches=False):
    """
    Merge scraped data into existing data.

    If trust_existing_launches=True, never overwrite DR/BM/CM for days that
    already exist (the HTML baseline is authoritative for launch counts).

    Dynamic outlier detection: new values are checked against a 7-day rolling
    average. Values exceeding 4x the average are flagged and skipped.
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
            # Dynamic sanity-check per field against recent trend
            filtered_vals = dict(vals)
            for key in ("dr", "bm", "cm"):
                v = filtered_vals.get(key, 0)
                if v and _is_outlier(merged, date, key, v):
                    log.warning("Dropping outlier %s=%d for %s", key, v, date)
                    filtered_vals[key] = 0

            # Hard caps still apply as last resort
            if filtered_vals.get("dr", 0) > 500 or filtered_vals.get("bm", 0) > 200:
                log.warning("Skipping suspicious day %s: DR=%s BM=%s (hard cap)",
                            date, filtered_vals.get("dr"), filtered_vals.get("bm"))
                continue

            if is_placeholder:
                merged[date].update(filtered_vals)
                log.info("FILLED placeholder: %s -- DR:%s BM:%s CM:%s",
                         date, filtered_vals.get("dr"), filtered_vals.get("bm"), filtered_vals.get("cm"))
            else:
                merged[date] = filtered_vals
                log.info("NEW day: %s -- DR:%s BM:%s CM:%s",
                         date, filtered_vals.get("dr"), filtered_vals.get("bm"), filtered_vals.get("cm"))
        else:
            old = merged[date]
            updated = False

            if not trust_existing_launches:
                for key in ("dr", "bm", "cm"):
                    if vals.get(key) and vals[key] > old.get(key, 0):
                        if _is_outlier(merged, date, key, vals[key]):
                            log.warning("Dropping outlier update %s=%d for %s", key, vals[key], date)
                            continue
                        if (key == "dr" and vals[key] > 500) or (key == "bm" and vals[key] > 200):
                            log.warning("Skipping suspicious %s=%s for %s (hard cap)", key, vals[key], date)
                            continue
                        old[key] = vals[key]
                        updated = True

            # Casualties: always allow upward updates (cumulative)
            for key in ("ck", "ci"):
                if vals.get(key) is not None and (old.get(key) is None or vals[key] > old[key]):
                    old[key] = vals[key]
                    updated = True

            if updated:
                log.info("UPDATED day: %s", date)

    return merged


def forward_fill_casualties(days):
    """
    Casualty figures (CK, CI) are cumulative -- forward fill gaps.
    Enforce monotonicity.
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
    log.info("=== Gulf Report Data Scraper (Recipe-based) ===")

    today = datetime.utcnow().date()
    target_date = datetime(today.year, today.month, today.day)
    target_date_str = target_date.strftime("%Y-%m-%d")

    # Step 1: Load baseline from existing HTML (authoritative)
    existing_days = extract_existing_from_html()

    # Step 2: Load previously saved data
    saved = load_existing_data()
    if saved.get("days"):
        existing_days = merge_data(existing_days, saved["days"])

    # Step 3: Check if today's data is already present and non-zero
    today_data = existing_days.get(target_date_str, {})
    today_has_data = (
        today_data.get("dr", 0) > 0 or
        today_data.get("bm", 0) > 0
    )

    new_day_data = {}

    if not today_has_data:
        log.info("No data for %s yet, searching sources...", target_date_str)

        # Recipe Step 1-2: Search MOD statement via news search
        mod_data = scrape_mod_statement_from_search(target_date)
        if mod_data:
            new_day_data[target_date_str] = mod_data
            log.info("MOD search: DR=%s BM=%s CM=%s",
                     mod_data.get("dr"), mod_data.get("bm"), mod_data.get("cm"))

        # Fallback: Gulf News
        if not new_day_data.get(target_date_str):
            gn_data = scrape_gulf_news(target_date)
            if gn_data:
                new_day_data[target_date_str] = gn_data

        # Fallback: Khaleej Times
        if not new_day_data.get(target_date_str):
            kt_data = scrape_khaleej_times(target_date)
            if kt_data:
                new_day_data[target_date_str] = kt_data
    else:
        log.info("Today %s already has data: DR=%s BM=%s CM=%s",
                 target_date_str, today_data.get("dr"), today_data.get("bm"), today_data.get("cm"))

    # Step 4: Always scrape Wikipedia as cross-reference
    wiki_data = parse_wikipedia()

    # Step 5: Merge -- trust existing launch counts, add new days/casualties
    merged = merge_data(existing_days, wiki_data, trust_existing_launches=True)

    # Merge new day data from MOD/news (higher priority than Wikipedia)
    if new_day_data:
        merged = merge_data(merged, new_day_data, trust_existing_launches=False)

    # Step 6: Forward-fill casualties
    merged = forward_fill_casualties(merged)

    # Step 7: Scrape news for Trends tab
    news_items = scrape_news_items()

    # Compute summary
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

    # Save daily.json
    DATA_DIR.mkdir(exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # Save news.json
    if news_items:
        with open(NEWS_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "updated": datetime.utcnow().isoformat() + "Z",
                "items": news_items,
            }, f, ensure_ascii=False, indent=2)
        log.info("Saved %d news items to %s", len(news_items), NEWS_FILE)

    log.info("Saved %d days to %s", len(merged), DATA_FILE)
    log.info("Summary: %d days, %d launches (DR:%d BM:%d CM:%d)",
             num_days, total, total_dr, total_bm, total_cm)
    log.info("Casualties: %d killed, %d injured", last_ck, last_ci)

    if not merged:
        log.error("No data collected!")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
