"""Great Expectations validation of the MySQL bronze tables (data-quality gate).

Run with the isolated GE venv: /home/airflow/ge-venv/bin/python.
"""

import os
import sys

import great_expectations as gx
from great_expectations import expectations as gxe
from great_expectations.data_context.types.base import ProgressBarsConfig


def mysql_connection_string():
    return (
        "mysql+pymysql://"
        f"{os.getenv('MYSQL_USER', 'root')}:{os.getenv('MYSQL_PASSWORD', 'root')}"
        f"@{os.getenv('MYSQL_HOST', 'mysql')}:3306/"
        f"{os.getenv('MYSQL_DATABASE', 'ml_underground')}"
    )


SUITES = {
    # github_repos_bronze: frozen relic of the retired GH Archive stream; stg
    # now anchors on github_repos_enriched and only LEFT JOINs this table for
    # legacy event-activity proxies -- may be empty on a fresh deploy.
    "github_repos_bronze": [
        gxe.ExpectColumnValuesToNotBeNull(column="repo_id"),
    ],
    "github_repos_enriched": [
        gxe.ExpectColumnValuesToNotBeNull(column="repo_id"),
        gxe.ExpectColumnProportionOfUniqueValuesToBeBetween(
            column="repo_id", min_value=1.0
        ),
        gxe.ExpectColumnValuesToBeInSet(
            column="enrichment_status",
            # ok / not_found / error come from the enricher; radio_lora is set
            # by the LoRA collector clean-up to exclude LoRaWAN/IoT false hits.
            value_set=["ok", "not_found", "error", "radio_lora"],
        ),
    ],
    "huggingface_models_bronze": [
        gxe.ExpectTableRowCountToBeBetween(min_value=1),
        gxe.ExpectColumnValuesToNotBeNull(column="model_id"),
        gxe.ExpectColumnProportionOfUniqueValuesToBeBetween(
            column="model_id", min_value=1.0
        ),
        gxe.ExpectColumnValuesToBeInSet(
            # organic = hourly hf_ingestion; targeted_lora = hf_targeted_collector
            column="collection_source", value_set=["organic", "targeted_lora"]
        ),
    ],
    # github_hf_links is filled by the linker step of corpus_backfill_dag, so it may
    # legitimately be empty between runs -- no row-count minimum here, the
    # column expectations all pass cleanly on an empty table.
    "github_hf_links": [
        gxe.ExpectColumnValuesToNotBeNull(column="repo_full_name"),
        gxe.ExpectColumnValuesToNotBeNull(column="model_id"),
        gxe.ExpectColumnValuesToBeInSet(
            column="link_type",
            value_set=["readme_direct", "modelcard_direct",
                       "same_username", "fuzzy_name"],
        ),
        gxe.ExpectColumnValuesToBeBetween(
            column="confidence", min_value=0.0, max_value=1.0
        ),
    ],
    # github_files is filled by the files_fetcher step of corpus_backfill_dag -- may
    # be empty between runs, so no row-count minimum.
    "github_files": [
        gxe.ExpectColumnValuesToNotBeNull(column="repo_full_name"),
        gxe.ExpectColumnValuesToNotBeNull(column="file_path"),
        gxe.ExpectColumnValuesToNotBeNull(column="file_sha"),
        gxe.ExpectColumnValuesToBeInSet(
            column="file_category",
            value_set=["training_script", "config",
                       "dependencies", "adapter_config"],
        ),
    ],
    # lora_configs_raw is filled by lora_extraction_dag — empty between runs.
    "lora_configs_raw": [
        gxe.ExpectColumnValuesToNotBeNull(column="repo_full_name"),
        gxe.ExpectColumnValuesToNotBeNull(column="file_id"),
        gxe.ExpectColumnValuesToNotBeNull(column="param_name"),
        gxe.ExpectColumnValuesToBeInSet(
            column="source",
            # 'llm' is reserved for the future LLM-extraction fallback (US-3.3);
            # this step's pipeline never emits it but the value is allowed.
            value_set=["ast", "yaml", "json", "regex", "llm"],
        ),
        gxe.ExpectColumnValuesToBeBetween(
            column="confidence", min_value=0.0, max_value=1.0
        ),
    ],
    # repo_lora_params: one row per LoRA repo after the merge step.
    "repo_lora_params": [
        gxe.ExpectColumnValuesToNotBeNull(column="repo_full_name"),
        # Domain ranges. rank_value=-1 is a valid PEFT auto-rank sentinel,
        # hence the -1 lower bound (the extractor rejects rank=0 / >512).
        gxe.ExpectColumnValuesToBeBetween(
            column="rank_value", min_value=-1, max_value=512
        ),
        gxe.ExpectColumnValuesToBeBetween(
            column="lora_alpha", min_value=1, max_value=1024
        ),
        gxe.ExpectColumnValuesToBeBetween(
            column="extraction_confidence", min_value=0.0, max_value=1.0
        ),
    ],
    # hf_models_lora_params: one row per HF model whose card yielded params
    # (Variant D for US-4.2). Same domain rules as repo_lora_params.
    "hf_models_lora_params": [
        gxe.ExpectColumnValuesToNotBeNull(column="model_id"),
        gxe.ExpectColumnValuesToBeBetween(
            column="rank_value", min_value=-1, max_value=512
        ),
        gxe.ExpectColumnValuesToBeBetween(
            column="lora_alpha", min_value=1, max_value=1024
        ),
        gxe.ExpectColumnValuesToBeBetween(
            column="extraction_confidence", min_value=0.0, max_value=1.0
        ),
    ],
}


def main():
    context = gx.get_context(mode="ephemeral")
    # keep task logs readable — no per-metric tqdm progress bars
    context.variables.progress_bars = ProgressBarsConfig(
        globally=False, metric_calculations=False
    )
    datasource = context.data_sources.add_sql(
        name="mysql_bronze", connection_string=mysql_connection_string()
    )

    failed = []
    for table, expectations in SUITES.items():
        asset = datasource.add_table_asset(name=table, table_name=table)
        batch_definition = asset.add_batch_definition_whole_table(
            name=f"{table}_whole"
        )

        suite = context.suites.add(gx.ExpectationSuite(name=f"{table}_suite"))
        for expectation in expectations:
            suite.add_expectation(expectation)

        validation = context.validation_definitions.add(
            gx.ValidationDefinition(
                name=f"{table}_validation", data=batch_definition, suite=suite
            )
        )
        result = validation.run()
        stats = result.statistics
        flag = "PASS" if result.success else "FAIL"
        print(
            f"{table}: {flag} "
            f"({stats['successful_expectations']}/{stats['evaluated_expectations']})"
        )
        if not result.success:
            for item in result.results:
                if not item.success:
                    cfg = item.expectation_config
                    print(f"  FAILED  {cfg.type}  kwargs={cfg.kwargs}")
                    print(f"          observed={item.result}")
            failed.append(table)

    if failed:
        print(f"Great Expectations: validation FAILED for {', '.join(failed)}")
        sys.exit(1)
    print("Great Expectations: all bronze tables passed validation")


if __name__ == "__main__":
    main()
