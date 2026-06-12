from fastapi import FastAPI, Query, Path, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any, Literal
from datetime import datetime

app = FastAPI(
    title="ML Underground API",
    version="1.0.0",
    description="Proposed contract derived from live warehouse schema (Snowflake GOLD/SILVER)"
)

# Налаштування CORS, щоб ваш React-фронтенд (наприклад, на порту 3000) міг вільно робити запити
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # В продакшені замініть на конкретний домен фронтенду
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- 📋 ПІДГОТОВКА СХЕМ ДАНИХ (Pydantic моделі) ---

class LoraParams(BaseModel):
    rank_value: Optional[int] = Field(None, description="The LoRA rank (renamed — rank is a SQL keyword)")
    lora_alpha: Optional[int] = None
    target_modules: Optional[List[str]] = Field(None, description="e.g. ['q_proj','v_proj'] stored as a JSON array")
    learning_rate: Optional[float] = None
    optimizer: Optional[str] = None
    lora_dropout: Optional[float] = None
    lora_bias: Optional[str] = None
    scheduler: Optional[str] = None
    batch_size: Optional[int] = None
    gradient_accumulation_steps: Optional[int] = None
    num_train_epochs: Optional[int] = None
    warmup_steps: Optional[int] = None
    bf16: Optional[bool] = None
    fp16: Optional[bool] = None
    gradient_checkpointing: Optional[bool] = None
    merge_and_unload: Optional[bool] = None
    param_sources: Optional[Dict[str, str]] = Field(None, description="Priority: ast > json > yaml > regex > llm")
    total_params_extracted: int
    extraction_confidence: float
    extracted_at: datetime

class Repo(BaseModel):
    repo_id: int
    repo_name: str
    description: Optional[str]
    primary_language: Optional[str]
    topics: List[str]
    license: Optional[str]
    homepage: Optional[str]
    star_count: int
    forks_count: int
    open_issues_count: int
    contributors_count: int
    commit_count_30d: int
    has_tests: bool
    has_ci: bool
    is_fork: bool
    is_archived: bool
    readme_length: int
    repo_created_at: datetime
    pushed_at: datetime
    enriched_at: Optional[datetime]
    is_enriched: bool

class RepoWithParams(Repo):
    lora_params: LoraParams

class LinkedModel(BaseModel):
    model_id: str
    best_confidence: float

class RepoDetail(Repo):
    lora_params: LoraParams
    linked_models: List[LinkedModel]

class HFModel(BaseModel):
    model_id: str
    author: str
    base_model: Optional[str]
    pipeline_tag: Optional[str]
    library_name: Optional[str]
    downloads: int
    likes: int
    tags: List[str]
    tag_count: int
    is_fine_tune: bool
    created_at: datetime
    last_modified: datetime

class Outcome(HFModel):
    fine_tune_fan_out: int
    composite_success_score: float

class OutcomeWithParams(Outcome):
    lora_params: LoraParams

class ModelDetail(Outcome):
    lora_params: LoraParams
    fine_tune_models: List[str]

class PracticeStat(BaseModel):
    param_name: str
    param_value: str
    prevalence: int
    avg_success_score: float
    quadrant: Literal["common+works", "common+fails", "rare+works", "rare+fails"]

# Пагінаційні конверти (Pagination Envelopes)
class InsightsResponse(BaseModel):
    items: List[PracticeStat]
    total: int
    limit: int
    offset: int

class ReposResponse(BaseModel):
    items: List[RepoWithParams]
    total: int
    limit: int
    offset: int

class ModelsResponse(BaseModel):
    items: List[OutcomeWithParams]
    total: int
    limit: int
    offset: int

class SummaryResponse(BaseModel):
    repos_total: int
    repos_enriched: int
    hf_models_total: int
    links_total: int
    repos_with_params: int
    extraction_coverage: float

class SearchItem(BaseModel):
    score: float
    type: Literal["repo", "model"]
    object: Any

class SearchResponse(BaseModel):
    items: List[SearchItem]


# --- 💾 РЕАЛІСТИЧНІ МОКОВІ ДАНІ (Snowflake Emulation) ---

MOCK_PARAMS = LoraParams(
    rank_value=64,
    lora_alpha=16,
    target_modules=["q_proj", "v_proj"],
    learning_rate=0.0002,
    optimizer="adamw_8bit",
    lora_dropout=0.05,
    lora_bias="none",
    scheduler="cosine",
    batch_size=4,
    gradient_accumulation_steps=2,
    num_train_epochs=3,
    warmup_steps=100,
    bf16=True,
    fp16=False,
    gradient_checkpointing=True,
    merge_and_unload=True,
    param_sources={"rank_value": "json", "optimizer": "yaml"},
    total_params_extracted=5,
    extraction_confidence=1.0,
    extracted_at=datetime.fromisoformat("2026-05-31T00:00:00Z")
)

MOCK_INSIGHTS = [
    PracticeStat(param_name="optimizer", param_value="adamw_8bit", prevalence=12, avg_success_score=7.41, quadrant="rare+works"),
    PracticeStat(param_name="rank_value", param_value="128", prevalence=9, avg_success_score=7.02, quadrant="rare+works"),
    PracticeStat(param_name="scheduler", param_value="cosine_with_restarts", prevalence=88, avg_success_score=3.12, quadrant="common+fails"),
    PracticeStat(param_name="optimizer", param_value="adamw_torch", prevalence=145, avg_success_score=6.20, quadrant="common+works"),
    PracticeStat(param_name="lora_dropout", param_value="0.1", prevalence=104, avg_success_score=3.45, quadrant="common+fails"),
    PracticeStat(param_name="lora_bias", param_value="all", prevalence=4, avg_success_score=1.80, quadrant="rare+fails")
]

MOCK_REPOS = [
    RepoWithParams(
        repo_id=482910,
        repo_name="alice/llama3-finance-lora",
        description="Optimized configuration for low VRAM training with AdamW 8bit quantization",
        primary_language="Python",
        topics=["lora", "finance", "peft"],
        license="MIT",
        homepage="https://github.com/alice/llama3-finance-lora",
        star_count=312,
        forks_count=45,
        open_issues_count=2,
        contributors_count=3,
        commit_count_30d=14,
        has_tests=True,
        has_ci=True,
        is_fork=False,
        is_archived=False,
        readme_length=4250,
        repo_created_at=datetime.fromisoformat("2026-02-10T08:00:00Z"),
        pushed_at=datetime.fromisoformat("2026-05-30T12:00:00Z"),
        enriched_at=datetime.fromisoformat("2026-05-31T00:00:00Z"),
        is_enriched=True,
        lora_params=MOCK_PARAMS
    )
]

MOCK_OUTCOMES = [
    OutcomeWithParams(
        model_id="alice/llama3-finance-lora",
        author="alice",
        base_model="meta-llama/Llama-3.1-8B",
        pipeline_tag="text-generation",
        library_name="peft",
        downloads=48213,
        likes=312,
        tags=["lora", "finance"],
        tag_count=2,
        is_fine_tune=True,
        created_at=datetime.fromisoformat("2026-02-10T08:00:00Z"),
        last_modified=datetime.fromisoformat("2026-05-30T12:00:00Z"),
        fine_tune_fan_out=7,
        composite_success_score=8.93,
        lora_params=MOCK_PARAMS
    )
]


# --- 🛣️ ЕНДПОІНТИ API (Base path: /api/v1) ---

@app.get("/api/v1/insights", response_model=InsightsResponse)
def get_insights(
    quadrant: Optional[str] = Query(None),
    param_name: Optional[str] = Query(None),
    min_prevalence: Optional[int] = Query(None),
    sort: str = Query("avg_success_score"),
    order: str = Query("desc"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0)
):
    filtered = MOCK_INSIGHTS
    if quadrant:
        filtered = [i for i in filtered if i.quadrant == quadrant]
    if param_name:
        filtered = [i for i in filtered if i.param_name == param_name]
    if min_prevalence:
        filtered = [i for i in filtered if i.prevalence >= min_prevalence]
        
    # Базове сортування
    reverse_sort = True if order == "desc" else False
    filtered.sort(key=lambda x: getattr(x, sort, "avg_success_score"), reverse=reverse_sort)
    
    return {
        "items": filtered[offset : offset + limit],
        "total": len(filtered),
        "limit": limit,
        "offset": offset
    }

@app.get("/api/v1/repos", response_model=ReposResponse)
def get_repos(
    param: Optional[str] = Query(None),
    value: Optional[str] = Query(None),
    language: Optional[str] = Query(None),
    has_tests: Optional[bool] = Query(None),
    q: Optional[str] = Query(None),
    sort: str = Query("star_count"),
    order: str = Query("desc"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0)
):
    # Повертає список репозиторіїв з розпарсеними параметрами
    return {
        "items": MOCK_REPOS,
        "total": len(MOCK_REPOS),
        "limit": limit,
        "offset": offset
    }

@app.get("/api/v1/repos/{repo_name:path}", response_model=RepoDetail)
def get_repo_detail(repo_name: str = Path(..., description="Passed raw using :path converter")):
    # Шукаємо репо по імені
    for repo in MOCK_REPOS:
        if repo.repo_name == repo_name:
            return RepoDetail(
                **repo.model_dump(),
                linked_models=[LinkedModel(model_id="alice/llama3-finance-lora", best_confidence=0.95)]
            )
    raise HTTPException(status_code=404, detail="Repository not found")

@app.get("/api/v1/models", response_model=ModelsResponse)
def get_models(
    base_model: Optional[str] = Query(None),
    pipeline_tag: Optional[str] = Query(None),
    library_name: Optional[str] = Query(None),
    min_downloads: Optional[int] = Query(None),
    sort: str = Query("composite_success_score"),
    order: str = Query("desc"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0)
):
    return {
        "items": MOCK_OUTCOMES,
        "total": len(MOCK_OUTCOMES),
        "limit": limit,
        "offset": offset
    }

@app.get("/api/v1/models/{model_id:path}", response_model=ModelDetail)
def get_model_detail(model_id: str = Path(..., description="Passed raw because it contains slashes")):
    for model in MOCK_OUTCOMES:
        if model.model_id == model_id:
            return ModelDetail(
                **model.model_dump(),
                fine_tune_models=["bob/llama3-finance-adapter-v2"]
            )
    raise HTTPException(status_code=404, detail="HuggingFace model not found")

@app.get("/api/v1/search", response_model=SearchResponse)
def semantic_search(
    q: str = Query(..., description="Semantic search over READMEs / model cards via Qdrant"),
    type: Literal["repos", "models", "all"] = Query("all"),
    limit: int = Query(10)
):
    # Імітуємо семантичний збіг для інтерфейсу пошуку, який ми бачили на скріншоті
    return {
        "items": [
            SearchItem(score=0.894, type="repo", object=MOCK_REPOS[0]),
            SearchItem(score=0.842, type="model", object=MOCK_OUTCOMES[0])
        ]
    }

@app.get("/api/v1/stats/summary", response_model=SummaryResponse)
def get_summary_kpi():
    # Головні Hero Numbers дашборду відповідно до ТЗ (500+ репо, >50 якісних лінків, >50% coverage)
    return SummaryResponse(
        repos_total=542,
        repos_enriched=510,
        hf_models_total=189,
        links_total=74,
        repos_with_params=280,
        extraction_coverage=0.518
    )

from fastapi.responses import RedirectResponse

@app.get("/")
def redirect_to_docs():
    return RedirectResponse(url="/docs")

from fastapi import Response

@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return Response(status_code=204)