"""Unit tests for ml/practice_stats.py (Issue #10 quadrants, pandas mirror).

Skipped when pandas is unavailable so the rest of the suite still runs.
"""

import pathlib
import sys

import pytest

pd = pytest.importorskip("pandas")

# ml/ is not on the default test path (conftest only adds de/ingestion).
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "ml"))

from practice_stats import MIN_SAMPLE, _score_vs_base, practice_stats  # noqa: E402


def _cell(out, param, value):
    rows = out[(out.param_name == param) & (out.param_value == value)]
    assert len(rows) == 1, f"expected one row for {param}={value}"
    return rows.iloc[0]


def test_score_vs_base_demeans_within_base_model():
    df = pd.DataFrame({
        "model_id": ["a1", "a2", "b1"],
        "base_model": ["A", "A", "B"],
        "composite_success_score": [0.6, 0.8, 0.2],
    })
    svb = _score_vs_base(df)
    assert round(svb.iloc[0], 4) == -0.1   # A mean 0.7
    assert round(svb.iloc[1], 4) == 0.1
    assert round(svb.iloc[2], 4) == 0.0    # B mean 0.2 (only member)


def _opt_frame():
    rows = []
    for i in range(3):
        rows.append({"model_id": f"g{i}", "base_model": "B",
                     "composite_success_score": 0.9, "optimizer": "good"})
    for i in range(3):
        rows.append({"model_id": f"b{i}", "base_model": "B",
                     "composite_success_score": 0.1, "optimizer": "bad"})
    rows.append({"model_id": "r0", "base_model": "B",
                 "composite_success_score": 0.95, "optimizer": "rare"})
    return pd.DataFrame(rows)


def test_quadrant_columns_and_accepted_values():
    out = practice_stats(_opt_frame())
    expected = {"param_name", "param_value", "prevalence", "avg_success_score",
                "avg_score_vs_base", "score_lift", "sample_ok", "quadrant"}
    assert expected.issubset(out.columns)
    assert out["quadrant"].isin(
        ["common+works", "common+fails", "rare+works", "rare+fails"]
    ).all()


def test_quadrants_use_stratified_score_and_prevalence():
    out = practice_stats(_opt_frame())
    assert _cell(out, "optimizer", "good")["quadrant"] == "common+works"
    assert _cell(out, "optimizer", "bad")["quadrant"] == "common+fails"
    rare = _cell(out, "optimizer", "rare")
    assert rare["quadrant"] == "rare+works"
    assert rare["prevalence"] == 1


def test_sample_ok_min_sample_gate():
    out = practice_stats(_opt_frame())
    assert bool(_cell(out, "optimizer", "good")["sample_ok"]) is True   # prevalence 3
    assert bool(_cell(out, "optimizer", "rare")["sample_ok"]) is False  # prevalence 1


def test_sample_ok_boundary():
    rows = [{"model_id": f"a{i}", "base_model": "B",
             "composite_success_score": 0.5, "optimizer": "at_threshold"}
            for i in range(MIN_SAMPLE)]
    rows += [{"model_id": f"b{i}", "base_model": "B",
              "composite_success_score": 0.5, "optimizer": "below_threshold"}
             for i in range(MIN_SAMPLE - 1)]
    out = practice_stats(pd.DataFrame(rows))
    assert bool(_cell(out, "optimizer", "at_threshold")["sample_ok"]) is True
    assert bool(_cell(out, "optimizer", "below_threshold")["sample_ok"]) is False


def test_score_lift_is_relative_to_param_mean():
    out = practice_stats(_opt_frame())
    # pooled mean over the 7 optimizer rows; "good" (0.9) sits above it.
    assert _cell(out, "optimizer", "good")["score_lift"] > 0
    assert _cell(out, "optimizer", "bad")["score_lift"] < 0
