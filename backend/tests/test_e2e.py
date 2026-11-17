"""End-to-end: upload → mapping → snapshot → diff → dashboard → governance → exports, plus RBAC."""
from __future__ import annotations

import time

from .conftest import wait_for

STATE: dict = {}


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}
    r = client.get("/api/ready")
    assert r.status_code == 200 and r.json()["ready"]


def test_auth_required(client):
    assert client.get("/api/programs").status_code == 401


def test_create_program(client, admin_headers):
    r = client.post("/api/programs", headers=admin_headers, json={
        "name": "National Digital Services Programme", "name_ar": "برنامج الخدمات الرقمية الوطنية",
        "client_name": "Ministry of Digital Government", "client_name_ar": "وزارة الحكومة الرقمية",
        "subtitle": "Steering Committee Report", "location": "Riyadh", "reporting_cycle_days": 7})
    assert r.status_code == 201, r.text
    STATE["pid"] = r.json()["id"]


def test_first_upload_awaits_mapping(client, admin_headers, sample_files):
    pid = STATE["pid"]
    with open(sample_files[0], "rb") as fh:
        r = client.post(f"/api/programs/{pid}/snapshots", headers=admin_headers,
                        files=[("files", (sample_files[0].name, fh, "application/xml"))])
    assert r.status_code == 202, r.text
    sid = r.json()["results"][0]["snapshot"]["id"]
    s = wait_for(client, admin_headers, sid, {"awaiting_mapping", "failed"})
    assert s["status"] == "awaiting_mapping", s
    assert s["as_of"] == "2026-10-19" and s["as_of_source"] == "status_date"
    STATE["s1"] = sid
    # processing log: ordered, covers the pipeline stages, ends with a final event
    ev = client.get(f"/api/snapshots/{sid}/events", headers=admin_headers).json()["events"]
    assert [e["seq"] for e in ev] == list(range(1, len(ev) + 1))
    stages = {e["stage"] for e in ev}
    assert {"upload", "parse", "store", "profile", "discovery", "mapping", "done"} <= stages
    assert any(e["message"].startswith("Read ") and "tasks" in e["message"] for e in ev)
    assert ev[-1]["data"]["final"] and ev[-1]["data"]["status"] == "awaiting_mapping"


def test_duplicate_rejected(client, admin_headers, sample_files):
    with open(sample_files[0], "rb") as fh:
        r = client.post(f"/api/programs/{STATE['pid']}/snapshots", headers=admin_headers,
                        files=[("files", (sample_files[0].name, fh, "application/xml"))])
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "duplicate"


def test_bad_file_reports_parse_error(client, admin_headers):
    r = client.post(f"/api/programs/{STATE['pid']}/snapshots", headers=admin_headers,
                    files=[("files", ("broken.mpp", b"\xd0\xcf\x11\xe0garbage" * 50, "application/octet-stream"))])
    assert r.status_code == 202
    sid = r.json()["results"][0]["snapshot"]["id"]
    s = wait_for(client, admin_headers, sid, {"failed", "ready", "awaiting_mapping"})
    assert s["status"] == "failed" and s["error_report"]["code"] in ("corrupt_file", "unsupported_format")
    # SSE stream replays the log, reports the parse error and closes with an `end` event
    with client.stream("GET", f"/api/snapshots/{sid}/events/stream", headers=admin_headers) as resp:
        assert resp.headers["content-type"].startswith("text/event-stream")
        body = "".join(resp.iter_text())
    assert "event: progress" in body and body.rstrip().splitlines()[-2] == "event: end"
    assert '"level": "error"' in body and '"status": "failed"' in body
    assert client.delete(f"/api/snapshots/{sid}", headers=admin_headers).status_code == 204


def test_mapping_proposal_and_preview(client, admin_headers):
    pid = STATE["pid"]
    m = client.get(f"/api/programs/{pid}/mapping", headers=admin_headers).json()
    assert m["proposed"]["track_rule"] == {"type": "outline_level", "level": 1}
    assert len(m["proposed"]["proposed_kpis"]) > 20
    r = client.post(f"/api/programs/{pid}/mapping/preview", headers=admin_headers, json={
        "track_rule": {"type": "custom_field", "field": "Text1"}, "milestone_rule": {"type": "outline_level", "level": 2}})
    assert r.status_code == 200
    assert len(r.json()["tracks"]) == 7 and r.json()["milestone_count"] == 14


def test_approve_mapping_and_bulk_upload(client, admin_headers, sample_files):
    pid = STATE["pid"]
    catalogue = client.get("/api/kpi-catalogue", headers=admin_headers).json()
    approved = [k["code"] for k in catalogue if not k["reference"]]
    r = client.post(f"/api/programs/{pid}/mapping/approve", headers=admin_headers, json={
        "track_rule": {"type": "outline_level", "level": 1}, "milestone_rule": {"type": "outline_level", "level": 2},
        "planned_method": "auto", "approved_kpis": approved})
    assert r.status_code == 200, r.text
    wait_for(client, admin_headers, STATE["s1"], {"ready", "failed"})
    files = [("files", (p.name, open(p, "rb"), "application/xml")) for p in sample_files[1:]]
    r = client.post(f"/api/programs/{pid}/snapshots", headers=admin_headers, files=files)
    for _, (_, fh, _) in files:
        fh.close()
    assert r.status_code == 202
    ids = [x["snapshot"]["id"] for x in r.json()["results"]]
    for sid in ids:
        s = wait_for(client, admin_headers, sid, {"ready", "failed"})
        assert s["status"] == "ready", s
    STATE["latest"] = ids[-1]
    STATE["ids"] = [STATE["s1"]] + ids


def test_dashboard_reference_spec(client, admin_headers):
    d = client.get(f"/api/programs/{STATE['pid']}/dashboard", headers=admin_headers).json()
    assert d["snapshot"]["id"] == STATE["latest"]
    assert d["header"]["title"] == "National Digital Services Programme - Executive Dashboard"
    assert d["kpi_strip"]["tracks"] == 7
    assert d["cards"]["active_tracks"]["total"] == 7
    assert d["cards"]["active_tracks"]["pending"] >= 1  # security track not yet started
    assert d["kpi_strip"]["milestones"] == 14
    assert 0 < d["cards"]["program_completion"]["value"] < 100
    assert d["cards"]["program_completion"]["tag"] in ("On Track", "Delay", "Critical Delay")
    statuses = {m["status"] for m in d["milestones"]}
    assert {"completed", "not_started"} <= statuses and statuses & {"delay", "critical_delay"}
    assert all(m["health"]["label"] for m in d["milestones"])
    assert d["gantt"]["months"] and d["gantt"]["items"]
    assert d["trend"]["cycles_reported"] == 4
    pts = d["trend"]["points"]
    assert all(p["planned"] is not None and p["actual"] is not None for p in pts)
    assert d["cards"]["next_milestone"]["available"]
    assert d["cards"]["active_track_timeline"]["value"] >= 6


def test_kpis_and_drilldown(client, admin_headers):
    sid = STATE["latest"]
    k = {x["code"]: x for x in client.get(f"/api/snapshots/{sid}/kpis", headers=admin_headers).json()["kpis"]}
    for code in ("spi", "bei", "cpi", "eac", "critical_path", "logic_health_score", "weekly_velocity", "s_curve",
                 "burn_up", "stalled_tasks", "change_summary", "scope_growth", "resource_allocation", "overdue_tasks"):
        assert k[code]["available"], (code, k[code].get("reason"))
    assert k["change_summary"]["details"]["removed"] >= 1
    assert k["scope_growth"]["value"] is not None
    r = client.get(f"/api/snapshots/{sid}/drill", params={"kpi": "overdue_tasks"}, headers=admin_headers).json()
    assert r["count"] == k["overdue_tasks"]["value"]
    d = client.get(f"/api/programs/{STATE['pid']}/dashboard", headers=admin_headers).json()
    ms = d["milestones"][0]
    r = client.get(f"/api/snapshots/{sid}/drill", params={"milestone_id": ms["id"]}, headers=admin_headers).json()
    assert r["count"] >= 2
    tr = d["tracks"][0]
    r = client.get(f"/api/snapshots/{sid}/drill", params={"track_id": tr["id"]}, headers=admin_headers).json()
    assert r["count"] > 0


def test_diff_what_changed(client, admin_headers):
    ids = STATE["ids"]
    v2 = client.get(f"/api/snapshots/{ids[1]}/diff", headers=admin_headers).json()
    assert v2["summary"]["renamed"] >= 1
    v3 = client.get(f"/api/snapshots/{ids[2]}/diff", headers=admin_headers).json()
    assert v3["summary"]["by_type"].get("added", 0) >= 1
    v4 = client.get(f"/api/snapshots/{ids[3]}/diff", headers=admin_headers).json()
    assert v4["summary"]["by_type"].get("removed", 0) >= 1
    cmp = client.get(f"/api/snapshots/{ids[3]}/diff", params={"compare_to": ids[0]}, headers=admin_headers).json()
    assert cmp["base"]["id"] == ids[0] and cmp["summary"]["total"] > 0
    bl = client.get(f"/api/snapshots/{ids[3]}/diff", params={"compare_to": "baseline"}, headers=admin_headers).json()
    assert bl["summary"]["slipped"] > 0
    hist = client.get(f"/api/programs/{STATE['pid']}/milestone-history", headers=admin_headers).json()
    assert hist and len(hist[0]["points"]) == 4


def test_governance_crud_and_live_kpis(client, admin_headers):
    pid = STATE["pid"]
    r = client.post(f"/api/programs/{pid}/decisions", headers=admin_headers, json={
        "title": "Approve additional front-end capacity", "description": "Two FTE for the portal build",
        "priority": "High", "owner": "Programme Director", "needed_by": "2026-11-20"})
    assert r.status_code == 201
    r = client.post(f"/api/programs/{pid}/risks", headers=admin_headers, json={
        "title": "Portal launch slips past Q1", "severity": "High", "mitigation": "Add capacity; descope phase 2",
        "owner": "Portal Lead", "due_date": "2026-11-01"})
    assert r.status_code == 201
    d = client.get(f"/api/programs/{pid}/dashboard", headers=admin_headers).json()
    assert d["cards"]["decisions_required"]["value"] == 1 and d["cards"]["decisions_required"]["high_priority"] == 1
    assert d["cards"]["high_risks"]["value"] == 1
    assert any(a["category"] == "overdue_mitigation" for a in d["attention"]["derived"])


def test_exports(client, admin_headers):
    sid = STATE["latest"]
    for fmt, magic in (("pdf", b"%PDF"), ("xlsx", b"PK"), ("pptx", b"PK")):
        r = client.get(f"/api/snapshots/{sid}/export/{fmt}", headers=admin_headers)
        assert r.status_code == 200, (fmt, r.text[:300])
        assert r.content.startswith(magic) and len(r.content) > 5000


def test_ai_off_degrades_gracefully(client, admin_headers):
    r = client.post(f"/api/snapshots/{STATE['latest']}/insights/executive_summary", headers=admin_headers)
    assert r.status_code == 503
    assert client.get("/api/ai/status", headers=admin_headers).json()["enabled"] is False


def test_rbac_roles(client, admin_headers):
    for email, role in (("viewer@test.local", "super_viewer"), ("editor@test.local", "pmo_editor")):
        r = client.post("/api/users", headers=admin_headers,
                        json={"email": email, "full_name": role, "role": role, "password": "Password1234"})
        assert r.status_code == 201
    tok = lambda e: {"Authorization": "Bearer " + client.post("/api/auth/login", json={"email": e, "password": "Password1234"}).json()["access_token"]}  # noqa: E731
    v, e = tok("viewer@test.local"), tok("editor@test.local")
    pid = STATE["pid"]
    assert client.get(f"/api/programs/{pid}/dashboard", headers=v).status_code == 200
    assert client.post(f"/api/programs/{pid}/risks", headers=v, json={"title": "x"}).status_code == 403
    assert client.post(f"/api/programs/{pid}/risks", headers=e, json={"title": "Editor risk"}).status_code == 201
    assert client.post(f"/api/programs/{pid}/mapping/approve", headers=e, json={}).status_code in (403, 422)
    assert client.get("/api/users", headers=e).status_code == 403
    assert client.get("/api/audit", headers=admin_headers).json()["total"] > 10


def test_portfolio_and_alerts(client, admin_headers):
    p = client.get("/api/portfolio", headers=admin_headers).json()
    assert p["summary"]["programs"] >= 1 and p["programs"][0]["completion"] is not None
    r = client.post("/api/alert-rules", headers=admin_headers, json={
        "name": "Behind plan", "kpi_code": "schedule_variance_pts", "operator": "<", "threshold": 100})
    assert r.status_code == 201
    # reprocess latest to trigger alert evaluation
    sid = STATE["latest"]
    client.post(f"/api/snapshots/{sid}/reprocess", headers=admin_headers)
    time.sleep(0.5)
    wait_for(client, admin_headers, sid, {"ready"})
    assert any(a["title"].endswith("Behind plan") for a in client.get("/api/alerts", headers=admin_headers).json())
