FROM python:3.11-slim

RUN pip install --no-cache-dir \
    prometheus-client \
    mysql-connector-python \
    qdrant-client

WORKDIR /app
COPY pipeline_exporter.py .

CMD ["python", "pipeline_exporter.py"]
