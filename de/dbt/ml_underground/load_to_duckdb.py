"""
Replicate the MySQL bronze tables into the DuckDB warehouse file.

EL step before dbt's T: dbt builds the Silver/Gold models on top of the DuckDB
copy. Each run is a full refresh (CREATE OR REPLACE) — fine for the bounded
bronze volume. Invoked by the Airflow load task using the isolated dbt venv
(duckdb + mysql-connector). The file path is DUCKDB_PATH, shared with dbt and
ml/data.py; the DuckDB catalog name is the file stem (ML_UNDERGROUND).
"""

import os

import duckdb
import mysql.connector
import pandas as pd

BRONZE_TABLES = [
    "github_repos_bronze",
    "github_repos_enriched",
    "huggingface_models_bronze",
    "github_repos_embedded",
    "github_hf_links",
    "github_files",
    "lora_configs_raw",
    "repo_lora_params",
    "hf_models_lora_params",
]

BRONZE_SCHEMA = "BRONZE"


def _clean(value):
    """Bytearray JSON cols -> utf-8 text (DuckDB stores them as VARCHAR)."""
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8")
    return value


def main():
    mysql_conn = mysql.connector.connect(
        host=os.getenv("MYSQL_HOST", "mysql"),
        user=os.getenv("MYSQL_USER", "root"),
        password=os.getenv("MYSQL_PASSWORD", "root"),
        database=os.getenv("MYSQL_DATABASE", "ml_underground"),
    )
    con = duckdb.connect(os.getenv("DUCKDB_PATH", "/opt/airflow/dbt/ML_UNDERGROUND.duckdb"))
    con.execute(f"CREATE SCHEMA IF NOT EXISTS {BRONZE_SCHEMA}")
    try:
        for table in BRONZE_TABLES:
            df = pd.read_sql(f"SELECT * FROM {table}", mysql_conn)
            for col in df.columns:
                if df[col].dtype == object:
                    df[col] = df[col].apply(_clean)
            con.register("df_tmp", df)
            con.execute(
                f"CREATE OR REPLACE TABLE {BRONZE_SCHEMA}.{table} AS SELECT * FROM df_tmp"
            )
            con.unregister("df_tmp")
            print(f"{table}: loaded {len(df)} rows")
    finally:
        mysql_conn.close()
        con.close()


if __name__ == "__main__":
    main()
