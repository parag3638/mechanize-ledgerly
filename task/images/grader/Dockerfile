# --- shared deps stage: keep byte-identical in app, dev and grader so BuildKit builds it once ---
FROM python:3.12-slim AS deps
ENV UV_PROJECT_ENVIRONMENT=/opt/venv UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy UV_HTTP_TIMEOUT=30 UV_HTTP_RETRIES=8 UV_CONCURRENT_DOWNLOADS=1
RUN pip install --no-cache-dir --default-timeout=120 --retries 8 uv==0.11.6
COPY ledgerly/pyproject.toml ledgerly/uv.lock /opt/deps/
RUN cd /opt/deps && uv sync --frozen --no-install-project && rm -rf /root/.cache
# --- end shared deps stage ---

# The grader. Idle until scoring; the agent can't exec into it and shares no
# writable volume with it. Holds everything the agent must never see: hidden
# tests, hidden load profiles, the baseline facts, the processor schedule.
FROM python:3.12-slim
# Same system layer as the dev image, so it comes from cache.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        postgresql-client redis-tools make git curl procps less jq ca-certificates \
    && rm -rf /var/lib/apt/lists/*
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH
COPY --from=deps /opt/venv /opt/venv
RUN useradd --uid 2000 --create-home runner

COPY ledgerly /grader/base_tree
COPY task/replayer/replay.py /grader/replayer/replay.py
COPY task/processor/schedule.py /grader/processor/schedule.py
COPY task/hidden /grader/hidden
COPY task/grader /grader/grader
RUN chmod -R go-rwx /grader && mkdir -p /grader/work /grader/out

WORKDIR /grader
CMD ["tail", "-f", "/dev/null"]
