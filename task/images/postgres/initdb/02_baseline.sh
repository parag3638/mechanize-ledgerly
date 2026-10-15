#!/bin/sh
# Restore the INC-2041 handoff database (schema + data) as the schema owner.
set -eu
DUMP=/opt/baseline/ledgerly_baseline.sql.gz
if [ "${LEDGERLY_SKIP_BASELINE:-0}" = "1" ] || [ ! -f "$DUMP" ]; then
    echo "baseline: not restored (capture mode or no snapshot)"
    exit 0
fi
gunzip -c "$DUMP" | psql -v ON_ERROR_STOP=1 -q -U ledgerly_migrator -d ledgerly
echo "baseline: restored $(psql -At -U ledgerly_migrator -d ledgerly -c 'SELECT count(*) FROM charges') charges"
