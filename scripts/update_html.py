#!/usr/bin/env python3
"""
update_html.py — Patches uae_telegram.html with fresh data from data/daily.json.

Reads the JSON produced by scrape_data.py and updates:
  1. JavaScript data arrays (DR, BM, CM, CK, CI)
  2. Summary stats (total launches, ballistic, drones, cruise, killed, injured)
  3. Header date and day counter
  4. DAYS labels array

Does NOT touch: CSS, chart configs, news blocks (those are editorial).
Rashid's principle: idempotent — run twice, get same output.
"""

import json
import re
import sys
import logging
from datetime import datetime, timedelta
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M"
)
log = logging.getLogger("update_html")

REPO_ROOT = Path(__file__).resolve().parent.parent
HTML_FILE = REPO_ROOT / "uae_telegram.html"
DATA_FILE = REPO_ROOT / "data" / "daily.json"

START_DATE = datetime(2026, 2, 28)

# Russian month abbreviations for DAYS labels
MONTH_ABBR = {
    2: "ф",   # февраль
    3: "м",   # март
    4: "апр", # апрель
    5: "мая", # май
    6: "июн", # июнь
}


def date_to_label(date_str: str) -> str:
    """Convert '2026-03-15' to '15м' (Russian short date for chart label)."""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    day = dt.day
    month = dt.month
    abbr = MONTH_ABBR.get(month, str(month))
    return f"{day}{abbr}"


def format_number_ru(n: int) -> str:
    """Format number with space as thousands separator (Russian style): 2429 -> '2 429'."""
    s = f"{n:,}".replace(",", " ")
    return s


def replace_js_array(html: str, var_name: str, values: list) -> str:
    """Replace a JavaScript array declaration: var NAME=[...]; with new values."""
    vals_str = ",".join(str(v) for v in values)
    pattern = rf"(var\s+{var_name}\s*=\s*\[)[^\]]*(\])"
    replacement = rf"\g<1>{vals_str}\2"
    new_html, count = re.subn(pattern, replacement, html)
    if count == 0:
        log.warning(f"Could not find var {var_name} in HTML")
    else:
        log.info(f"Updated var {var_name} ({len(values)} values)")
    return new_html


def replace_stat_value(html: str, label_text: str, new_value: str, new_subtitle: str = None) -> str:
    """
    Replace a stat card value by finding the label text.
    Structure: <div class="sl">LABEL</div><div class="sv" ...>VALUE</div><div class="ss">SUB</div>
    """
    # Find the stat block containing this label
    pattern = rf'(<div class="sl">{re.escape(label_text)}</div>\s*<div class="sv"[^>]*>)[^<]*(</div>)'
    new_html, count = re.subn(pattern, rf'\g<1>{new_value}\2', html)
    if count == 0:
        log.warning(f"Could not find stat '{label_text}'")
    else:
        log.info(f"Updated stat '{label_text}' -> {new_value}")

    if new_subtitle is not None:
        pattern_sub = rf'(<div class="sl">{re.escape(label_text)}</div>\s*<div class="sv"[^>]*>[^<]*</div>\s*<div class="ss">)[^<]*(</div>)'
        new_html, count = re.subn(pattern_sub, rf'\g<1>{new_subtitle}\2', new_html)

    return new_html


def replace_badge(html: str, day_number: int) -> str:
    """Update the day counter badge."""
    pattern = r'(<div class="badge">)[^<]*(</div>)'
    replacement = rf'\g<1>День {day_number}\2'
    return re.sub(pattern, replacement, html)


def replace_header_date(html: str, date_str: str) -> str:
    """Update the date in the header subtitle."""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    months_ru = {
        1: "января", 2: "февраля", 3: "марта", 4: "апреля",
        5: "мая", 6: "июня", 7: "июля", 8: "августа",
        9: "сентября", 10: "октября", 11: "ноября", 12: "декабря"
    }
    date_ru = f"{dt.day} {months_ru[dt.month]} {dt.year}"
    pattern = r'(<div class="hdr-s">МО ОАЭ · The National · Al Jazeera\s*&nbsp;·&nbsp;\s*)[^<]*(</div>)'
    replacement = rf'\g<1>{date_ru}\2'
    return re.sub(pattern, replacement, html)


def update_comparison_table_uae_row(html: str, num_days: int, total: int, killed: int, population_m: float = 9.7) -> str:
    """Update the UAE row in the comparison table."""
    per_million = round(killed / population_m, 2) if killed > 0 else 0
    launches_per_death = round(total / killed) if killed > 0 else 0

    days_word = "дней" if num_days % 10 >= 5 or num_days % 10 == 0 or (11 <= num_days % 100 <= 14) else ("день" if num_days % 10 == 1 else "дня")
    per_million_str = str(per_million).replace(".", ",")

    # Use a function-based replacement to avoid regex escape issues
    pattern = r'(<tr><td><b>ОАЭ 2026</b></td><td>)\d+ дн[яей]*(</td><td>)[^<]*(</td><td[^>]*><b>)[^<]*(</b></td>)'

    def replacer(m):
        return f"{m.group(1)}{num_days} {days_word}{m.group(2)}{format_number_ru(total)}{m.group(3)}{per_million_str}{m.group(4)}"

    html = re.sub(pattern, replacer, html)

    # Update launches per death stat card
    html = replace_stat_value(html, "Запуск / гиб.", str(launches_per_death))

    return html


def main():
    log.info("=== Gulf Report HTML Updater ===")

    # Load data
    if not DATA_FILE.exists():
        log.error(f"Data file not found: {DATA_FILE}")
        log.error("Run scrape_data.py first")
        return 1

    with open(DATA_FILE, encoding="utf-8") as f:
        data = json.load(f)

    meta = data.get("meta", {})
    days = data.get("days", {})

    if not days:
        log.error("No daily data found")
        return 1

    # Load HTML
    if not HTML_FILE.exists():
        log.error(f"HTML file not found: {HTML_FILE}")
        return 1

    html = HTML_FILE.read_text(encoding="utf-8")

    # Sort dates
    sorted_dates = sorted(days.keys())
    num_days = len(sorted_dates)
    last_date = sorted_dates[-1]

    # Build arrays
    dr_arr = [days[d]["dr"] for d in sorted_dates]
    bm_arr = [days[d]["bm"] for d in sorted_dates]
    cm_arr = [days[d]["cm"] for d in sorted_dates]
    ck_arr = [days[d]["ck"] for d in sorted_dates]
    ci_arr = [days[d]["ci"] for d in sorted_dates]
    day_labels = [date_to_label(d) for d in sorted_dates]

    # Mark the last day with * if it's possibly incomplete
    last_dt = datetime.strptime(last_date, "%Y-%m-%d")
    if last_dt.date() >= datetime.utcnow().date():
        day_labels[-1] = day_labels[-1] + "*"

    # Totals
    total_dr = sum(dr_arr)
    total_bm = sum(bm_arr)
    total_cm = sum(cm_arr)
    total = total_dr + total_bm + total_cm
    killed = ck_arr[-1] if ck_arr else 0
    injured = ci_arr[-1] if ci_arr else 0

    log.info(f"Data: {num_days} days, last={last_date}")
    log.info(f"Totals: DR={total_dr} BM={total_bm} CM={total_cm} Total={total}")
    log.info(f"Casualties: {killed} killed, {injured} injured")

    # ---- UPDATE HTML ----

    # 1. Update DAYS labels
    days_str = ",".join(f"'{l}'" for l in day_labels)
    html = re.sub(
        r"(var\s+DAYS\s*=\s*\[)[^\]]*(\])",
        rf"\g<1>{days_str}\2",
        html
    )
    log.info(f"Updated DAYS array ({len(day_labels)} labels)")

    # 2. Update data arrays
    html = replace_js_array(html, "DR", dr_arr)
    html = replace_js_array(html, "BM", bm_arr)
    html = replace_js_array(html, "CM", cm_arr)
    html = replace_js_array(html, "CK", ck_arr)
    html = replace_js_array(html, "CI", ci_arr)

    # 3. Update stat cards
    html = replace_stat_value(html, "Запусков", format_number_ru(total), f"{num_days} дней" if num_days != 34 else "34 дня")
    html = replace_stat_value(html, "Баллист.", format_number_ru(total_bm), f"+{total_cm} крыл.")
    html = replace_stat_value(html, "Дронов", format_number_ru(total_dr), "Shahed")
    html = replace_stat_value(html, "Погибших", str(killed))
    html = replace_stat_value(html, "Раненых", str(injured))

    # 4. Update badge (day counter)
    html = replace_badge(html, num_days)

    # 5. Update header date
    html = replace_header_date(html, last_date)

    # 6. Update launches per death
    if killed > 0:
        lpd = round(total / killed)
        html = replace_stat_value(html, "Запуск / гиб.", str(lpd), "исторический рекорд" if lpd > 100 else "")

    # 7. Update per-million stat
    uae_pop = 9.7  # million
    per_million = round(killed / uae_pop, 2)
    html = replace_stat_value(html, "ОАЭ / млн", str(per_million).replace(".", ","), f"{num_days} дней войны" if num_days != 34 else "34 дня войны")

    # 8. Update comparison table UAE row
    html = update_comparison_table_uae_row(html, num_days, total, killed)

    # 9. Update weekly chart data
    # The weekly chart is computed from TOT in JS, so it auto-updates

    # ---- WRITE HTML ----
    HTML_FILE.write_text(html, encoding="utf-8")
    log.info(f"Written updated HTML to {HTML_FILE}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
