# Spec Delta: market-read-api

## Purpose

Lets signed-in Users read Instruments, exact Bars and the Return series, and lets admins, quants and analysts read run history, Rejected bars and data quality, through a role-checked, documented HTTP API shaped to the POC frontend; operational reads are API-only, and each finished run contributes one event to the audit feed behind the POC Audit Log page. Realizes PRD FR-29 (SPEC FR-MKT-001..003, FR-MKT-011, NFR-PERF-002; addendum section G).

## ADDED Requirements

### Requirement: Instrument list matches the POC Instruments page
The Instrument list SHALL return, for each Instrument, exactly what the POC Instruments page shows: `symbol`, `name`, `sector`, `price` (the latest clean close, as an 8-decimal string) and `change_pct` (the change from the previous clean close), to any signed-in User. An Instrument with fewer than two clean Bars MUST return no price or change. (PRD FR-29, FR-20; addendum section G)

#### Scenario: Price and change from the last two clean closes
- **GIVEN** an Instrument whose last two clean closes are 200.00000000 and 214.32000000
- **WHEN** a viewer lists Instruments
- **THEN** it is returned with its symbol, name, sector, `price` 214.32000000 and `change_pct` 7.16

#### Scenario: Too few clean Bars
- **GIVEN** an Instrument with one clean Bar
- **WHEN** Instruments are listed
- **THEN** it is returned with symbol, name and sector and no price or change


### Requirement: Read Bars in Session order
The system SHALL return an Instrument's Bars for a date range, raw or adjusted, paginated, in Session order, with exact decimal prices, revision numbers and Quality flags, to any signed-in User. (PRD FR-29; SPEC FR-MKT-001, FR-MKT-002, NFR-INT-001; MID FR-03, TC-04)

#### Scenario: One clean Bar per Session
- **GIVEN** a quant and an Instrument ingested from 2015-01-02
- **WHEN** they request Bars from 2015-01-02 to today
- **THEN** they receive one Bar per trading Session in order, with no weekends or holidays, and prices as exact decimals with 8 decimal places, which the POC Market Data page draws for the last 90 sessions

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
Run history, run detail with its Reconciliation report, Rejected bars with reasons, and the data-quality summary SHALL be readable by admins, quants and analysts, and MUST return HTTP 403 to viewers. They are API-only: no POC screen shows them and none is added. (PRD FR-29, FR-16; SPEC FR-MKT-011, NFR-SEC-001)

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

### Requirement: One audit feed event per Ingestion run
When an Ingestion run reaches a final status, the system SHALL add exactly one event to the platform audit feed read by the POC Audit Log page: user (requester or `System`), service `Market Data`, action `Ingestion run completed`, `partially succeeded` or `failed`, severity `Info`, `Warning` (rejections, gaps or deferrals) or `Critical` (failed), and a one-line detail with counts and rejecting rules. (PRD FR-29, UJ-1)

#### Scenario: Planted-fault run produces a Warning event
- **GIVEN** an admin-triggered run over the Planted-fault dataset that rejects records
- **WHEN** it finishes
- **THEN** one event is added with the admin as user, service `Market Data`, action `Ingestion run completed`, severity `Warning`, and a detail line with received, passed untouched, corrected and rejected counts and the rejecting rules

#### Scenario: Scheduled clean run produces an Info event
- **GIVEN** a scheduled `daily` run with no rejections, gaps or deferrals
- **WHEN** it finishes
- **THEN** one event is added with user `System` and severity `Info`

#### Scenario: Failed run produces a Critical event
- **GIVEN** a run that ends `failed` on `vendor_auth`
- **WHEN** it finishes
- **THEN** one event is added with action `Ingestion run failed` and severity `Critical`

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
