FROM apache/airflow:2.8.0
RUN pip install pymysql mysql-connector-python requests python-dotenv huggingface-hub sentence-transformers qdrant-client

# Pre-download the embedding model so the embed_repos task runs offline.
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

# Isolated venv for dbt + the Snowflake loader — keeps their deps off Airflow.
# PIP_USER=false: the airflow image defaults pip to --user, which breaks venv installs.
RUN python -m venv /home/airflow/dbt-venv && \
    PIP_USER=false /home/airflow/dbt-venv/bin/pip install --no-cache-dir \
        dbt-snowflake snowflake-connector-python[pandas] mysql-connector-python

# build-essential: Great Expectations pulls backports.zoneinfo on Python 3.8,
# which has no aarch64 wheel and must be compiled from source.
USER root
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
 && rm -rf /var/lib/apt/lists/*
USER airflow

# Isolated venv for Great Expectations (the data-quality gate).
RUN python -m venv /home/airflow/ge-venv && \
    PIP_USER=false /home/airflow/ge-venv/bin/pip install --no-cache-dir \
        'great-expectations[mysql]'
