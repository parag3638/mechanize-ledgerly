# Mock payment processor. Its source is never in the agent's container.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN pip install --no-cache-dir --default-timeout=120 --retries 8 fastapi==0.143.1 uvicorn==0.54.0

COPY task/processor/app.py task/processor/schedule.py /opt/processor/
COPY task/baseline/processor_ledger.json* /opt/processor/baseline/
RUN useradd --uid 1001 --create-home processor
USER processor
WORKDIR /opt/processor
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "warning", "--backlog", "4096"]
