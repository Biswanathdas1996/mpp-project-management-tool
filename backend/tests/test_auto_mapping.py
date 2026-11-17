"""Automatic first-upload mapping approval (logic + AI agreement, structural checks)."""
from __future__ import annotations

import pytest

from app.config import get_settings
from app.services import auto_mapping

from .conftest import wait_for


@pytest.fixture
def auto_mode():
    s = get_settings()
    old = s.mapping_auto_approve
    s.mapping_auto_approve = "confident"
    yield
    s.mapping_auto_approve = old


def test_first_upload_is_mapped_automatically(client, admin_headers, sample_files, auto_mode):
    r = client.post("/api/programs", headers=admin_headers, json={"name": "Auto-mapped Programme"})
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    with open(sample_files[0], "rb") as fh:
        r = client.post(f"/api/programs/{pid}/snapshots", headers=admin_headers,
                        files=[("files", (sample_files[0].name, fh, "application/xml"))])
    sid = r.json()["results"][0]["snapshot"]["id"]
    s = wait_for(client, admin_headers, sid, {"ready", "awaiting_mapping", "failed"})
    assert s["status"] == "ready", s
    m = client.get(f"/api/programs/{pid}/mapping", headers=admin_headers).json()
    assert m["approved"] and m["approved"]["auto_approved"] is True and m["approved"]["approved_kpis"]
    msgs = [e["message"] for e in client.get(f"/api/snapshots/{sid}/events", headers=admin_headers).json()["events"]]
    assert any(x.startswith("Mapping approved automatically") for x in msgs)
    assert any(x.startswith("Check: ") for x in msgs)
    # the wizard still works afterwards: an admin approval replaces the automatic one
    r = client.post(f"/api/programs/{pid}/mapping/approve", headers=admin_headers, json={
        "track_rule": m["approved"]["track_rule"], "milestone_rule": m["approved"]["milestone_rule"],
        "planned_method": "auto", "approved_kpis": m["approved"]["approved_kpis"]})
    assert r.status_code == 200 and r.json()["auto_approved"] is False


def test_disagreement_needs_review():
    d = auto_mapping.evaluate([], {"track_rule": {"type": "outline_level", "level": 2},
                                   "milestone_rule": {"type": "flag"}},
                              {"track_rule": {"type": "outline_level", "level": 1}, "milestone_rule": {"type": "flag"}},
                              ai_answered=True, ai_rule_fallbacks=0, mode="confident")
    assert not d.approve and any("disagree on tracks" in r for r in d.reasons)


def test_ai_rule_fallback_needs_review():
    rule = {"track_rule": {"type": "outline_level", "level": 1}, "milestone_rule": {"type": "flag"}}
    d = auto_mapping.evaluate([], rule, rule, ai_answered=True, ai_rule_fallbacks=1, mode="confident")
    assert not d.approve and any("did not fit" in r for r in d.reasons)


def test_off_mode_never_approves():
    rule = {"track_rule": {"type": "outline_level", "level": 1}, "milestone_rule": {"type": "flag"}}
    assert not auto_mapping.evaluate([], rule, rule, True, 0, "off").approve
