# INC-1877: Charges stuck in pending after Redis failover

- **Date:** 2026-03-02
- **Authors:** Priya N., Tomasz K.
- **Status:** final
- **Severity:** SEV2

## Summary

A planned Redis failover at 14:05 dropped the worker's stream connection. The worker reconnected with a new consumer name and never picked up the 312 entries its previous incarnation had read but not acknowledged. Those charges sat in `pending` for up to 47 minutes until we claimed them by hand.

## Impact

- 312 charges delayed by 9–47 minutes (count from `charges` where `status = 'pending'` and `created_at` between 14:04 and 14:06, confirmed against the stream's pending list).
- No charge was lost or duplicated. No customer was charged twice.

## Timeline

| Time | Event |
|---|---|
| 14:05 | Redis failover (planned maintenance) |
| 14:06 | Worker logs `ConnectionError`, reconnects as a new consumer |
| 14:31 | Merchant support reports orders stuck at "processing payment" |
| 14:38 | On-call finds 312 entries pending for the old consumer (`XPENDING`) |
| 14:52 | Entries claimed by hand with `XCLAIM`; backlog drains in 2 minutes |

## Root cause(s)

The worker only read new entries (`>`). Entries delivered to a consumer that disappeared stay pending forever unless someone claims them.

## Things that looked like causes but weren't

Redis memory jumped 30% after the failover. That was the replica's fresh allocator, not a leak.

## Resolution

Worker now reclaims entries idle for more than 30 s on start (`XAUTOCLAIM`). Regression test added.

## What went well / what went badly

- Well: the stream kept every entry; nothing was lost.
- Badly: we learned about it from merchants. No alert on stream pending count.

## Action items

| Action | Owner | Due |
|---|---|---|
| Reclaim idle entries on worker start | Tomasz K. | done (1.13.0) |
| Alert on `stream_backlog` > 500 for 5 min | Priya N. | 2026-04-15 |
| Agree a house retry standard for dependency calls | Platform | done (see ARCHITECTURE.md) |

## Communication log

| Time | Who | What |
|---|---|---|
| 14:40 | On-call → #merchants | "Some charges are delayed; no action needed, they will complete." |
| 15:05 | On-call → Finance | Final count of delayed charges; none duplicated. |
