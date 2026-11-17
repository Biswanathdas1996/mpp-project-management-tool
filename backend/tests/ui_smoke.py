"""Browser smoke test over the running app (real UI → real API → real MPXJ parsing).

    python tests/ui_smoke.py http://127.0.0.1:8000 admin@pma.local <password> <samples_dir> <screenshot_dir>

Fails (exit 1) on any uncaught JS error, console error or failed API call (status >= 500).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE, EMAIL, PWD, SAMPLES, SHOTS = sys.argv[1:6]
shots = Path(SHOTS)
shots.mkdir(parents=True, exist_ok=True)
files = sorted(Path(SAMPLES).glob("*.xml"))
problems: list[str] = []


def snap(page, name):
    page.screenshot(path=str(shots / f"{name}.png"), full_page=True)


with sync_playwright() as p:
    try:
        browser = p.chromium.launch()
    except Exception:
        browser = p.chromium.launch(channel="msedge")  # fall back to the system Edge browser
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    page.on("pageerror", lambda e: problems.append(f"pageerror: {e}"))
    page.on("console", lambda m: m.type == "error" and "favicon" not in m.text and problems.append(f"console: {m.text}"))
    page.on("response", lambda r: r.status >= 500 and problems.append(f"HTTP {r.status} {r.url}"))

    page.goto(f"{BASE}/login")
    page.fill("input[type=email]", EMAIL)
    page.fill("input[type=password]", PWD)
    page.click("button:has-text('Sign in')")
    page.wait_for_url("**/programs")
    snap(page, "01_programs_empty")

    # Create program
    page.click("text=+ New program")
    page.fill("#np input >> nth=0", "National Digital Services Programme")
    page.fill("#np input >> nth=1", "برنامج الخدمات الرقمية الوطنية")
    page.fill("#np input >> nth=2", "Ministry of Digital Government")
    page.fill("#np input >> nth=3", "وزارة الحكومة الرقمية")
    page.fill("#np input >> nth=4", "Steering Committee Report")
    page.fill("#np input >> nth=5", "Riyadh")
    page.click("button:has-text('Create')")
    page.wait_for_url("**/snapshots")

    # Upload first snapshot through the UI
    page.set_input_files("input[type=file]", str(files[0]))
    page.click("button:has-text('Upload 1 file')")
    page.wait_for_selector("text=Awaiting mapping", timeout=600000)
    snap(page, "02_snapshots_awaiting_mapping")

    # Mapping wizard
    page.click("text=Open mapping wizard")
    page.wait_for_selector("text=What's in the file")
    snap(page, "03_mapping_profile")
    page.click("button:has-text('Next: tracks')")
    page.wait_for_selector("text=Track 07")
    snap(page, "04_mapping_tracks")
    page.click("button:has-text('Next: milestones')")
    page.select_option("section.card select >> nth=0", "outline_level")
    page.select_option("section.card select >> nth=1", "2")
    page.wait_for_selector("text=14")
    time.sleep(0.5)
    snap(page, "05_mapping_milestones")
    page.click("button:has-text('Next') >> nth=-1")
    page.click("button:has-text('Next: KPIs')")
    snap(page, "06_mapping_kpis")
    page.click("button:has-text('Approve mapping')")
    page.wait_for_selector("text=Mapping approved", timeout=15000)
    time.sleep(3)

    # Bulk upload remaining snapshots
    pid = page.url.split("/p/")[1].split("/")[0]
    page.goto(f"{BASE}/p/{pid}/snapshots")
    page.set_input_files("input[type=file]", [str(f) for f in files[1:]])
    page.click(f"button:has-text('Upload {len(files) - 1} file')")
    t0 = time.time()
    while time.time() - t0 < 1500:
        if page.locator("td .pill:has-text('Ready')").count() == len(files):
            break
        time.sleep(1)
    else:
        problems.append("snapshots did not all become Ready")
    snap(page, "07_snapshots_ready")

    # Governance data through the UI
    page.goto(f"{BASE}/p/{pid}/decisions")
    page.click("text=+ Add")
    page.fill("#dec-form input >> nth=0", "Approve two additional front-end developers")
    page.fill("#dec-form textarea", "Portal build is 40 pts behind plan; capacity needed to recover Q1 launch.")
    page.select_option("#dec-form select >> nth=1", "High")
    page.fill("#dec-form input >> nth=2", "Programme Director")
    page.fill("#dec-form input[type=date]", "2026-11-20")
    page.click("button:has-text('Save')")
    page.wait_for_selector("text=Approve two additional")
    page.goto(f"{BASE}/p/{pid}/risks")
    page.click("text=+ Add")
    page.fill("#risk-form input >> nth=0", "Citizen portal launch slips past Q1 2027")
    page.fill("#risk-form textarea >> nth=1", "Add capacity; descope phase-2 e-services")
    page.select_option("#risk-form select >> nth=0", "High")
    page.fill("#risk-form input >> nth=2", "Portal Lead")
    page.fill("#risk-form input[type=date]", "2026-11-01")
    page.click("button:has-text('Save')")
    page.wait_for_selector("text=Citizen portal launch slips")

    pages = ["overview", "tracks", "milestones", "timeline", "decisions", "risks", "attention", "changes", "kpis",
             "insights", "snapshots", "mapping", "settings"]
    for i, name in enumerate(pages, start=10):
        page.goto(f"{BASE}/p/{pid}/{name}")
        page.wait_for_load_state("networkidle")
        time.sleep(0.6)
        snap(page, f"{i}_{name}")

    # Drill-down from a KPI card
    page.goto(f"{BASE}/p/{pid}/overview")
    page.wait_for_load_state("networkidle")
    page.click("button[aria-label^='Program Completion']")
    page.wait_for_selector("text=Underlying tasks")
    time.sleep(0.5)
    snap(page, "30_drilldown")
    page.keyboard.press("Escape")
    page.click("button[aria-label='Close']")

    for path, name in (("/portfolio", "31_portfolio"), ("/alerts", "32_alerts"), ("/admin/users", "33_users"),
                       ("/admin/organisation", "34_org"), ("/admin/alert-rules", "35_rules"), ("/admin/audit", "36_audit"),
                       ("/admin/ai-logs", "37_ailogs"), ("/platform/tenants", "38_tenants"), ("/account", "39_account")):
        page.goto(BASE + path)
        page.wait_for_load_state("networkidle")
        time.sleep(0.4)
        snap(page, name)

    # Arabic / RTL + dark mode
    page.goto(f"{BASE}/p/{pid}/overview")
    page.wait_for_load_state("networkidle")
    page.click("button[aria-label='Toggle theme']")  # dark mode (label is still English here)
    page.click("button:has-text('العربية')")
    time.sleep(1)
    if page.evaluate("document.documentElement.dir") != "rtl":
        problems.append("RTL not applied")
    snap(page, "40_overview_ar_dark")
    page.goto(f"{BASE}/p/{pid}/timeline")
    page.wait_for_load_state("networkidle")
    time.sleep(0.6)
    snap(page, "41_timeline_ar_dark")

    # Phone width
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{BASE}/p/{pid}/overview")
    page.wait_for_load_state("networkidle")
    time.sleep(0.6)
    snap(page, "42_overview_mobile")
    browser.close()

print("\n".join(problems) if problems else "NO PROBLEMS")
sys.exit(1 if problems else 0)
