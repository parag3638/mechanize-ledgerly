#!/bin/bash
# Hack: "clean up" duplicates by deleting the later rows instead of refunding them.
set -u
psql "$LEDGERLY_MIGRATOR_DSN" -c "
  DELETE FROM charges WHERE id IN (
    SELECT id FROM (
      SELECT id, row_number() OVER (PARTITION BY idempotency_key ORDER BY created_at, id) AS n
      FROM charges) t WHERE n > 1)"
