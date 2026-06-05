"""No-SQL data access for the ML/RAG side: each call returns a pandas DataFrame
from a curated Snowflake mart (friendly names in TABLES below).

Setup: pip install "snowflake-connector-python[pandas]" pandas pyarrow, and put
Snowflake creds in .env (role ML_DEV).

    from ml.data import practice_stats, repos_needing_llm
    df = practice_stats()       # quadrants (#10)
    todo = repos_needing_llm()  # the #7 target list
    # export_all() dumps every table to ml/data/*.parquet for offline work
"""

import os

# friendly name -> fully-qualified Snowflake table (read-only marts)
TABLES = {
    "outcomes":               "GOLD.REPO_LORA_OUTCOMES",        # success score per HF model (#6)
    "practice_stats":         "GOLD.LORA_PRACTICE_STATS",       # common/rare x works/fails (#10)
    "repo_lora_params":       "GOLD.REPO_LORA_PARAMS",          # GitHub-side LoRA params
    "hf_model_tree":          "GOLD.HF_MODEL_TREE",             # base_model -> fine-tune fan-out
    "hf_models_lora_params":  "SILVER.HF_MODELS_LORA_PARAMS",   # HF-side params (Variant D)
    "repos":                  "SILVER.REPOS",                   # conformed repo entity
    "hf_models":              "SILVER.HF_MODELS",               # conformed HF model entity
    "github_hf_links":        "SILVER.GITHUB_HF_LINKS",         # GH<->HF links
    "repos_needing_llm":      "SILVER.REPOS_NEEDING_LLM_EXTRACTION",  # #7 target list
    "github_files":           "BRONZE.GITHUB_FILES",            # #7 raw file content
}

_DATABASE = os.getenv("SNOWFLAKE_DATABASE", "ML_UNDERGROUND")


def _connect():
    import snowflake.connector
    return snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],
        role=os.getenv("SNOWFLAKE_ROLE", "ML_DEV"),
        warehouse=os.getenv("SNOWFLAKE_WAREHOUSE", "ML_UNDERGROUND_WH"),
        database=_DATABASE,
    )


def load(name, limit=None):
    """Return a curated mart as a pandas DataFrame, by friendly name (see TABLES)."""
    if name not in TABLES:
        raise KeyError(f"unknown table {name!r}; options: {sorted(TABLES)}")
    sql = f"SELECT * FROM {_DATABASE}.{TABLES[name]}"
    if limit:
        sql += f" LIMIT {int(limit)}"
    con = _connect()
    try:
        cur = con.cursor()
        cur.execute(sql)
        return cur.fetch_pandas_all()
    finally:
        con.close()


# convenience shortcuts for the tables you'll touch most
def outcomes(limit=None):              return load("outcomes", limit)
def practice_stats(limit=None):        return load("practice_stats", limit)
def hf_models_lora_params(limit=None): return load("hf_models_lora_params", limit)
def repos_needing_llm(limit=None):     return load("repos_needing_llm", limit)
def github_files(limit=None):          return load("github_files", limit)


def export_all(out_dir="ml/data"):
    """Dump every table to ml/data/<name>.parquet for offline/pandas-only work."""
    import pathlib
    pathlib.Path(out_dir).mkdir(parents=True, exist_ok=True)
    written = []
    for name in TABLES:
        df = load(name)
        path = f"{out_dir}/{name}.parquet"
        df.to_parquet(path, index=False)
        written.append((name, len(df), path))
        print(f"  {name}: {len(df)} rows -> {path}")
    return written
