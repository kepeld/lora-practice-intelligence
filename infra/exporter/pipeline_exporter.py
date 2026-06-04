"""
Prometheus exporter for ML Underground pipeline metrics.

One source for the Grafana monitoring dashboard: bronze table row counts
(MySQL), Qdrant embedding counts, and the last successful DAG run (Airflow
metadata). Metrics are recomputed on every Prometheus scrape.
"""

import os
import time

import mysql.connector
from prometheus_client import start_http_server
from prometheus_client.core import REGISTRY, GaugeMetricFamily
from qdrant_client import QdrantClient

# bronze metric name -> fully-qualified MySQL table
BRONZE_TABLES = {
    # "repos" is the frozen github_repos_bronze relic; "repos_enriched" is the
    # live LoRA corpus (github_repos_enriched), grown by the hourly enricher.
    "repos": "ml_underground.github_repos_bronze",
    "repos_enriched": "ml_underground.github_repos_enriched",
    "hf_models": "ml_underground.huggingface_models_bronze",
}

QDRANT_COLLECTIONS = ["github_repos", "huggingface_models"]


def collect_mysql():
    """Return (bronze row counts, last successful DAG run unix ts)."""
    counts, last_run = {}, None
    conn = mysql.connector.connect(
        host=os.getenv("MYSQL_HOST", "mysql"),
        user=os.getenv("MYSQL_USER", "root"),
        password=os.getenv("MYSQL_PASSWORD", "root"),
    )
    try:
        cur = conn.cursor()
        for metric, table in BRONZE_TABLES.items():
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            counts[metric] = cur.fetchone()[0]
        cur.execute(
            "SELECT UNIX_TIMESTAMP(MAX(end_date)) FROM airflow.dag_run "
            "WHERE dag_id = 'ml_underground_pipeline' AND state = 'success'"
        )
        row = cur.fetchone()
        last_run = row[0] if row else None
        cur.close()
    finally:
        conn.close()
    return counts, last_run


def collect_qdrant():
    """Return {collection: point_count} for the known collections."""
    counts = {}
    client = QdrantClient(
        host=os.getenv("QDRANT_HOST", "qdrant"),
        port=int(os.getenv("QDRANT_PORT", "6333")),
    )
    existing = {c.name for c in client.get_collections().collections}
    for collection in QDRANT_COLLECTIONS:
        if collection in existing:
            counts[collection] = client.get_collection(collection).points_count
    return counts


class PipelineCollector:
    """Prometheus collector — recomputes pipeline metrics on each scrape."""

    def collect(self):
        try:
            bronze_counts, last_run = collect_mysql()
        except Exception as exc:  # MySQL down / unreachable — skip, don't crash
            print(f"mysql metrics error: {exc}", flush=True)
            bronze_counts, last_run = {}, None

        try:
            qdrant_counts = collect_qdrant()
        except Exception as exc:
            print(f"qdrant metrics error: {exc}", flush=True)
            qdrant_counts = {}

        rows = GaugeMetricFamily(
            "ml_underground_bronze_rows",
            "Row count of a MySQL bronze table",
            labels=["table"],
        )
        for metric, value in bronze_counts.items():
            rows.add_metric([metric], value)
        yield rows

        qdrant = GaugeMetricFamily(
            "ml_underground_qdrant_points",
            "Number of vectors stored in a Qdrant collection",
            labels=["collection"],
        )
        for collection, value in qdrant_counts.items():
            qdrant.add_metric([collection], value)
        yield qdrant

        if last_run is not None:
            yield GaugeMetricFamily(
                "ml_underground_last_successful_dag_run_timestamp",
                "Unix timestamp of the last successful ml_underground_pipeline run",
                value=last_run,
            )


def main():
    port = int(os.getenv("EXPORTER_PORT", "9101"))
    REGISTRY.register(PipelineCollector())
    start_http_server(port)
    print(f"pipeline exporter listening on :{port}", flush=True)
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
