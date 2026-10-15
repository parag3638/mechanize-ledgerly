#!/bin/sh
# Postgres under the supervisor. Statement audit logs go to the shared audit
# volume, readable only by postgres and root (the grader), never by the agent.
set -eu
mkdir -p /var/log/audit/postgres
chown postgres:postgres /var/log/audit/postgres
chmod 0700 /var/log/audit/postgres
exec python3 /opt/supervisor/supervisor.py --service postgres --stop-signal SIGINT -- \
    docker-entrypoint.sh "$@"
