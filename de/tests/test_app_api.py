"""API tests for app/ (the v1 contract service) over a seeded demo warehouse.

Skipped when fastapi/duckdb are unavailable. /search and /ask are exercised in
their degraded (503) paths — no Qdrant, no ANTHROPIC_API_KEY in tests.
"""

import pathlib
import sys

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("duckdb")
from fastapi.testclient import TestClient  # noqa: E402

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from app.demo_seed import seed  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    path = tmp_path_factory.mktemp("wh") / "ML_UNDERGROUND.duckdb"
    seed(str(path))
    import os
    old = os.environ.get("DUCKDB_PATH")
    os.environ["DUCKDB_PATH"] = str(path)
    yield TestClient(app)
    if old is None:
        os.environ.pop("DUCKDB_PATH", None)
    else:
        os.environ["DUCKDB_PATH"] = old


def test_stats_summary_contract_keys(client):
    body = client.get("/api/v1/stats/summary").json()
    assert set(body) == {"repos_total", "repos_enriched", "hf_models_total",
                         "links_total", "repos_with_params", "extraction_coverage"}
    assert body["repos_total"] == 5
    assert body["repos_with_params"] == 4
    assert body["extraction_coverage"] == 0.8


def test_insights_envelope_and_sort(client):
    body = client.get("/api/v1/insights?sort=score_lift&order=desc").json()
    assert {"items", "total", "limit", "offset"} <= set(body)
    lifts = [i["score_lift"] for i in body["items"]]
    assert lifts == sorted(lifts, reverse=True)


def test_insights_quadrant_filter_tolerates_space(client):
    encoded = client.get("/api/v1/insights?quadrant=rare%2Bworks").json()
    spaced = client.get("/api/v1/insights?quadrant=rare+works").json()
    assert encoded["total"] == spaced["total"] > 0
    assert all(i["quadrant"] == "rare+works" for i in encoded["items"])


def test_insights_sample_ok_filter(client):
    body = client.get("/api/v1/insights?sample_ok=true").json()
    assert all(i["sample_ok"] for i in body["items"])
    allb = client.get("/api/v1/insights").json()
    assert allb["total"] > body["total"]


def test_insights_bad_sort_is_422(client):
    assert client.get("/api/v1/insights?sort=hacky").status_code == 422


def test_insight_evidence_models(client):
    body = client.get("/api/v1/insights/optimizer/adamw_8bit/models").json()
    ids = [m["model_id"] for m in body["items"]]
    assert "alice/llama3-finance-lora" in ids
    scores = [m["composite_success_score"] for m in body["items"]]
    assert scores == sorted(scores, reverse=True)


def test_insight_evidence_unknown_param_is_422(client):
    assert client.get("/api/v1/insights/evil; DROP/x/models").status_code == 422


def test_models_envelope_with_nested_params(client):
    body = client.get("/api/v1/models?sort=composite_success_score").json()
    top = body["items"][0]
    assert top["model_id"] == "alice/llama3-finance-lora"
    assert 0 <= top["composite_success_score"] <= 1
    assert top["lora_params"]["rank_value"] == 64
    assert top["lora_params"]["target_modules"][0] == "q_proj"


def test_models_filter_by_base(client):
    body = client.get(
        "/api/v1/models?base_model=mistralai/Mistral-7B-v0.3").json()
    assert body["total"] == 2


def test_model_detail_and_404(client):
    detail = client.get("/api/v1/models/alice/llama3-finance-lora").json()
    assert detail["lora_params"]["optimizer"] == "adamw_8bit"
    assert detail["fine_tune_models"] == []
    assert client.get("/api/v1/models/nope/nope").status_code == 404


def test_repos_filters_and_nested_params(client):
    body = client.get("/api/v1/repos?has_tests=true").json()
    assert body["total"] == 3
    named = client.get("/api/v1/repos?q=cargo").json()
    assert named["total"] == 1
    assert named["items"][0]["lora_params"]["optimizer"] == "adamw_torch"


def test_repos_param_value_filter(client):
    body = client.get("/api/v1/repos?param=optimizer&value=adamw_8bit").json()
    assert [r["repo_name"] for r in body["items"]] == ["axolotl/llama-3-configs"]


def test_repo_detail_linked_models(client):
    body = client.get("/api/v1/repos/axolotl/llama-3-configs").json()
    assert body["linked_models"][0]["model_id"] == "alice/llama3-finance-lora"


def test_search_degrades_to_503(client, monkeypatch):
    # Hermetic: simulate the vector stack being down even when the dev machine
    # has qdrant-client installed and a live Qdrant running.
    import ml.rag.retriever as retriever

    def boom(*args, **kwargs):
        raise RuntimeError("qdrant unreachable (simulated)")

    monkeypatch.setattr(retriever, "search_all", boom)
    monkeypatch.setattr(retriever, "search", boom)
    res = client.get("/api/v1/search?q=adamw")
    assert res.status_code == 503
    assert "unavailable" in res.json()["detail"]


def test_ask_without_key_is_503(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    res = client.get("/api/v1/ask?q=which optimizer")
    assert res.status_code == 503
    assert "ANTHROPIC_API_KEY" in res.json()["detail"]


def test_dashboard_served_at_root(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "ML Underground" in res.text
