"""
Replicate the MySQL bronze tables into Snowflake.

This is the EL step before dbt's T: dbt builds the Silver/Gold models on top
of the Snowflake copy. Each run is a full refresh (overwrite) — fine for the
bounded bronze volume. Invoked by the Airflow `load_to_snowflake` task using
the isolated dbt venv (which has snowflake-connector-python + mysql-connector).
"""

import datetime
import os

import mysql.connector
import pandas as pd
import snowflake.connector
from snowflake.connector.pandas_tools import write_pandas

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


def _normalise(value):
    """Bytearray JSON cols and date/datetime objects -> clean text for Snowflake."""
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8")
    if isinstance(value, datetime.date):  # also catches datetime
        return value.isoformat()
    return value


BRONZE_SCHEMA = "BRONZE"


def main():
    mysql_conn = mysql.connector.connect(
        host=os.getenv("MYSQL_HOST", "mysql"),
        user=os.getenv("MYSQL_USER", "root"),
        password=os.getenv("MYSQL_PASSWORD", "root"),
        database=os.getenv("MYSQL_DATABASE", "ml_underground"),
    )
    sf_conn = snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],
        role=os.getenv("SNOWFLAKE_ROLE", "ACCOUNTADMIN"),
        warehouse=os.getenv("SNOWFLAKE_WAREHOUSE", "ML_UNDERGROUND_WH"),
        database=os.getenv("SNOWFLAKE_DATABASE", "ML_UNDERGROUND"),
        schema=os.getenv("SNOWFLAKE_SCHEMA", "PUBLIC"),
    )

    sf_conn.cursor().execute(f"CREATE SCHEMA IF NOT EXISTS {BRONZE_SCHEMA}")

    try:
        for table in BRONZE_TABLES:
            df = pd.read_sql(f"SELECT * FROM {table}", mysql_conn)
            for col in df.columns:
                if pd.api.types.is_datetime64_any_dtype(df[col]):
                    # datetimes -> ISO strings; dbt staging casts them back to
                    # TIMESTAMP (write_pandas auto-create maps datetimes poorly).
                    df[col] = df[col].dt.strftime("%Y-%m-%d %H:%M:%S")
                elif df[col].dtype == object:
                    df[col] = df[col].apply(_normalise)
            df.columns = [c.upper() for c in df.columns]
            sf_conn.cursor().execute(
                f"DROP TABLE IF EXISTS {BRONZE_SCHEMA}.{table.upper()}"
            )
            success, _, nrows, _ = write_pandas(
                sf_conn, df, table.upper(), schema=BRONZE_SCHEMA,
                auto_create_table=True, overwrite=True, quote_identifiers=False,
            )
            print(f"{table}: loaded {nrows} rows (success={success})")
    finally:
        mysql_conn.close()
        sf_conn.close()


if __name__ == "__main__":
    main()
