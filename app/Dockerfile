# Build from the repo root: docker build -f app/Dockerfile .
FROM python:3.11-slim

WORKDIR /srv
COPY app/requirements.txt app/requirements.txt
RUN pip install --no-cache-dir -r app/requirements.txt

COPY app /srv/app
COPY ml /srv/ml

# The warehouse file is mounted read-only at /warehouse by compose/terraform.
ENV DUCKDB_PATH=/warehouse/ML_UNDERGROUND.duckdb

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
