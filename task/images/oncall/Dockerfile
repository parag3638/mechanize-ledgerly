# The simulated on-call lead. The only service with internet access (for the
# optional LLM intent classifier); never reachable except through its HTTP API.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN pip install --no-cache-dir --default-timeout=120 --retries 8 fastapi==0.143.1 uvicorn==0.54.0 openai==3.31.0
COPY task/oncall/server.py task/oncall/classifier.py task/oncall/intents.json \
     task/oncall/cache.json task/oncall/facts.json /opt/oncall/
WORKDIR /opt/oncall
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "warning"]
