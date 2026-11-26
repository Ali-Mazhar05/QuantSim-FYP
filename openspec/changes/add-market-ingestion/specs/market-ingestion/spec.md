# Spec Delta: market-ingestion

## Purpose

Fetches end-of-day Bars from the Vendor on a schedule and on demand, within a shared Vendor budget, and publishes them idempotently with visible Revisions, so admins get fresh, exact data every trading day without babysitting. Realizes PRD FR-22, FR-23, FR-24 and FR-31.

## ADDED Requirements

### Requirement: Scheduled daily and catch-up runs
The system SHALL create one `daily` Ingestion run at 22:30 UTC and one `catchup` run at 06:00 UTC on every calendar day, covering every active Instrument, and MUST create at most one run of each mode per date. The scheduler MUST be enabled in exactly one Environment per Vendor API key (TEST in Iteration 1). (PRD FR-22; SPEC FR-MKT-002)

#### Scenario: Duplicate schedule firing creates one run
- **GIVEN** two scheduler instances running
- **WHEN** both fire at 22:30 UTC
- **THEN** exactly one `daily` run exists for that date

#### Scenario: Daily run starts during a backfill
- **GIVEN** a backfill run in progress
- **WHEN** 22:30 UTC arrives
- **THEN** the `daily` run starts within 15 minutes

#### Scenario: Scheduler disabled outside its Environment
- **GIVEN** DEV, where the scheduler is disabled
- **WHEN** 22:30 UTC arrives
- **THEN** no run is created unless an admin triggers one

### Requirement: Admin triggers manual and backfill runs
The system SHALL let an admin trigger a `manual` run (optional window and Instrument list) or a `backfill` run (explicit start date, default 2015-01-02), answering HTTP 202 with the run id within 800 ms while the work proceeds asynchronously. (PRD FR-22; SPEC FR-MKT-002, NFR-PERF-004; MID FR-01)

#### Scenario: Trigger is acknowledged at once
- **GIVEN** an admin
- **WHEN** they trigger a `manual` run
- **THEN** the response is HTTP 202 with the run id within 800 ms

#### Scenario: Overlapping run is refused
- **GIVEN** an unfinished run whose Instruments and window overlap the request
- **WHEN** an admin triggers the run
- **THEN** the response is HTTP 409 with the id of the active run

#### Scenario: Non-admin trigger is refused
- **GIVEN** a quant, analyst or viewer
- **WHEN** they trigger a run
- **THEN** they get HTTP 403

### Requirement: Default run window
Without an explicit window, each Instrument's window SHALL start 5 Sessions before its last stored Bar and end at the latest Session whose close has passed, using the exchange's local date (America/New_York for XNYS). A new Instrument SHALL start at the backfill start date. (PRD FR-22)

#### Scenario: Weekend run finds nothing new
- **GIVEN** a run created on a Sunday with all Bars up to Friday stored
- **WHEN** it executes
- **THEN** it ends `succeeded` with zero new Bars

#### Scenario: New Instrument starts at the backfill date
- **GIVEN** an Instrument with no stored Bars
- **WHEN** a run without an explicit window executes
- **THEN** its window starts at 2015-01-02

### Requirement: Runs are recorded per Instrument
Each run SHALL record its mode, status, window, requesting User or `scheduler`, Ruleset version, start and finish times and error, plus one Run item per Instrument with counts and error. Status MUST be one of `pending`, `running`, `succeeded`, `partially_succeeded`, `failed`. (PRD FR-22; SPEC FR-MKT-002)

#### Scenario: Run record is complete
- **GIVEN** a finished run over three Instruments
- **WHEN** its record is read
- **THEN** it shows mode, status, window, requester, Ruleset version, times, and three Run items with counts

#### Scenario: Database refuses an unknown status
- **GIVEN** the run table
- **WHEN** a row with status `done` is written
- **THEN** the database refuses it

### Requirement: One worker executes a run at a time
The system MUST execute each run on only one worker at a time, and a run interrupted by a worker crash MUST be recoverable by re-running it with the same final result. (PRD FR-23; SPEC NFR-REL-005)

#### Scenario: Two workers do not double-execute
- **GIVEN** two workers and one pending run
- **WHEN** both try to claim work
- **THEN** only one executes the run

#### Scenario: Crashed run is recovered
- **GIVEN** a worker that crashed mid-run
- **WHEN** the next worker claims work
- **THEN** the run is re-executed and ends with the same Bars, Revisions and Events as an uninterrupted run

### Requirement: Idempotent publication with Revisions
Ingesting the same window again MUST add no Bars and publish no Events. A changed Vendor value for a published Bar SHALL create a Revision: the revision number increases, previous values are retained, and `bar.corrected` is published. A correction that fails the Cleaning gate MUST NOT create a Revision. (PRD FR-23; SPEC FR-MKT-002, NFR-REL-008; MID TC-01)

#### Scenario: Identical re-run adds nothing
- **GIVEN** a window already ingested
- **WHEN** the identical window is run again
- **THEN** the second run produces zero new Bars, zero Revisions and zero Events

#### Scenario: Changed close creates one Revision
- **GIVEN** a published Bar whose Vendor close value has changed
- **WHEN** the window is re-run
- **THEN** exactly one Revision and one `bar.corrected` Event are produced and the previous value can be read

#### Scenario: Invalid correction is rejected, not revised
- **GIVEN** a Vendor correction whose new values fail the Cleaning gate
- **WHEN** it is processed
- **THEN** no Revision is created, the published Bar is unchanged, and the record is stored as a Rejected bar

### Requirement: Vendor calls are bounded and retried
Every Vendor call MUST time out after at most 30 seconds. Timeouts, HTTP 5xx and HTTP 429 SHALL be retried with backoff up to 4 attempts in total, honouring `Retry-After`. Unknown symbols and refused requests MUST NOT be retried. (PRD FR-24; SPEC NFR-PERF-005)

#### Scenario: 429 with Retry-After then success
- **GIVEN** a recorded Vendor response of HTTP 429 with `Retry-After` followed by success
- **WHEN** the Instrument is fetched
- **THEN** the call waits as instructed, retries, and succeeds

#### Scenario: Unknown symbol is not retried
- **GIVEN** a Vendor response for an unknown symbol
- **WHEN** the Instrument is fetched
- **THEN** exactly one call is made and only that Run item fails with a reason while other Instruments continue

#### Scenario: Malformed response publishes nothing
- **GIVEN** a malformed Vendor response
- **WHEN** it is received
- **THEN** the Run item fails with reason `malformed_response` and nothing from that response is published

### Requirement: Vendor failure degrades the run
After 5 consecutive Vendor failures (timeouts, HTTP 5xx, HTTP 429 only) the system SHALL defer the remaining Instruments and end the run `partially_succeeded`, naming them. A Vendor authentication failure MUST end the run `failed` with reason `vendor_auth` and make no further calls. (PRD FR-24; SPEC NFR-REL-006; MID section 7.6)

#### Scenario: Circuit opens after five failures
- **GIVEN** a run over 40 Instruments where the Vendor times out 5 times in a row
- **WHEN** the fifth failure occurs
- **THEN** the remaining Instruments are deferred and the run ends `partially_succeeded` naming them

#### Scenario: Authentication failure stops the run
- **GIVEN** the Vendor answers HTTP 401
- **WHEN** the run fetches its first Instrument
- **THEN** the run ends `failed` with reason `vendor_auth` and no further Vendor call is made

#### Scenario: Repeated deferral is visible
- **GIVEN** an Instrument deferred by 2 consecutive runs
- **WHEN** the data-quality view is read
- **THEN** it shows the Instrument with its deferral count

### Requirement: Shared Vendor budget
One hourly Vendor budget SHALL be shared by every worker and Environment using the same Vendor API key, and combined usage MUST NOT exceed it. When it is exhausted remaining Instruments MUST be deferred, and backfill and manual runs MUST NOT spend the reserve for that day's `daily` and `catchup` runs. (PRD FR-24, FR-22; SM-C4)

#### Scenario: Concurrent callers stay within budget
- **GIVEN** a budget of 45 requests per hour and three concurrent workers
- **WHEN** they request 60 calls within the hour
- **THEN** at most 45 calls reach the Vendor and the rest are deferred

#### Scenario: Backfill cannot take the daily reserve
- **GIVEN** 40 active Instruments and a backfill in progress
- **WHEN** the backfill requests budget
- **THEN** it is refused once only the reserve of one request per active Instrument per scheduled run remains

### Requirement: Fixture Vendor for recorded responses
An Environment SHALL be switchable to a fixture Vendor that serves recorded responses. Fixture data MUST be ingested only for dedicated planted Instruments, marked as such, and excluded from real Instruments' data-quality totals. No automated test SHALL call the real Vendor. (PRD FR-24)

#### Scenario: Planted data stays separate
- **GIVEN** TEST switched to the fixture Vendor
- **WHEN** the planted-fault window is ingested
- **THEN** only planted Instruments receive Bars and the data-quality totals of real Instruments are unchanged

### Requirement: Ingestion observability
Every ingestion log line SHALL carry the run id, Instrument and Vendor and MUST NOT contain the Vendor API key. Metrics SHALL cover runs by status and duration, Bars by outcome, rejections by rule, Vendor calls by status and latency, budget waits, circuit state and outbox backlog. (PRD FR-31; SPEC NFR-OBS-002, NFR-OBS-003)

#### Scenario: Log lines carry context and no key
- **GIVEN** a run that fetches and fails one Instrument
- **WHEN** its logs are inspected
- **THEN** every line has run id, Instrument and Vendor, and the API key appears nowhere

#### Scenario: Readiness reflects dependencies
- **GIVEN** Redis is unreachable
- **WHEN** `/api/market/ready` is called
- **THEN** it returns 503, while `/api/market/health` still reports the build Content hash
