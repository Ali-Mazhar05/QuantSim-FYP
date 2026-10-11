# Spec Delta: market-instruments

## Purpose

Maintains the admin-curated Instrument master of US-listed equities and ETFs that QuantSim tracks, validated against official exchange listings, so every ingestion and read works from a trustworthy list. Realizes PRD FR-20 and FR-21 (SPEC FR-MKT-001, FR-PLT-006).

## ADDED Requirements

### Requirement: Admin adds an Instrument
The system SHALL let an admin add an Instrument through the market API with symbol, name, sector, listing exchange, currency, asset class (`equity` or `etf`), optional Vendor symbol and notes, creating it as `active`, publishing `instrument.created` and recording an Audit entry. Adding is API-only; the POC Instruments page stays read-only. (PRD FR-20; SPEC FR-MKT-001, FR-PLT-006, NFR-AUD-001)

#### Scenario: Admin adds a new Instrument
- **GIVEN** an admin and a symbol and exchange not yet in the Instrument master
- **WHEN** the admin adds the Instrument
- **THEN** it is created with status `active` and its sector
- **AND** an `instrument.created` Event is published and one Audit entry is recorded

#### Scenario: Duplicate symbol and exchange is refused
- **GIVEN** an Instrument with the same symbol and exchange already exists, even if it is retired
- **WHEN** an admin adds it again
- **THEN** the response is HTTP 409 naming the existing Instrument id and status

#### Scenario: Database refuses a duplicate inserted directly
- **GIVEN** an existing Instrument
- **WHEN** a second row with the same symbol and exchange is inserted directly into the database
- **THEN** the database refuses it

### Requirement: Admin annotates and retires Instruments
The system SHALL let an admin change an Instrument's name, sector and notes and retire it, through the market API only. Retiring MUST be non-destructive and idempotent, MUST publish `instrument.retired`, and every change MUST be audited. Re-activation is out of scope for Iteration 1. (PRD FR-20; SPEC FR-MKT-001, FR-PLT-006)

#### Scenario: Retire keeps history and excludes future runs
- **GIVEN** an active Instrument with stored Bars
- **WHEN** an admin retires it
- **THEN** it becomes `retired`, keeps its Bars and history, still appears in history queries, and is excluded from every later Ingestion run
- **AND** an `instrument.retired` Event is published and an Audit entry is recorded

#### Scenario: Retiring twice has no further effect
- **GIVEN** a retired Instrument
- **WHEN** an admin retires it again
- **THEN** nothing changes and no further Event is published

#### Scenario: Annotation is audited
- **GIVEN** an active Instrument
- **WHEN** an admin changes its name, sector or notes
- **THEN** the change is saved and one Audit entry holds the before and after state

### Requirement: Only admins change the Instrument master
The system MUST refuse add, annotate and retire for quant, analyst and viewer Users, and SHALL let every signed-in User list Instruments filtered by status. (PRD FR-20, FR-16; SPEC FR-PLT-005, NFR-SEC-001)

#### Scenario: Non-admin change is refused
- **GIVEN** a signed-in quant, analyst or viewer
- **WHEN** they add, annotate or retire an Instrument
- **THEN** they get HTTP 403

#### Scenario: Any signed-in User lists Instruments
- **GIVEN** a signed-in viewer
- **WHEN** they list Instruments with status `active`
- **THEN** they receive the active Instruments

#### Scenario: Unauthenticated listing is refused
- **GIVEN** a request with no token
- **WHEN** it lists Instruments
- **THEN** it gets HTTP 401

### Requirement: Instrument administration is API-only
Adding, annotating and retiring Instruments, and Symbol directory validation, SHALL be available only through the market API (its interactive docs at `/api/market/docs`). The change MUST NOT add any screen, field, column or control to the POC frontend. (PRD FR-20, Conventions; addendum section G)

#### Scenario: Admin works through the API docs
- **GIVEN** a signed-in admin on `/api/market/docs`
- **WHEN** they add an Instrument there
- **THEN** it is created and appears on the POC Instruments page with no change to that page's layout or controls

### Requirement: Seed the starting universe
The system SHALL provide a seed command that loads the 40-Instrument starting universe (30 large-cap equities, 10 ETFs). Running it again MUST add nothing, and it MUST NOT depend on the Symbol directory. (PRD FR-20; addendum D5)

#### Scenario: Seed loads 40 Instruments
- **GIVEN** an empty Instrument master
- **WHEN** the seed command runs
- **THEN** 40 Instruments exist: 30 equities and 10 ETFs, each with a name and sector

#### Scenario: Seed is idempotent
- **GIVEN** the seed has already run
- **WHEN** it runs again
- **THEN** no Instrument is added

#### Scenario: Seed works without a Symbol directory copy
- **GIVEN** no Symbol directory copy has ever been stored
- **WHEN** the seed command runs
- **THEN** it succeeds

### Requirement: Validate new Instruments against the Symbol directory
When an admin adds an Instrument, the system SHALL check the symbol against the latest Symbol directory copy and set or confirm the listing exchange from the directory's exchange code (Nasdaq XNAS, NYSE XNYS, NYSE American XASE, NYSE Arca ARCX, Cboe BZX BATS, IEX IEXG). (PRD FR-21; strengthens SPEC FR-MKT-001; addendum D)

#### Scenario: Listed symbol is accepted with its exchange
- **GIVEN** a symbol listed in `otherlisted.txt` with exchange code `N`
- **WHEN** an admin adds it without an exchange
- **THEN** it is accepted with listing exchange XNYS

#### Scenario: ETF asset class is suggested
- **GIVEN** a symbol the directory marks as an ETF
- **WHEN** an admin adds it
- **THEN** the asset class `etf` is suggested

#### Scenario: Test issue is refused
- **GIVEN** a symbol the directory marks as a test issue
- **WHEN** an admin adds it
- **THEN** it is refused with HTTP 422 and reason `test_issue`

#### Scenario: Unlisted symbol is refused unless overridden
- **GIVEN** a symbol not found in the directory
- **WHEN** an admin adds it without an override reason
- **THEN** it is refused with HTTP 422 and reason `not_listed`
- **AND** when the admin supplies an override reason, it is added and the reason is recorded in the Audit entry

#### Scenario: Exchange mismatch is refused unless overridden
- **GIVEN** an admin-supplied exchange that differs from the directory's
- **WHEN** the add is submitted without an override reason
- **THEN** it is refused with HTTP 422 and reason `exchange_mismatch`

### Requirement: Symbol directory degrades safely
If the directory cannot be downloaded the system SHALL use the last successful copy, warning `stale_directory` when it is older than 3 days. With no copy at all it MUST refuse adds with HTTP 503 `directory_unavailable` unless overridden. Validation MUST NOT block longer than 5 seconds. (PRD FR-21; SPEC NFR-PERF-005, NFR-REL-006)

#### Scenario: Stale copy is used with a warning
- **GIVEN** the download failed and the last copy is 4 days old
- **WHEN** an admin adds a listed symbol
- **THEN** the add is validated against that copy and the response carries a `stale_directory` warning

#### Scenario: No copy on a fresh Environment
- **GIVEN** a fresh Environment with no stored copy and a failed download
- **WHEN** an admin adds an Instrument without an override reason
- **THEN** it is refused with HTTP 503 and reason `directory_unavailable`

#### Scenario: Slow validation times out
- **GIVEN** directory validation that has not finished after 5 seconds
- **WHEN** the timeout is reached
- **THEN** the system behaves as for a failed download

### Requirement: Daily directory refresh reports delisted candidates
The system SHALL refresh the Symbol directory daily, log each failed refresh, expose the directory's age as a metric, and mark active Instruments missing from the directory as `delisted_candidate` in the data-quality view. It MUST NOT retire them automatically. (PRD FR-21, FR-31)

#### Scenario: Missing Instrument becomes a delisted candidate
- **GIVEN** an active Instrument absent from today's directory files
- **WHEN** the daily refresh completes
- **THEN** the Instrument is shown as `delisted_candidate` and remains `active`

#### Scenario: Failed refresh keeps the last copy
- **GIVEN** the directory download fails
- **WHEN** the refresh ends
- **THEN** the failure is logged, the previous copy is kept, and the directory age metric keeps increasing

#### Scenario: Trailer line is ignored
- **GIVEN** directory files ending with a "File Creation Time" trailer line
- **WHEN** they are parsed
- **THEN** the trailer line is not treated as a symbol
