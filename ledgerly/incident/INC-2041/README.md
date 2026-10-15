# INC-2041 evidence

Exported by the overnight on-call at 11:52 UTC, 2026-10-14. All times UTC.

| File | What |
|---|---|
| `timeline.md` | The on-call's notes while it was happening |
| `api.log.jsonl` | JSON logs from `api1` and `api2`, merged and sorted by `ts`, from 11:21 |
| `worker.log.jsonl` | JSON logs from the worker, 11:21–11:51 |
| `metrics/api1.prom`, `metrics/api2.prom`, `metrics/worker.prom` | Prometheus scrapes every 10 s; each scrape starts with `# scrape <time>` |
| `redis-info.txt` | `INFO memory`, stream length and consumer-group state, sampled every 10 s |

Handy:

```
jq -r 'select(.level=="error") | .msg' api.log.jsonl | sort | uniq -c | sort -rn
grep -n '^# scrape' metrics/worker.prom | head
```
