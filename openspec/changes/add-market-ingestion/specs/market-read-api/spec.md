# Spec Delta: market-read-api

## Purpose

Lets signed-in Users read Instruments, exact Bars and the Return series, and lets admins, quants and analysts read run history, Rejected bars and data quality, through a role-checked, documented HTTP API. Realizes PRD FR-29 (SPEC FR-MKT-001..003, FR-MKT-011, NFR-PERF-002).

## ADDED Requirements

### Requirement: Read Bars in Session order
The system SHALL return an Instrument's Bars for a date range, raw or adjusted, paginated, in Session order, with exact decimal prices, revision numbers and Quality flags, to any signed-in User. (PRD FR-29; SPEC FR-MKT-001, FR-MKT-002, NFR-INT-001; MID FR-03, TC-04)

#### Scenario: One clean Bar per Session
- **GIVEN** a quant and an Instrument ingested from 2015-01-02
- **WHEN** they request Bars from 2015-01-02 to today
- **THEN** they receive one Bar per trading Session in order, with no weekends or holidays, and prices as exact decimals with 8 decimal places

#### Scenario: Revised Bar shows its revision
- **GIVEN** a Bar corrected once by the Vendor
- **WHEN** it is read
- **THEN** it shows `revision: 2` and the previous values remain readable

#### Scenario: Unauthenticated read is refused
- **GIVEN** a request with no token
- **WHEN** it reads Bars
- **THEN** it gets HTTP 401

#### Scenario: Unknown Instrument
- **GIVEN** an Instrument id that does not exist
- **WHEN** its Bars are requested
- **THEN** the response is HTTP 404

### Requirement: Bars carry provenance
Each Bar SHALL carry the Ingestion run that published its current revision, the Vendor and the Ruleset version, and previous revisions MUST carry the same fields. (PRD FR-29)

#### Scenario: Provenance on current and previous revisions
- **GIVEN** a Bar at revision 2
- **WHEN** it and its previous revision are read
- **THEN** each shows its own run id, Vendor and Ruleset version

### Requirement: Read the Return series
The system SHALL return the Return series for an Instrument and date range in Session order to any signed-in User. (PRD FR-29; SPEC FR-MKT-003)

#### Scenario: Viewer reads returns
- **GIVEN** a signed-in viewer
- **WHEN** they request the Return series for one year
- **THEN** they receive log return, adjusted log return and both volatilities per Session

### Requirement: Operational reads restricted
Run history, run detail with its Reconciliation report, Rejected bars with reasons, and the data-quality summary SHALL be readable by admins, quants and analysts, and MUST return HTTP 403 to viewers. (PRD FR-29, FR-16; SPEC FR-MKT-011, NFR-SEC-001)

#### Scenario: Analyst reads Rejected bars
- **GIVEN** an analyst and a run with rejections
- **WHEN** they read the run's Rejected bars
- **THEN** each record shows every rule it broke and its raw payload

#### Scenario: Viewer refused on operational reads
- **GIVEN** a signed-in viewer
- **WHEN** they read run history, Rejected bars or data quality
- **THEN** each request gets HTTP 403

### Requirement: Data-quality summary
The data-quality summary SHALL show, for each real Instrument, its last clean Session, Bar count, open Data gaps and flagged Bars, plus deferral counts, `delisted_candidate` marks and any `stale_directory` warning. Planted fixture Instruments MUST be excluded from real Instruments' totals. (PRD FR-29, FR-21, FR-24)

#### Scenario: Sort by open gaps
- **GIVEN** three Instruments with 0, 2 and 1 open Data gaps
- **WHEN** an analyst sorts the summary by open gaps
- **THEN** the Instrument with 2 gaps is first

#### Scenario: Planted Instruments excluded
- **GIVEN** planted fixture Instruments with rejections
- **WHEN** the real-Instrument totals are read
- **THEN** the planted Instruments' counts are not included

### Requirement: Published API contract
The API contract SHALL be exported as an OpenAPI document on every build, and the frontend's typed client SHALL be generated from it so an incompatible change breaks the frontend type check. (PRD FR-29; SPEC NFR-MNT-005 partial)

#### Scenario: Incompatible change is caught
- **GIVEN** a change that renames a Bar field
- **WHEN** the pipeline runs
- **THEN** the regenerated client breaks the frontend type check and the pull request check fails

### Requirement: Read latency
Standard reads MUST complete within 800 ms at p95 for a 1-year window of one Instrument, measured as 200 sequential requests from one client through the gateway on TEST. (PRD FR-29; SPEC NFR-PERF-002)

#### Scenario: Measured p95
- **GIVEN** TEST with a fully ingested Instrument
- **WHEN** 200 sequential one-year Bar requests are sent through the gateway
- **THEN** the p95 latency is at most 800 ms and the result is recorded
