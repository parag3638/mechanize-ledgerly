# --- shared deps stage: keep byte-identical in app, dev and grader so BuildKit builds it once ---
FROM python:3.12-slim AS deps
ENV UV_PROJECT_ENVIRONMENT=/opt/venv UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy UV_HTTP_TIMEOUT=30 UV_HTTP_RETRIES=8 UV_CONCURRENT_DOWNLOADS=1
RUN pip install --no-cache-dir --default-timeout=120 --retries 8 uv==0.11.6
COPY ledgerly/pyproject.toml ledgerly/uv.lock /opt/deps/
RUN cd /opt/deps && uv sync --frozen --no-install-project && rm -rf /root/.cache
# --- end shared deps stage ---

# Runtime for api1/api2/worker/migrate. Dependencies only: the code comes from the
# shared `repo` volume at /workspace/ledgerly so edits in the dev container go live.
# api/worker run under the audited supervisor (as root), which runs the service as `app`.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH
COPY --from=deps /opt/venv /opt/venv
COPY task/images/app/devseed.py /opt/task/devseed.py
COPY task/supervisor/supervisor.py /opt/supervisor/supervisor.py
RUN useradd --uid 1000 --create-home app
WORKDIR /workspace/ledgerly
