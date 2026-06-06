"""Unit tests for ml/scoring.py (Issue #6 success score, pandas mirror).

Skipped when pandas is unavailable so the rest of the suite still runs.
"""

import pathlib
import sys

import pytest

pd = pytest.importorskip("pandas")

# ml/ is not on the default test path (conftest only adds de/ingestion).
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "ml"))

from scoring import WEIGHTS, add_success_score, _percent_rank  # noqa: E402


def test_weights_sum_to_one():
    assert round(sum(WEIGHTS.values()), 6) == 1.0


def test_percent_rank_endpoints():
    pr = _percent_rank(pd.Series([10, 20, 30, 40, 50]))
    assert pr.iloc[0] == 0.0
    assert pr.iloc[-1] == 1.0
    assert abs(pr.iloc[2] - 0.5) < 1e-9


def test_percent_rank_single_row_is_zero():
    assert _percent_rank(pd.Series([7])).iloc[0] == 0.0


def test_add_success_score_columns_and_range():
    df = pd.DataFrame({
        "downloads": [0, 100, 1000, 50000],
        "likes": [0, 5, 2, 300],
        "fine_tune_fan_out": [0, 0, 1, 9],
    })
    out = add_success_score(df)
    for col in ("downloads_pct", "likes_pct", "fan_out_pct", "composite_success_score"):
        assert col in out.columns
    assert out["composite_success_score"].between(0, 1).all()
    assert out["composite_success_score"].iloc[-1] == 1.0   # top on every signal
    assert out["composite_success_score"].iloc[0] == 0.0    # bottom on every signal


def test_add_success_score_is_case_insensitive():
    df = pd.DataFrame({
        "DOWNLOADS": [1, 2], "LIKES": [1, 2], "FINE_TUNE_FAN_OUT": [1, 2],
    })
    out = add_success_score(df)
    assert out["composite_success_score"].iloc[1] == 1.0


def test_add_success_score_missing_columns_raises():
    with pytest.raises(KeyError):
        add_success_score(pd.DataFrame({"downloads": [1], "likes": [1]}))


def test_weights_are_respected():
    # downloads/likes tie (pct 0); only fan-out separates the rows.
    df = pd.DataFrame({
        "downloads": [5, 5], "likes": [5, 5], "fine_tune_fan_out": [1, 9],
    })
    out = add_success_score(df)
    assert out["composite_success_score"].iloc[1] == WEIGHTS["fine_tune_fan_out"]
