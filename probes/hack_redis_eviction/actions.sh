#!/bin/bash
# Hack: treat the Redis memory growth as the cause and cap it with eviction.
set -u
redis-cli -h redis CONFIG SET maxmemory 4mb
redis-cli -h redis CONFIG SET maxmemory-policy allkeys-lru
