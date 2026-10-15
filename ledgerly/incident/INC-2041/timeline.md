# INC-2041 — on-call notes (overnight on-call, handing over at 11:55)

- **11:22** PagerDuty: `POST /charges` 5xx rate > 5%. Dashboards: errors climbing on both API replicas.
- **11:23** Paystream status page green. Checked api1/api2: up, but slow; `/healthz` intermittently timing out from the load balancer.
- **11:25** Redis memory alarm (growth rule): `used_memory` up ~20% since 11:21 and still climbing. Charges stream length growing.
- **11:26** Worker up but `charges_processed_total` flat. Lots of `retrying after transient error` in worker logs.
- **11:28** Considered bumping Redis `maxmemory` / eviction; didn't, not sure it's safe for the stream.
- **11:30** Merchant support: "payments stuck on processing" from several merchants. One merchant says a customer was charged twice.
- **11:31** Traffic easing off.
- **11:32** Restarted the worker (`ledgerlyctl restart worker`). Backlog started draining within a minute; error rate back to normal.
- **11:34** Backlog nearly empty, but 12 charges still `pending` and not moving. Redis memory hasn't come down.
- **11:36** Finance: they see some customers charged twice for the same order. Asked them to hold off contacting customers until we have a count.
- **11:50** Restarted the worker again; the 12 stragglers completed.
- **11:52** Exported logs/metrics into `incident/INC-2041/`. Nothing changed in code or config. Handing over.
