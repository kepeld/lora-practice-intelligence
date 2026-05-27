"""
GH Archive Kafka Consumer

Reads ML-relevant GitHub events from Kafka and persists them to:
  - MySQL: structured repository metadata (Bronze layer)
  - MinIO: raw JSON archive (raw layer / S3-compatible)
"""

import json
import logging
import os
from datetime import datetime, timezone
from io import BytesIO
from typing import List

import boto3
import mysql.connector
from botocore.client import Config
from kafka import KafkaConsumer

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
KAFKA_TOPIC_ML = "github.events.ml"
KAFKA_GROUP_ID = "ml-underground-consumer"

MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", 3306))
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "root")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "ml_underground")

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "http://localhost:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
MINIO_BUCKET = "github-events-raw"

# How many messages to buffer before flushing to MySQL
MYSQL_BATCH_SIZE = 100

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# MySQL
# ---------------------------------------------------------------------------

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS github_events_bronze (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    event_id        VARCHAR(64)  NOT NULL UNIQUE,
    event_type      VARCHAR(64)  NOT NULL,
    repo_id         BIGINT,
    repo_name       VARCHAR(255),
    actor_login     VARCHAR(128),
    created_at      DATETIME,
    ingested_at     DATETIME,
    raw_payload     JSON,
    INDEX idx_repo_name  (repo_name),
    INDEX idx_event_type (event_type),
    INDEX idx_created_at (created_at)
);

CREATE TABLE IF NOT EXISTS github_repos_bronze (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    repo_id         BIGINT       NOT NULL UNIQUE,
    repo_name       VARCHAR(255) NOT NULL,
    first_seen_at   DATETIME,
    last_seen_at    DATETIME,
    star_count      INT          DEFAULT 0,
    fork_count      INT          DEFAULT 0,
    event_count     INT          DEFAULT 0,
    INDEX idx_repo_id   (repo_id),
    INDEX idx_repo_name (repo_name)
);
"""


def get_mysql_connection():
    return mysql.connector.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DATABASE,
    )


def init_mysql_schema(conn):
    """Create Bronze tables if they do not exist."""
    cursor = conn.cursor()
    for statement in SCHEMA_SQL.strip().split(";"):
        statement = statement.strip()
        if statement:
            cursor.execute(statement)
    conn.commit()
    cursor.close()
    logger.info("MySQL schema initialized")


def upsert_repo(cursor, event: dict):
    """Insert or update repository-level aggregates."""
    repo = event.get("repo", {})
    repo_id = repo.get("id")
    repo_name = repo.get("name")
    if not repo_id or not repo_name:
        return

    now = datetime.now(timezone.utc)
    star_delta = 1 if event.get("type") == "WatchEvent" else 0
    fork_delta = 1 if event.get("type") == "ForkEvent" else 0

    cursor.execute(
        """
        INSERT INTO github_repos_bronze
            (repo_id, repo_name, first_seen_at, last_seen_at, star_count, fork_count, event_count)
        VALUES
            (%s, %s, %s, %s, %s, %s, 1)
        ON DUPLICATE KEY UPDATE
            last_seen_at = VALUES(last_seen_at),
            star_count   = star_count + VALUES(star_count),
            fork_count   = fork_count + VALUES(fork_count),
            event_count  = event_count + 1
        """,
        (repo_id, repo_name, now, now, star_delta, fork_delta),
    )


def insert_event_batch(conn, batch: List[dict]):
    """Write a batch of events to github_events_bronze."""
    cursor = conn.cursor()
    rows = []
    for event in batch:
        repo = event.get("repo", {})
        actor = event.get("actor", {})
        created_raw = event.get("created_at")
        ingested_raw = event.get("ingested_at")

        created_at = None
        if created_raw:
            try:
                created_at = datetime.fromisoformat(created_raw.replace("Z", "+00:00"))
            except ValueError:
                pass

        ingested_at = None
        if ingested_raw:
            try:
                ingested_at = datetime.fromisoformat(ingested_raw)
            except ValueError:
                pass

        rows.append((
            event.get("id"),
            event.get("type"),
            repo.get("id"),
            repo.get("name"),
            actor.get("login"),
            created_at,
            ingested_at,
            json.dumps(event),
        ))
        upsert_repo(cursor, event)

    cursor.executemany(
        """
        INSERT IGNORE INTO github_events_bronze
            (event_id, event_type, repo_id, repo_name, actor_login,
             created_at, ingested_at, raw_payload)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
        rows,
    )
    conn.commit()
    cursor.close()


# ---------------------------------------------------------------------------
# MinIO
# ---------------------------------------------------------------------------

def get_minio_client():
    return boto3.client(
        "s3",
        endpoint_url=MINIO_ENDPOINT,
        aws_access_key_id=MINIO_ACCESS_KEY,
        aws_secret_access_key=MINIO_SECRET_KEY,
        config=Config(signature_version="s3v4"),
    )


def ensure_bucket(s3_client):
    try:
        s3_client.head_bucket(Bucket=MINIO_BUCKET)
    except Exception:
        s3_client.create_bucket(Bucket=MINIO_BUCKET)
        logger.info("Created MinIO bucket: %s", MINIO_BUCKET)


def write_batch_to_minio(s3_client, batch: List[dict], partition_dt: datetime):
    """
    Write a batch of events as a newline-delimited JSON file to MinIO.
    Path pattern: year=YYYY/month=MM/day=DD/hour=HH/<timestamp>.ndjson
    """
    prefix = partition_dt.strftime("year=%Y/month=%m/day=%d/hour=%H")
    key = f"{prefix}/{partition_dt.strftime('%Y%m%d%H%M%S%f')}.ndjson"

    payload = "\n".join(json.dumps(e) for e in batch).encode("utf-8")

    s3_client.put_object(
        Bucket=MINIO_BUCKET,
        Key=key,
        Body=BytesIO(payload),
        ContentType="application/x-ndjson",
    )
    logger.debug("Written %d events to MinIO: %s", len(batch), key)


# ---------------------------------------------------------------------------
# Consumer loop
# ---------------------------------------------------------------------------

def run_consumer():
    logger.info("Connecting to Kafka at %s", KAFKA_BOOTSTRAP_SERVERS)

    consumer = KafkaConsumer(
        KAFKA_TOPIC_ML,
        bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
        group_id=KAFKA_GROUP_ID,
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
        auto_offset_reset="earliest",   # start from the beginning on first run
        enable_auto_commit=False,        # manual commit after successful write
        max_poll_records=MYSQL_BATCH_SIZE,
    )

    mysql_conn = get_mysql_connection()
    init_mysql_schema(mysql_conn)

    s3_client = get_minio_client()
    ensure_bucket(s3_client)

    logger.info("Consumer started. Waiting for messages on %s", KAFKA_TOPIC_ML)

    batch = []
    total_processed = 0

    try:
        for message in consumer:
            event = message.value
            batch.append(event)

            if len(batch) >= MYSQL_BATCH_SIZE:
                _flush_batch(batch, mysql_conn, s3_client)
                consumer.commit()
                total_processed += len(batch)
                logger.info("Flushed %d events (total: %d)", len(batch), total_processed)
                batch = []

    except KeyboardInterrupt:
        logger.info("Shutting down consumer")
    finally:
        # Flush remaining events
        if batch:
            _flush_batch(batch, mysql_conn, s3_client)
            consumer.commit()
            total_processed += len(batch)
            logger.info("Final flush: %d events (total: %d)", len(batch), total_processed)

        consumer.close()
        mysql_conn.close()


def _flush_batch(batch: List[dict], mysql_conn, s3_client):
    """Write a batch to both MySQL and MinIO."""
    now = datetime.now(timezone.utc)

    # Reconnect MySQL if connection dropped
    if not mysql_conn.is_connected():
        mysql_conn.reconnect(attempts=3, delay=2)

    insert_event_batch(mysql_conn, batch)
    write_batch_to_minio(s3_client, batch, now)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run_consumer()