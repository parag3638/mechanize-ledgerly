#!/bin/sh
# Seed the shared repo volume on first start, start the shell audit log, then hand off to CMD.
set -eu
REPO=/workspace/ledgerly
mkdir -p /var/log/ledgerly-shell /var/lib/ledgerly
if [ ! -f /var/log/ledgerly-shell/commands.log ]; then
    : > /var/log/ledgerly-shell/commands.log
    chmod 0622 /var/log/ledgerly-shell/commands.log
fi
if [ ! -f "$REPO/pyproject.toml" ]; then
    cp -a /opt/ledgerly-seed/. "$REPO/"
    chown -R dev:dev "$REPO"
fi
if [ ! -f /var/lib/ledgerly/session_start ]; then
    date -u +%Y-%m-%dT%H:%M:%S.%3NZ > /var/lib/ledgerly/session_start
fi
exec "$@"
