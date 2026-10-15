FROM redis:7.4
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 \
    && rm -rf /var/lib/apt/lists/*
COPY task/supervisor/supervisor.py /opt/supervisor/supervisor.py
ENTRYPOINT ["python3", "/opt/supervisor/supervisor.py", "--service", "redis", "--", "docker-entrypoint.sh"]
CMD ["redis-server", "--save", "", "--appendonly", "no"]
