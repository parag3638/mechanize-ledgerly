# Changelog

All notable changes to Ledgerly. Newest first. Each entry says what changed and why; incident fixes reference the incident id.

## [1.14.0] - 2026-07-29

### Added
- Index `ix_charges_customer_created` (migration 0003), built concurrently, for the merchant dashboard's per-customer history.

### Changed
- Worker concurrency raised from 8 to 12 threads to keep up with the back-to-school peak.

## [1.13.0] - 2026-03-18

### Added
- Refunds: `POST /refunds`, `GET /refunds?charge_id=` (migration 0002).

### Fixed
- Worker no longer loses charges when Redis fails over: unacknowledged stream entries are reclaimed on start (INC-1877).

## [1.12.0] - 2026-01-12

### Added
- First release of the charges service: `POST /charges`, `GET /charges/{id}`, worker, migration 0001.
