FROM postgres:16
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 \
    && rm -rf /var/lib/apt/lists/*
COPY task/supervisor/supervisor.py /opt/supervisor/supervisor.py
COPY task/images/postgres/entrypoint.sh /usr/local/bin/ledgerly-pg-entrypoint
COPY task/images/postgres/initdb/ /docker-entrypoint-initdb.d/
COPY task/baseline/ /opt/baseline/
RUN chmod 0755 /usr/local/bin/ledgerly-pg-entrypoint /docker-entrypoint-initdb.d/*.sh
ENTRYPOINT ["/usr/local/bin/ledgerly-pg-entrypoint"]
CMD ["postgres"]
