"""Multi-sheet evaluation-workbook ingestion.

The official workbook holds Read_Me + BLIND_01..BLIND_07, each an
independent 12-second scenario at 100 ms. Requirements under test:
sheet discovery and validation (non-data sheets ignored), NO silent
sheet choice and NO concatenation, per-sheet duration from that sheet's
Relative Time axis, a completely fresh engine per scenario, and
sheet-name independence of the algorithm.
"""

import pytest

from engine.npw import PIPELINE_LENGTH_M
from server.batch import evaluate_path
from simulator.generate import make_mock_workbook, write_csv
from streaming.loader import (load as load_telemetry, inspect_sheets,
                              MultiSheetWorkbook)


@pytest.fixture(scope="module")
def workbook(tmp_path_factory):
    path = tmp_path_factory.mktemp("wb") / "evaluation_workbook.xlsx"
    specs = make_mock_workbook(str(path))
    return str(path), specs


def test_sheet_discovery_ignores_readme(workbook):
    path, specs = workbook
    sheets = inspect_sheets(path)
    by_name = {s["sheet"]: s for s in sheets}
    assert not by_name["Read_Me"]["valid"]          # non-data sheet ignored
    valid = [s["sheet"] for s in sheets if s["valid"]]
    assert valid == [f"BLIND_{i:02d}" for i in range(1, 8)]


def test_no_silent_choice_or_concatenation(workbook):
    path, _ = workbook
    with pytest.raises(MultiSheetWorkbook) as exc:
        load_telemetry(path)                        # no sheet specified
    assert len(exc.value.sheets) == 7
    assert "select a scenario" in str(exc.value).lower()


def test_sheet_duration_uses_own_relative_time(workbook):
    path, _ = workbook
    tel = load_telemetry(path, sheet="BLIND_03")
    assert tel.sheet == "BLIND_03"
    assert tel.validation["sheet"] == "BLIND_03"
    assert tel.validation["samples"] == 121          # 12 s @ 100 ms
    assert tel.validation["sample_dt_ms"] == 100.0
    # ends at ~T+12.0 s — proof sheets were not concatenated (7 x 12 = 84 s)
    assert abs(tel.times_s[-1] - 12.0) < 0.2


def test_every_sheet_processed_independently(workbook):
    """Fresh engine per sheet: six leaks localized on their own truths,
    the control silent — no state leaks between scenarios."""
    path, specs = workbook
    for i in range(1, 7):
        sheet = f"BLIND_{i:02d}"
        row = evaluate_path(path, sheet=sheet)
        truth = specs[sheet].leak_x_m
        assert row["leak_detected"], f"{sheet} not detected: {row}"
        assert abs(row["x_m"] - truth) <= 200.0, f"{sheet}: {row}"
        assert abs(row["x_m"] + row["x_out_m"] - PIPELINE_LENGTH_M) < 1e-6
        assert row["duration_s"] <= 12.5
    control = evaluate_path(path, sheet="BLIND_07")
    assert not control["leak_detected"]
    assert not control["isolated"]
    assert control["final_state"] in ("NORMAL", "ANOMALY_SUSPECTED")


def test_order_independence_no_cross_talk(workbook):
    """Processing the control right after a deep leak must give exactly
    the same result as processing it alone."""
    path, _ = workbook
    alone = evaluate_path(path, sheet="BLIND_07")
    evaluate_path(path, sheet="BLIND_01")            # deep leak first
    after = evaluate_path(path, sheet="BLIND_07")
    for key in ("leak_detected", "t_in", "t_out", "final_state", "isolated"):
        assert alone[key] == after[key]


def test_sheet_name_is_not_a_detection_input(workbook, tmp_path):
    """The same telemetry under a different sheet/file identity produces
    identical results — names are labels only."""
    path, _ = workbook
    tel = load_telemetry(path, sheet="BLIND_02")
    csv_copy = tmp_path / "totally_unrelated_name.csv"
    write_csv(str(csv_copy), tel.times_s, tel.p_in, tel.p_out)
    a = evaluate_path(path, sheet="BLIND_02")
    b = evaluate_path(str(csv_copy))
    for key in ("leak_detected", "t_in", "t_out", "delta_t", "x_m",
                "x_out_m", "segment", "final_state", "isolated"):
        assert a[key] == b[key], key
