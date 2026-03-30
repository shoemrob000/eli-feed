#!/usr/bin/env python3
"""Standalone ELI JBoard feed generator for GitHub Actions.

Queries Monday.com for approved opportunities and writes index.html
to the current directory (eli-feed repo root).

Requires: MONDAY_API_TOKEN environment variable
Run from: eli-feed repo root
"""
import json
import os
import re
from datetime import date, timedelta
from pathlib import Path

import requests

MONDAY_API_TOKEN = os.environ["MONDAY_API_TOKEN"]
MONDAY_BOARD_ID = 18406083209

COL_IDS = [
    "long_text_mm1xk79e",   # Description
    "text_mm1xtwvz",         # Organization
    "color_mm1xqs13",        # ELI Category
    "text_mm1xrs09",         # Location
    "link_mm1xm97c",         # Application URL
    "date_mm1xzjpp",         # Application Deadline
    "color_mm1x83bw",        # Review Status
    "date_mm1xb7me",         # Date Found
    "text_mm1xk54r",         # Time Commitment
    "text_mm1x82h0",         # Residency Requirement
    "text_mm1xjj2d",         # Skills/Expertise Sought
    "text_mm1xax9d",         # Contact Name
    "email_mm1xw4yg",        # Contact Email
]

CAT_COLORS = {
    "Government Commission": ("#0e7c3a", "#e6f4ea"),
    "Board Position": ("#1a56db", "#e8f0fe"),
    "Volunteer Position": ("#b45309", "#fef3c7"),
    "Leadership Development": ("#7c3aed", "#ede9fe"),
}


def _monday_query(query_str, variables=None):
    headers = {
        "Authorization": MONDAY_API_TOKEN,
        "Content-Type": "application/json",
    }
    payload = {"query": query_str}
    if variables:
        payload["variables"] = variables
    resp = requests.post(
        "https://api.monday.com/v2", json=payload, headers=headers, timeout=30
    )
    resp.raise_for_status()
    data = resp.json()
    if "errors" in data:
        raise RuntimeError(f"Monday API error: {data['errors']}")
    return data["data"]


def get_approved_items():
    col_ids_str = '", "'.join(COL_IDS)
    query_str = """
    query ($boardId: [ID!]!) {
        boards(ids: $boardId) {
            items_page(limit: 500) {
                items {
                    id
                    name
                    group { id title }
                    column_values(ids: ["%s"]) {
                        id text value
                    }
                }
            }
        }
    }
    """ % col_ids_str

    data = _monday_query(query_str, {"boardId": [str(MONDAY_BOARD_ID)]})
    all_items = data["boards"][0]["items_page"]["items"]

    approved = []
    for item in all_items:
        group_title = item.get("group", {}).get("title", "")
        review_status = ""
        for cv in item["column_values"]:
            if cv["id"] == "color_mm1x83bw":
                review_status = cv.get("text", "")
        if "approved" in group_title.lower() or "approved" in review_status.lower():
            parsed = {"id": item["id"], "name": item["name"]}
            for cv in item["column_values"]:
                parsed[cv["id"]] = cv.get("text", "") or ""
                if cv.get("value") and cv["id"].startswith("link_"):
                    try:
                        val = json.loads(cv["value"])
                        if isinstance(val, dict) and val.get("url"):
                            parsed[cv["id"] + "_url"] = val["url"]
                    except (json.JSONDecodeError, TypeError):
                        pass
            approved.append(parsed)
    return approved


def make_slug(title):
    slug = title.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug[:80]


def build_jsonld(item):
    title = item.get("name", "Untitled Opportunity")
    description = item.get("long_text_mm1xk79e", "")
    org_name = item.get("text_mm1xtwvz", "")
    location = item.get("text_mm1xrs09", "")
    apply_url = item.get("link_mm1xm97c_url", "")
    deadline = item.get("date_mm1xzjpp", "")
    date_found = item.get("date_mm1xb7me", "")
    category = item.get("color_mm1xqs13", "")

    emp_type = "VOLUNTEER"
    if "leadership" in category.lower():
        emp_type = "OTHER"

    city = location.split(",")[0].strip() if location else ""
    valid_through = deadline
    if not valid_through:
        try:
            posted = date.fromisoformat(date_found) if date_found else date.today()
            valid_through = (posted + timedelta(days=90)).isoformat()
        except ValueError:
            valid_through = (date.today() + timedelta(days=90)).isoformat()

    date_posted = date_found or date.today().isoformat()
    jsonld = {
        "@context": "https://schema.org/",
        "@type": "JobPosting",
        "title": title,
        "description": description or f"Community leadership opportunity: {title}",
        "datePosted": date_posted,
        "validThrough": f"{valid_through}T23:59:59",
        "employmentType": emp_type,
        "hiringOrganization": {
            "@type": "Organization",
            "name": org_name or "Eastside Leadership Initiative",
        },
        "jobLocation": {
            "@type": "Place",
            "address": {
                "@type": "PostalAddress",
                "addressLocality": city,
                "addressRegion": "WA",
                "addressCountry": "US",
            },
        },
        "identifier": {
            "@type": "PropertyValue",
            "name": "ELI Monday ID",
            "value": f"eli-{item.get('id', '')}",
        },
    }
    if apply_url:
        jsonld["url"] = apply_url
        jsonld["directApply"] = True
    return jsonld


def generate_html(items):
    cards_html = ""
    jsonld_scripts = ""

    for item in items:
        title = item.get("name", "")
        org = item.get("text_mm1xtwvz", "")
        location = item.get("text_mm1xrs09", "")
        description = item.get("long_text_mm1xk79e", "")
        apply_url = item.get("link_mm1xm97c_url", "")
        deadline = item.get("date_mm1xzjpp", "")
        category = item.get("color_mm1xqs13", "")
        time_commit = item.get("text_mm1xk54r", "")
        residency = item.get("text_mm1x82h0", "")
        skills = item.get("text_mm1xjj2d", "")
        contact = item.get("text_mm1xax9d", "")
        contact_email = item.get("email_mm1xw4yg", "")
        slug = make_slug(title)
        badge_fg, badge_bg = CAT_COLORS.get(category, ("#555", "#f0f0f0"))
        desc_preview = (description[:250].rsplit(" ", 1)[0] + "...") if len(description) > 250 else description
        desc_preview = desc_preview.replace("\n", " ").replace("\r", " ")

        pills = ""
        if location:
            pills += f'<span class="pill loc">{location}</span>'
        if deadline:
            pills += f'<span class="pill deadline">Deadline: {deadline}</span>'
        if time_commit:
            pills += f'<span class="pill time">{time_commit}</span>'

        apply_btn = f'<a href="{apply_url}" class="apply-btn" target="_blank" rel="noopener">Apply Now</a>' if apply_url else ""

        details = ""
        if residency:
            details += f'<p class="detail"><strong>Residency:</strong> {residency}</p>'
        if skills:
            details += f'<p class="detail"><strong>Looking for:</strong> {skills}</p>'
        if contact:
            cs = contact + (f' (<a href="mailto:{contact_email}">{contact_email}</a>)' if contact_email else "")
            details += f'<p class="detail"><strong>Contact:</strong> {cs}</p>'

        cards_html += f"""
        <article class="opp-card" id="{slug}">
            <div class="card-header">
                <span class="category-badge" style="color:{badge_fg};background:{badge_bg}">{category}</span>
                <span class="org">{org}</span>
            </div>
            <h2><a href="#{slug}">{title}</a></h2>
            <div class="pills">{pills}</div>
            <p class="desc">{desc_preview}</p>
            {details}
            <div class="card-footer">{apply_btn}</div>
        </article>
        """
        jsonld_scripts += f'<script type="application/ld+json">{json.dumps(build_jsonld(item), indent=2)}</script>\n'

    today = date.today().isoformat()
    count = len(items)
    empty = '<div class="empty-state"><p>No approved opportunities at this time. Check back soon!</p></div>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Eastside Leadership Initiative - Open Opportunities</title>
    <meta name="description" content="Board seats, government commissions, volunteer positions, and leadership development programs across the Eastside.">
    {jsonld_scripts}
    <style>
        :root {{--primary:#003366;--accent:#0066cc;--accent-light:#e8f0fe;--text:#1a1a1a;--text-muted:#555;--border:#e0e0e0;--bg:#f8f9fa;--white:#fff;--radius:10px;}}
        *{{margin:0;padding:0;box-sizing:border-box;}}
        body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;background:var(--bg);color:var(--text);line-height:1.6;}}
        header{{background:var(--primary);color:white;padding:2rem 1.5rem;text-align:center;}}
        header h1{{font-size:1.75rem;font-weight:700;margin-bottom:.25rem;}}
        header p{{opacity:.85;font-size:1rem;max-width:600px;margin:0 auto;}}
        .subheader{{background:var(--white);border-bottom:1px solid var(--border);padding:.75rem 1.5rem;text-align:center;font-size:.875rem;color:var(--text-muted);}}
        .container{{max-width:860px;margin:1.5rem auto;padding:0 1rem;}}
        .opp-card{{background:var(--white);border:1px solid var(--border);border-radius:var(--radius);padding:1.5rem;margin-bottom:1rem;transition:box-shadow .15s;}}
        .opp-card:hover{{box-shadow:0 2px 12px rgba(0,0,0,.08);}}
        .card-header{{display:flex;align-items:center;gap:.75rem;margin-bottom:.5rem;flex-wrap:wrap;}}
        .category-badge{{font-size:.75rem;font-weight:600;padding:.2rem .6rem;border-radius:99px;text-transform:uppercase;letter-spacing:.03em;}}
        .org{{font-size:.85rem;color:var(--text-muted);font-weight:500;}}
        .opp-card h2{{font-size:1.15rem;font-weight:600;margin-bottom:.5rem;}}
        .opp-card h2 a{{color:var(--text);text-decoration:none;}}
        .opp-card h2 a:hover{{color:var(--accent);}}
        .pills{{display:flex;gap:.5rem;flex-wrap:wrap;margin-bottom:.75rem;}}
        .pill{{font-size:.75rem;padding:.2rem .5rem;background:#f0f0f0;border-radius:4px;color:var(--text-muted);}}
        .pill.deadline{{background:#fff3cd;color:#856404;}}
        .desc{{font-size:.9rem;color:var(--text-muted);margin-bottom:.75rem;}}
        .detail{{font-size:.85rem;color:var(--text-muted);margin-bottom:.25rem;}}
        .detail a{{color:var(--accent);}}
        .card-footer{{margin-top:1rem;display:flex;gap:.75rem;}}
        .apply-btn{{display:inline-block;background:var(--accent);color:white;padding:.5rem 1.25rem;border-radius:6px;text-decoration:none;font-size:.875rem;font-weight:600;transition:background .15s;}}
        .apply-btn:hover{{background:#0052a3;}}
        footer{{text-align:center;padding:2rem 1rem;color:var(--text-muted);font-size:.8rem;border-top:1px solid var(--border);margin-top:2rem;}}
        footer a{{color:var(--accent);text-decoration:none;}}
        .empty-state{{text-align:center;padding:3rem 1rem;color:var(--text-muted);}}
        @media(max-width:600px){{header h1{{font-size:1.35rem;}}.opp-card{{padding:1rem;}}}}
    </style>
</head>
<body>
    <header>
        <h1>Eastside Leadership Initiative</h1>
        <p>Connecting Eastside leaders with service, training, and professional development</p>
    </header>
    <div class="subheader">
        {count} open opportunit{"ies" if count != 1 else "y"} &middot; Updated {today} &middot;
        <a href="https://eli.bellevuechamber.org" target="_blank">View full board at eli.bellevuechamber.org</a>
    </div>
    <div class="container">
        {cards_html if cards_html else empty}
    </div>
    <footer>
        <p>Powered by the <a href="https://www.bellevuechamber.org/eli/">Bellevue Chamber of Commerce</a> Eastside Leadership Initiative</p>
        <p>This page is auto-generated from approved opportunities. Visit <a href="https://eli.bellevuechamber.org">eli.bellevuechamber.org</a> for the full searchable board.</p>
    </footer>
</body>
</html>"""


if __name__ == "__main__":
    print("=== ELI JBoard Feed Generator (GitHub Actions) ===")
    print("Fetching approved items from Monday.com...")
    items = get_approved_items()
    print(f"  Found {len(items)} approved opportunities")

    html = generate_html(items)
    Path("index.html").write_text(html, encoding="utf-8")
    print(f"  Written index.html ({len(html):,} bytes)")
    print("  Done. GitHub Actions will commit and push.")
