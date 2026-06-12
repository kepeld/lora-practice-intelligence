"""Unit tests for ml/practice_stats.py (Issue #10 quadrants, pandas mirror).

Skipped when pandas is unavailable so the rest of the suite still runs.
"""

import pathlib
import sys

import pytest

pd = pytest.importorskip("pandas")

# ml/ is not on the default test path (conftest only adds de/ingestion).
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "ml"))

from practice_stats import (  # noqa: E402
    DEFAULT_PARAMS, MIN_SAMPLE, _score_vs_base, normalize_param_value,
    practice_stats,
)


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


def test_score_vs_base_uses_reference_population():
    # #53: peer means must come from the reference frame when given, so a
    # params-only subset can still be judged against the FULL outcomes mart.
    models = pd.DataFrame({
        "model_id": ["a1"],
        "base_model": ["A"],
        "composite_success_score": [0.6],
    })
    reference = pd.DataFrame({
        "model_id": ["a1", "a2"],
        "base_model": ["A", "A"],
        "composite_success_score": [0.6, 0.8],
    })
    assert _score_vs_base(models).iloc[0] == 0.0                      # self-reference
    assert round(_score_vs_base(models, reference).iloc[0], 4) == -0.1  # A mean 0.7


def test_score_vs_base_unknown_base_falls_back_to_reference_global():
    models = pd.DataFrame({
        "model_id": ["x1"],
        "base_model": ["UNSEEN"],
        "composite_success_score": [0.9],
    })
    reference = pd.DataFrame({
        "model_id": ["r1", "r2"],
        "base_model": ["A", "A"],
        "composite_success_score": [0.2, 0.4],
    })
    # UNSEEN base is not in the reference -> global reference mean 0.3.
    assert round(_score_vs_base(models, reference).iloc[0], 4) == 0.6


def test_practice_stats_passes_reference_through():
    models = _opt_frame()
    # Reference shifts every B-peer mean up to 0.95: now ONLY "rare" (0.95)
    # is at/above its peer mean; good (0.9) lands below.
    reference = pd.DataFrame({
        "model_id": ["p1", "p2"],
        "base_model": ["B", "B"],
        "composite_success_score": [0.95, 0.95],
    })
    out = practice_stats(models, reference_models=reference)
    assert _cell(out, "optimizer", "good")["avg_score_vs_base"] == round(0.9 - 0.95, 3)
    assert _cell(out, "optimizer", "rare")["avg_score_vs_base"] == round(0.95 - 0.95, 3)


def test_normalize_param_value_matches_dbt_rendering():
    # #75: float-promoted ints/bools must render like the dbt long_form.
    assert normalize_param_value("rank_value", 64.0) == "64"
    assert normalize_param_value("rank_value", "64.0") == "64"
    assert normalize_param_value("bf16", 1.0) == "true"
    assert normalize_param_value("bf16", "0.0") == "false"
    assert normalize_param_value("bf16", True) == "true"
    assert normalize_param_value("lora_dropout", 0.05) == "0.05"
    assert normalize_param_value("optimizer", "adamw") == "adamw"


def test_practice_stats_renders_float_promoted_values_cleanly():
    df = pd.DataFrame({
        "model_id": ["a", "b", "c"],
        "base_model": ["B", "B", "B"],
        "composite_success_score": [0.5, 0.6, 0.7],
        "lora_alpha": [48.0, 48.0, 16.0],
        "fp16": [1.0, 0.0, 1.0],
    })
    out = practice_stats(df)
    assert set(out[out.param_name == "lora_alpha"]["param_value"]) == {"48", "16"}
    assert set(out[out.param_name == "fp16"]["param_value"]) == {"true", "false"}


def test_default_params_match_dbt_long_form():
    # Pin the mirror's param list to the dbt long_form unions (14 params, #67).
    assert set(DEFAULT_PARAMS) == {
        "rank_value", "lora_alpha", "optimizer", "scheduler", "batch_size",
        "num_train_epochs", "gradient_accumulation_steps", "lora_dropout",
        "bf16", "learning_rate", "lora_bias", "warmup_steps",
        "gradient_checkpointing", "fp16",
    }
