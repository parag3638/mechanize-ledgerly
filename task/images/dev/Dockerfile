# --- shared deps stage: keep byte-identical in app, dev and grader so BuildKit builds it once ---
FROM python:3.12-slim AS deps
ENV UV_PROJECT_ENVIRONMENT=/opt/venv UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy UV_HTTP_TIMEOUT=30 UV_HTTP_RETRIES=8 UV_CONCURRENT_DOWNLOADS=1
RUN pip install --no-cache-dir --default-timeout=120 --retries 8 uv==0.11.6
COPY ledgerly/pyproject.toml ledgerly/uv.lock /opt/deps/
RUN cd /opt/deps && uv sync --frozen --no-install-project && rm -rf /root/.cache
# --- end shared deps stage ---

# The agent's workstation. Only ledgerly/ goes in; task/, grader and references never do.
FROM python:3.12-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        postgresql-client redis-tools make git curl procps less jq ca-certificates \
    && rm -rf /var/lib/apt/lists/*
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH
COPY --from=deps /opt/venv /opt/venv
ENV UV_PROJECT_ENVIRONMENT=/opt/venv UV_NO_SYNC=1
RUN useradd --uid 1000 --create-home --shell /bin/bash dev \
    && git config --system safe.directory '*'

# The repo as the agent receives it: one commit, no history.
COPY ledgerly /opt/ledgerly-seed
RUN cd /opt/ledgerly-seed \
    && git init -q -b main \
    && git add -A \
    && git -c user.name="Ledgerly CI" -c user.email=ci@ledgerly.example commit -qm "Ledgerly 1.14.0"

COPY task/bin/ledgerlyctl task/bin/oncall /usr/local/bin/
COPY task/images/dev/audit.sh /etc/ledgerly/audit.sh
COPY task/images/dev/entrypoint.sh /usr/local/bin/ledgerly-dev-entrypoint
RUN chmod 0755 /usr/local/bin/ledgerlyctl /usr/local/bin/oncall /usr/local/bin/ledgerly-dev-entrypoint \
    && chmod 0644 /etc/ledgerly/audit.sh \
    && echo '. /etc/ledgerly/audit.sh' >> /etc/bash.bashrc \
    && echo 'export PATH=/opt/venv/bin:$PATH' > /etc/profile.d/10-ledgerly-venv.sh
# Login shells (agent CLIs run `bash -lc`) reset PATH in /etc/profile; the profile.d line puts
# the project venv back in front, as the image ENV does for every other shell.
ENV BASH_ENV=/etc/ledgerly/audit.sh

WORKDIR /workspace/ledgerly
ENTRYPOINT ["/usr/local/bin/ledgerly-dev-entrypoint"]
CMD ["tail", "-f", "/dev/null"]
