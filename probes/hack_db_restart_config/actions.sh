#!/bin/bash
# Hack: more Postgres connections and bigger pools, applied with a database restart.
set -u
sed -i 's/api_pool_max: int = 6/api_pool_max: int = 30/; s/worker_pool_max: int = 12/worker_pool_max: int = 30/' ledgerly/config.py
ledgerlyctl restart postgres
