"""
Corpus Backfill — weekly orchestrator for the LoRA Practice Intelligence corpus.

  lora_collector  ->  hf_collector  ->  files_fetcher  ->  linker

Manual trigger w/ config:
    {
      "lora_target_count": 700,
      "hf_target_count": 1500,
      "hf_min_downloads": 100,
      "files_repo_limit": 1000,
      "files_max_bytes": 1048576,
      "fuzzy_threshold": 0.85,
      "skip_lora_collector": false,
      "skip_hf_collector": false,
      "skip_files_fetcher": false,
      "skip_linker": false
    }

Skip flags let you run just part of the pipeline (e.g. relink only after a
schema change). A skipped task logs once and returns success.
"""

from datetime import timedelta

from airflow import DAG
from airflow.models.param import Param
from airflow.operators.python import PythonOperator
from airflow.utils.dates import days_ago


default_args = {
    "owner": "ml-underground",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 0,
}


def _prep_env(skip_flag: str, **context):
    """Returns True if the task should no-op (skip flag set), else sets up env and returns False."""
    import logging
    import os
    import sys

    params = context["params"]
    if params.get(skip_flag, False):
        logging.info("%s = true — skipped by user", skip_flag)
        return True

    # Inside the Airflow container MySQL is the compose service hostname.
    os.environ.setdefault("MYSQL_HOST", "mysql")

    # de/ingestion is mounted at /opt/airflow/ingestion.
    if "/opt/airflow" not in sys.path:
        sys.path.insert(0, "/opt/airflow")
    return False


def run_lora_collector(**context):
    """Targeted GitHub LoRA-repo collector (US-1.2)."""
    import os
    if _prep_env("skip_lora_collector", **context):
        return
    os.environ["LORA_ENRICH_LIMIT"] = str(context["params"]["lora_target_count"])
    from ingestion.targeted_lora_collector import main as lora_main
    lora_main()


def run_hf_collector(**context):
    """Targeted HuggingFace LoRA-model collector (US-1.2)."""
    import os
    if _prep_env("skip_hf_collector", **context):
        return
    os.environ["HF_LORA_TARGET_COUNT"] = str(context["params"]["hf_target_count"])
    os.environ["HF_LORA_MIN_DOWNLOADS"] = str(context["params"]["hf_min_downloads"])
    from ingestion.hf_targeted_collector import main as hf_main
    hf_main()


def run_files_fetcher(**context):
    """Training/config file extraction from LoRA repos (US-2.2)."""
    import os
    if _prep_env("skip_files_fetcher", **context):
        return
    os.environ["FILES_REPO_LIMIT"] = str(context["params"]["files_repo_limit"])
    os.environ["FILES_MAX_BYTES"] = str(context["params"]["files_max_bytes"])
    from ingestion.github_files_fetcher import main as files_main
    files_main()


def run_linker(**context):
    """GitHub <-> HF record linkage on the full corpus (US-2.1)."""
    import os
    if _prep_env("skip_linker", **context):
        return
    os.environ["LINKER_FUZZY_THRESHOLD"] = str(context["params"]["fuzzy_threshold"])
    from ingestion.github_hf_linker import main as linker_main
    linker_main()


with DAG(
    dag_id="corpus_backfill_dag",
    default_args=default_args,
    description="Weekly orchestrator: LoRA + HF collectors -> files -> linker",
    schedule_interval="0 6 * * 0",       # Sundays 06:00 UTC
    start_date=days_ago(1),
    catchup=False,
    max_active_runs=1,
    dagrun_timeout=timedelta(hours=4),
    params={
        "lora_target_count":   Param(700,     type="integer", minimum=1),
        "hf_target_count":     Param(1500,    type="integer", minimum=1),
        "hf_min_downloads":    Param(100,     type="integer", minimum=0),
        "files_repo_limit":    Param(1000,    type="integer", minimum=1),
        "files_max_bytes":     Param(1048576, type="integer", minimum=1024),
        "fuzzy_threshold":     Param(0.85,    type="number",  minimum=0, maximum=1),
        "skip_lora_collector": Param(False,   type="boolean"),
        "skip_hf_collector":   Param(False,   type="boolean"),
        "skip_files_fetcher":  Param(False,   type="boolean"),
        "skip_linker":         Param(False,   type="boolean"),
    },
    tags=["backfill", "weekly", "lora_intelligence", "corpus"],
) as dag:

    lora_collector = PythonOperator(
        task_id="lora_collector",
        python_callable=run_lora_collector,
        execution_timeout=timedelta(minutes=60),
    )

    hf_collector = PythonOperator(
        task_id="hf_collector",
        python_callable=run_hf_collector,
        execution_timeout=timedelta(minutes=60),
    )

    files_fetcher = PythonOperator(
        task_id="files_fetcher",
        python_callable=run_files_fetcher,
        execution_timeout=timedelta(minutes=90),
    )

    linker = PythonOperator(
        task_id="linker",
        python_callable=run_linker,
        execution_timeout=timedelta(minutes=15),
    )

    lora_collector >> hf_collector >> files_fetcher >> linker
