#!/usr/bin/env python3
"""
update_html.py — Patches uae_telegram.html per DASHBOARD_RECIPE.md Section 7.

UPDATE PROCEDURE:
  3. Update arrays: append new day to DR[], BM[], CM[], CK[], CI[]
  4. Update badge: increment day counter
  5. Update subtitle: new date + source
  6. Update stats: recalculate totals
  7. Update news: inject latest news cards from news.json
  8. Rebuild file: write complete new HTML

Reads data/daily.json + data/news.json produced by scrape_data.py.
Rashid's principle: idempotent -- run twice, get same output.
"""

import json
import re
import sys
import logging
from datetime import datetime, timedelta
from pathlib import Path
from math import ceil

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M"
)
log = logging.getLogger("update_html")

REPO_ROOT = Path(__file__).resolve().parent.parent
HTML_FILE = REPO_ROOT / "uae_telegram.html"
DATA_FILE = REPO_ROOT / "data" / "daily.json"
NEWS_FILE = REPO_ROOT / "data" / "news.json"

START_DATE = datetime(2026, 2, 28)

# Russian month abbreviations for DAYS labels (per recipe Section 2)
MONTH_ABBR = {
    2: "f",    # февраль -> ф
    3: "m",    # март -> м
    4: "apr",  # апрель -> апр
    5: "may",  # май -> мая
    6: "jun",  # июнь -> июн
}

# Correct Russian short abbreviations
MONTH_ABBR_RU = {
    2: "\u0444",      # ф
    3: "\u043c",      # м
    4: "\u0430\u043f\u0440",  # апр
    5: "\u043c\u0430\u044f",  # мая
    6: "\u0438\u044e\u043d",  # июн
}

MONTHS_RU_FULL = {
    1: "\u044f\u043d\u0432\u0430\u0440\u044f",
    2: "\u0444\u0435\u0432\u0440\u0430\u043b\u044f",
    3: "\u043c\u0430\u0440\u0442\u0430",
    4: "\u0430\u043f\u0440\u0435\u043b\u044f",
    5: "\u043c\u0430\u044f",
    6: "\u0438\u044e\u043d\u044f",
    7: "\u0438\u044e\u043b\u044f",
    8: "\u0430\u0432\u0433\u0443\u0441\u0442\u0430",
    9: "\u0441\u0435\u043d\u0442\u044f\u0431\u0440\u044f",
    10: "\u043e\u043a\u0442\u044f\u0431\u0440\u044f",
    11: "\u043d\u043e\u044f\u0431\u0440\u044f",
    12: "\u0434\u0435\u043a\u0430\u0431\u0440\u044f",
}

# News category -> tag class and label (per recipe Section 4)
NEWS_CATEGORIES = {
    "school": {"tag_class": "tr", "label": "\u0428\u043a\u043e\u043b\u044b", "icon": "\U0001f3eb"},
    "economy": {"tag_class": "ta", "label": "\u042d\u043a\u043e\u043d\u043e\u043c\u0438\u043a\u0430", "icon": "\U0001f4b0"},
    "tactics": {"tag_class": "ta", "label": "\u0421\u0438\u0442\u0443\u0430\u0446\u0438\u044f", "icon": "\U0001f6a2"},
    "visa": {"tag_class": "ta", "label": "\u0412\u0438\u0437\u044b", "icon": "\U0001f4cb"},
    "aviation": {"tag_class": "tb", "label": "\u0410\u0432\u0438\u0430\u0446\u0438\u044f", "icon": "\u2708\ufe0f"},
    "daily": {"tag_class": "ta", "label": "\u0411\u044b\u0442 \u0438 \u0431\u0435\u0437\u043e\u043f\u0430\u0441\u043d\u043e\u0441\u0442\u044c", "icon": "\U0001f3e0"},
}


def date_to_label(date_str):
    """Convert '2026-03-15' to '15м' (Russian short date for chart label)."""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    day = dt.day
    month = dt.month
    abbr = MONTH_ABBR_RU.get(month, str(month))
    return "%d%s" % (day, abbr)


def format_number_ru(n):
    """Format number with space as thousands separator: 2429 -> '2 429'."""
    s = "{:,}".format(n).replace(",", " ")
    return s


def days_word_ru(n):
    """Russian word for 'days' depending on number."""
    mod10 = n % 10
    mod100 = n % 100
    if 11 <= mod100 <= 14:
        return "\u0434\u043d\u0435\u0439"
    elif mod10 == 1:
        return "\u0434\u0435\u043d\u044c"
    elif 2 <= mod10 <= 4:
        return "\u0434\u043d\u044f"
    else:
        return "\u0434\u043d\u0435\u0439"


def replace_js_array(html, var_name, values):
    """Replace a JavaScript array: var NAME=[...]; with new values."""
    vals_str = ",".join(str(v) for v in values)
    pattern = r"(var\s+%s\s*=\s*\[)[^\]]*(\])" % var_name
    new_html, count = re.subn(pattern, r"\g<1>%s\2" % vals_str, html)
    if count == 0:
        log.warning("Could not find var %s in HTML", var_name)
    else:
        log.info("Updated var %s (%d values)", var_name, len(values))
    return new_html


def replace_days_array(html, labels):
    """Replace the DAYS string array with quoted labels."""
    days_str = ",".join("'%s'" % l for l in labels)
    pattern = r"(var\s+DAYS\s*=\s*\[)[^\]]*(\])"
    new_html, count = re.subn(pattern, r"\g<1>%s\2" % days_str, html)
    if count == 0:
        log.warning("Could not find var DAYS in HTML")
    else:
        log.info("Updated DAYS array (%d labels)", len(labels))
    return new_html


def replace_stat_value(html, label_text, new_value, new_subtitle=None):
    """
    Replace a stat card value by finding the label text.
    Structure: <div class="sl">LABEL</div><div class="sv" ...>VALUE</div><div class="ss">SUB</div>
    """
    escaped_label = re.escape(label_text)
    pattern = r'(<div class="sl">%s</div>\s*<div class="sv"[^>]*>)[^<]*(</div>)' % escaped_label
    new_html, count = re.subn(pattern, r'\g<1>%s\2' % new_value, html)
    if count == 0:
        log.warning("Could not find stat '%s'", label_text)
    else:
        log.info("Updated stat '%s' -> %s", label_text, new_value)

    if new_subtitle is not None:
        pattern_sub = (
            r'(<div class="sl">%s</div>\s*<div class="sv"[^>]*>[^<]*</div>\s*<div class="ss">)[^<]*(</div>)'
            % escaped_label
        )
        new_html, _ = re.subn(pattern_sub, r'\g<1>%s\2' % new_subtitle, new_html)

    return new_html


def replace_badge(html, day_number):
    """Recipe Step 4: Update the day counter badge."""
    # Badge has structure: <div class="badge"><span data-t="badge">День</span> 33</div>
    pattern = r'(<div class="badge">).*?(</div>)'
    replacement = r'\g<1><span data-t="badge">День</span> %d\2' % day_number
    result = re.sub(pattern, replacement, html, flags=re.DOTALL)
    log.info("Updated badge: Day %d", day_number)
    return result


def replace_header_date(html, date_str):
    """Recipe Step 5: Update the date in the header subtitle."""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    date_ru = "%d %s %d" % (dt.day, MONTHS_RU_FULL[dt.month], dt.year)

    # Match the subtitle pattern with source names and date
    pattern = (
        r'(<div class="hdr-s">'
        r'[\u0410-\u044f\u0451\u0401\w\s&;·\.\-]+&nbsp;[·;]&nbsp;\s*)'
        r'[^<]*(</div>)'
    )
    new_html, count = re.subn(pattern, r'\g<1>%s\2' % date_ru, html)
    if count == 0:
        # Fallback: replace any date-like content after the last separator
        pattern2 = r'(<div class="hdr-s">.*?&nbsp;·&nbsp;\s*)[^<]*(</div>)'
        new_html, count = re.subn(pattern2, r'\g<1>%s\2' % date_ru, html)
    if count == 0:
        log.warning("Could not update header date")
    else:
        log.info("Updated header date: %s", date_ru)
    return new_html


def update_comparison_table(html, num_days, total, killed, population_m=9.7):
    """Update the UAE row in the comparison table (Tab 1)."""
    per_million = round(killed / population_m, 2) if killed > 0 else 0
    launches_per_death = round(total / killed) if killed > 0 else 0

    dw = days_word_ru(num_days)
    per_million_str = str(per_million).replace(".", ",")

    # Update table row
    pattern = (
        r'(<tr><td><b>\u041e\u0410\u042d 2026</b></td><td>)\d+ '
        r'\u0434[\u043d\u0435\u0439\u044c\u044f]*(</td><td>)[^<]*'
        r'(</td><td[^>]*><b>)[^<]*(</b></td>)'
    )

    def replacer(m):
        return "%s%d %s%s%s%s%s%s" % (
            m.group(1), num_days, dw, m.group(2),
            format_number_ru(total), m.group(3),
            per_million_str, m.group(4)
        )

    html = re.sub(pattern, replacer, html)

    # Update launches per death stat card
    html = replace_stat_value(html, "\u0417\u0430\u043f\u0443\u0441\u043a / \u0433\u0438\u0431.", str(launches_per_death))

    return html


def update_trends_from_rashid(html, trends):
    """
    Rashid-generated Trends tab: deadline banner + trend summary.
    Reads from data/trends.json (generated by scrape_data.py).
    Falls back to static values if trends.json is missing.
    """
    if not trends:
        log.info("No Rashid trends data, keeping existing content")
        return html

    # Update deadline banner
    dl_label = trends.get("deadline_label", "")
    dl_days = trends.get("deadline_days", 0)
    dl_caption = trends.get("deadline_caption", "")
    dl_body = trends.get("deadline_body", "")

    if dl_label:
        pattern = r'(<div class="dl-label"[^>]*>)[^<]*(</div>)'
        html = re.sub(pattern, r'\g<1>%s\2' % dl_label, html)

    if dl_days is not None:
        pattern = r'(<div class="dl-days">)[^<]*(</div>)'
        html = re.sub(pattern, r'\g<1>%s\2' % max(dl_days, 0), html)

    if dl_caption:
        pattern = r'(<div class="dl-caption"[^>]*>)[^<]*(</div>)'
        html = re.sub(pattern, r'\g<1>%s\2' % dl_caption, html)

    if dl_body:
        pattern = r'(<div class="dl-body"[^>]*>).*?(</div>)'
        html = re.sub(pattern, r'\g<1>%s\2' % dl_body, html, flags=re.DOTALL)

    log.info("Updated deadline: %s (%d days)", dl_label, dl_days if dl_days else 0)

    # Update trend block
    trend_title = trends.get("trend_title", "")
    trend_body = trends.get("trend_body", "")

    if trend_title:
        pattern = r'(<div class="trend-t"[^>]*>)[^<]*(</div>)'
        html = re.sub(pattern, r'\g<1>%s\2' % trend_title, html)

    if trend_body:
        pattern = r'(<div class="trend-b"[^>]*>).*?(</div>)'
        html = re.sub(pattern, r'\g<1>%s\2' % trend_body, html, flags=re.DOTALL)
        log.info("Updated trend body from Rashid")

    return html


def update_deadline_banner(html):
    """Legacy fallback: static deadline countdown."""
    today = datetime.utcnow().date()
    deadline = datetime(2026, 4, 6).date()
    days_left = (deadline - today).days

    if days_left < 0:
        pattern = r'(<div class="dl-days">)\d+(</div>)'
        html = re.sub(pattern, r'\g<1>0\2', html)
        pattern2 = r'(<div class="dl-caption"[^>]*>)[^<]*(</div>)'
        html = re.sub(pattern2, r'\g<1>' + 'дедлайн прошёл' + r'\2', html)
    else:
        pattern = r'(<div class="dl-days">)\d+(</div>)'
        html = re.sub(pattern, r'\g<1>%d\2' % days_left, html)

    log.info("Updated deadline (legacy): %d days left", max(days_left, 0))
    return html


def update_trend_date(html, date_str):
    """Legacy fallback: update trend date header."""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    date_ru = "%d %s %d" % (dt.day, MONTHS_RU_FULL[dt.month], dt.year)
    pattern = r'(<div class="trend-t"[^>]*>)[^<]*(</div>)'
    html = re.sub(pattern, r'\g<1>Тренды · %s\2' % date_ru, html)
    log.info("Updated trend date: %s", date_ru)
    return html


def build_news_html(news_items):
    """
    Build HTML for news cards from news.json.
    Per recipe Section 4 template.
    """
    if not news_items:
        return ""

    blocks = []
    for item in news_items:
        cat = item.get("category", "")
        cat_info = NEWS_CATEGORIES.get(cat, {"tag_class": "tb", "label": cat, "icon": ""})

        title = item.get("title", "").replace("<", "&lt;").replace(">", "&gt;")
        source = item.get("source", "").replace("<", "&lt;").replace(">", "&gt;")
        date = item.get("date", "").replace("<", "&lt;").replace(">", "&gt;")
        summary = item.get("summary", "").replace("<", "&lt;").replace(">", "&gt;")
        analysis = item.get("analysis", "").replace("<", "&lt;").replace(">", "&gt;")

        if not title:
            continue

        # Build body: Rashid's summary + analysis (if available)
        body_parts = []
        if summary:
            body_parts.append(summary)
        if analysis:
            body_parts.append(analysis)
        body_html = ""
        if body_parts:
            body_html = '    <div class="nbod">%s</div>\n' % " ".join(body_parts)

        block = (
            '<div class="news">\n'
            '    <div class="ntag %s">%s %s</div>\n'
            '    <div class="ntit">%s</div>\n'
            '%s'
            '    <div class="nmeta">%s%s</div>\n'
            '  </div>' % (
                cat_info["tag_class"],
                cat_info["icon"],
                cat_info["label"],
                title,
                body_html,
                date,
                (" \u00b7 " + source) if source else "",
            )
        )
        blocks.append(block)

    return "\n\n  ".join(blocks)


def update_news_section(html, news_items):
    """
    Recipe Step 7: Replace news cards in the Trends tab.
    Only replaces if we have new news items. Keeps existing news if no new data.
    """
    if not news_items:
        log.info("No new news items, keeping existing news section")
        return html

    new_news_html = build_news_html(news_items)
    if not new_news_html:
        return html

    # Find the news section: starts after the trend block, ends before </div><!-- /p2 -->
    # We match from the first <div class="news"> to the last </div> before the panel close
    pattern = (
        r'(</div>\s*<!-- /trend -->\s*|'
        r'</div>\s*\n\s*(?=<div class="news">))'
        r'((?:<div class="news">.*?</div>\s*)+)'
        r'(\s*</div><!-- /p2 -->)'
    )

    new_html, count = re.subn(
        pattern,
        r'\g<1>%s\3' % new_news_html,
        html,
        flags=re.DOTALL
    )

    if count == 0:
        # Fallback: try to find the news blocks by simpler pattern
        log.info("News section replacement via fallback pattern")
        # Just log and skip -- we keep existing news rather than corrupt the HTML
    else:
        log.info("Updated %d news cards", len(news_items))

    return new_html if count > 0 else html


def update_weekly_labels(html, num_days):
    """Update week labels in the weekly chart (c1)."""
    num_weeks = ceil(num_days / 7)
    labels = []
    for w in range(1, num_weeks + 1):
        if w == num_weeks:
            start_day = (w - 1) * 7 + 1
            end_day = num_days
            if start_day == end_day:
                labels.append("'нед%d %d'" % (w, end_day))
            else:
                labels.append("'нед%d %d–%d'" % (w, start_day, end_day))
        else:
            labels.append("'нед%d'" % w)

    labels_str = ",".join(labels)
    pattern = r"(var\s+wL\s*=\s*\[)[^\]]*(\])"
    new_html, count = re.subn(pattern, r"\g<1>%s\2" % labels_str, html)
    if count > 0:
        log.info("Updated weekly labels: %d weeks", num_weeks)
    return new_html


def update_c4_uae_value(html, launches_per_death):
    """Update the UAE value in the launches-per-killed chart (c4)."""
    # The datasets data array in c4: [221,50,44,26.7,9.3]
    pattern = r"(// c4.*?datasets:\[\{data:\[)\d+\.?\d*(,50,44,26\.7,9\.3\])"
    new_html, count = re.subn(pattern, r"\g<1>%d\2" % launches_per_death, html, flags=re.DOTALL)
    if count > 0:
        log.info("Updated c4 UAE launches/killed: %d", launches_per_death)
    return new_html


def update_per_million_chart(html, per_million):
    """Update the UAE value in the per-million log chart (c3)."""
    # cmpV=[1.13,0.8,2.8,11.9,1.82,65.7,3488]
    pm_str = "%.2f" % per_million
    pattern = r"(var\s+cmpV\s*=\s*\[)\d+\.?\d*(,)"
    new_html, count = re.subn(pattern, r"\g<1>%s\2" % pm_str, html)
    if count > 0:
        log.info("Updated c3 UAE per-million: %s", pm_str)
    return new_html


def main():
    log.info("=== Gulf Report HTML Updater (Recipe-based) ===")

    # Load data
    if not DATA_FILE.exists():
        log.error("Data file not found: %s", DATA_FILE)
        log.error("Run scrape_data.py first")
        return 1

    with open(DATA_FILE, encoding="utf-8") as f:
        data = json.load(f)

    meta = data.get("meta", {})
    days = data.get("days", {})

    if not days:
        log.error("No daily data found")
        return 1

    # Load news (optional)
    news_items = []
    if NEWS_FILE.exists():
        try:
            with open(NEWS_FILE, encoding="utf-8") as f:
                news_data = json.load(f)
            news_items = news_data.get("items", [])
        except (json.JSONDecodeError, IOError):
            log.warning("Could not parse news.json")

    # Load HTML
    if not HTML_FILE.exists():
        log.error("HTML file not found: %s", HTML_FILE)
        return 1

    html = HTML_FILE.read_text(encoding="utf-8")

    # Sort dates and build arrays
    sorted_dates = sorted(days.keys())
    num_days = len(sorted_dates)
    last_date = sorted_dates[-1]

    # === Recipe Step 3: Update arrays ===
    dr_arr = [days[d]["dr"] for d in sorted_dates]
    bm_arr = [days[d]["bm"] for d in sorted_dates]
    cm_arr = [days[d]["cm"] for d in sorted_dates]
    ck_arr = [days[d]["ck"] for d in sorted_dates]
    ci_arr = [days[d]["ci"] for d in sorted_dates]
    day_labels = [date_to_label(d) for d in sorted_dates]

    # Mark last day with * if possibly incomplete (today or future)
    last_dt = datetime.strptime(last_date, "%Y-%m-%d")
    if last_dt.date() >= datetime.utcnow().date():
        day_labels[-1] = day_labels[-1] + "*"

    # === Compute totals (Recipe Step 6) ===
    total_dr = sum(dr_arr)
    total_bm = sum(bm_arr)
    total_cm = sum(cm_arr)
    total = total_dr + total_bm + total_cm
    killed = ck_arr[-1] if ck_arr else 0
    injured = ci_arr[-1] if ci_arr else 0
    uae_pop = 9.7
    per_million = round(killed / uae_pop, 2) if killed > 0 else 0
    launches_per_death = round(total / killed) if killed > 0 else 0

    log.info("Data: %d days, last=%s", num_days, last_date)
    log.info("Totals: DR=%d BM=%d CM=%d Total=%d", total_dr, total_bm, total_cm, total)
    log.info("Casualties: %d killed, %d injured", killed, injured)

    # ======== UPDATE HTML (Recipe Steps 3-8) ========

    # Step 3: Update data arrays
    html = replace_days_array(html, day_labels)
    html = replace_js_array(html, "DR", dr_arr)
    html = replace_js_array(html, "BM", bm_arr)
    html = replace_js_array(html, "CM", cm_arr)
    html = replace_js_array(html, "CK", ck_arr)
    html = replace_js_array(html, "CI", ci_arr)

    # Step 4: Update badge
    html = replace_badge(html, num_days)

    # Step 5: Update subtitle with new date
    html = replace_header_date(html, last_date)

    # Step 6: Recalculate and update stats
    dw = days_word_ru(num_days)
    html = replace_stat_value(
        html,
        "\u0417\u0430\u043f\u0443\u0441\u043a\u043e\u0432",
        format_number_ru(total),
        "%d %s" % (num_days, dw)
    )
    html = replace_stat_value(
        html,
        "\u0411\u0430\u043b\u043b\u0438\u0441\u0442.",
        format_number_ru(total_bm),
        "+%d \u043a\u0440\u044b\u043b." % total_cm
    )
    html = replace_stat_value(
        html,
        "\u0414\u0440\u043e\u043d\u043e\u0432",
        format_number_ru(total_dr),
        "Shahed"
    )
    html = replace_stat_value(
        html,
        "\u041f\u043e\u0433\u0438\u0431\u0448\u0438\u0445",
        str(killed)
    )
    html = replace_stat_value(
        html,
        "\u0420\u0430\u043d\u0435\u043d\u044b\u0445",
        str(injured)
    )

    # Per-million stat
    pm_str = str(per_million).replace(".", ",")
    html = replace_stat_value(
        html,
        "\u041e\u0410\u042d / \u043c\u043b\u043d",
        pm_str,
        "%d %s \u0432\u043e\u0439\u043d\u044b" % (num_days, dw)
    )

    # Launches per death
    if killed > 0:
        html = replace_stat_value(
            html,
            "\u0417\u0430\u043f\u0443\u0441\u043a / \u0433\u0438\u0431.",
            str(launches_per_death),
            "\u0438\u0441\u0442\u043e\u0440\u0438\u0447\u0435\u0441\u043a\u0438\u0439 \u0440\u0435\u043a\u043e\u0440\u0434" if launches_per_death > 100 else ""
        )

    # Comparison table update
    html = update_comparison_table(html, num_days, total, killed)

    # Update per-million chart (c3)
    html = update_per_million_chart(html, per_million)

    # Update launches per killed chart (c4)
    if killed > 0:
        html = update_c4_uae_value(html, launches_per_death)

    # Update ss_days and ss_dayswar in all language packs
    dw_en = "days" if num_days != 1 else "day"
    replacements = {
        r"ss_days:'(\d+)\s+\w+'": f"ss_days:'{num_days} %s'" % dw,
        r"ss_days:'(\d+)\s+days'": f"ss_days:'{num_days} {dw_en}'",
        r"ss_days:'(\d+)\s+يوم'": f"ss_days:'{num_days} يوم'",
        r"ss_days:'(\d+)\s+jours'": f"ss_days:'{num_days} jours'",
        r"ss_days:'(\d+)\s+giorni'": f"ss_days:'{num_days} giorni'",
        r"ss_dayswar:'(\d+)\s+\w+\s+войны'": f"ss_dayswar:'{num_days} {dw} войны'",
        r"ss_dayswar:'(\d+)\s+days\s+of\s+war'": f"ss_dayswar:'{num_days} {dw_en} of war'",
        r"ss_dayswar:'(\d+)\s+يوم\s+حرب'": f"ss_dayswar:'{num_days} يوم حرب'",
        r"ss_dayswar:'(\d+)\s+jours\s+de\s+guerre'": f"ss_dayswar:'{num_days} jours de guerre'",
        r"ss_dayswar:'(\d+)\s+giorni\s+di\s+guerra'": f"ss_dayswar:'{num_days} giorni di guerra'",
    }
    for pattern, repl in replacements.items():
        html = re.sub(pattern, repl, html)
    log.info("Updated ss_days/ss_dayswar to %d in all languages", num_days)

    # Update weekly labels
    html = update_weekly_labels(html, num_days)

    # Update Trends tab: Rashid-generated content (priority) or legacy fallback
    trends_file = REPO_ROOT / "data" / "trends.json"
    rashid_trends = None
    if trends_file.exists():
        try:
            rashid_trends = json.loads(trends_file.read_text(encoding="utf-8")).get("trends")
        except Exception:
            pass

    if rashid_trends:
        html = update_trends_from_rashid(html, rashid_trends)
    else:
        html = update_deadline_banner(html)
        html = update_trend_date(html, last_date)

    # Step 7: Update news section (only if we have fresh news)
    if news_items:
        html = update_news_section(html, news_items)

    # === Step 8: Rebuild file ===
    HTML_FILE.write_text(html, encoding="utf-8")
    log.info("Written updated HTML to %s", HTML_FILE)

    return 0


if __name__ == "__main__":
    sys.exit(main())
