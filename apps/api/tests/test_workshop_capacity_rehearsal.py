"""Offline profiles and failure accounting; never call a deployed service."""

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("capacity_rehearsal",
                                             ROOT / "scripts/workshop_capacity_rehearsal.py")
rehearsal = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rehearsal)


def test_eighty_one_profile_uses_five_approved_fixed_official_conditions():
    rows = rehearsal.cases(81)
    assert len(rows) == 81
    assert {r["conditions"]["tool"] for r in rows} == set(rehearsal.TOOLS)
    assert all(r["approved"] is True and r["mode"] == "archive" for r in rows)
    rows[0]["conditions"]["start"] = "tampered"
    assert rows[5]["conditions"]["start"] != "tampered"


def test_rehearsal_reports_model_failure_even_with_terminal_http_success():
    rows = [dict(seconds=8, result=True, waiting_seen=True, max_queue_ahead=64,
                 brief_status="complete", input_tokens=1000),
            dict(seconds=9, result=True, waiting_seen=True, max_queue_ahead=65,
                 brief_status="failed", error="brief_validation_failed", input_tokens=1001)]
    result = rehearsal.summary(rows)
    assert result["terminal_results"] == 2 and result["brief_complete"] == 1
    assert result["brief_failed"] == 1
    assert result["errors"] == {"brief_validation_failed": 1}
    assert result["input_tokens"] == 2001 and result["max_queue_ahead"] == 65
