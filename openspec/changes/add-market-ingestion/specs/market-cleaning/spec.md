# Spec Delta: market-cleaning

## Purpose

Checks every Vendor record against named Cleaning rules before it can become a Bar, keeps every rejected record with its reasons, records Data gaps, and accounts for every record in a Reconciliation report that always adds up. Realizes PRD FR-25 and FR-26 (SPEC FR-MKT-011, FR-MKT-002).

## ADDED Requirements

### Requirement: Reject invalid records
The Cleaning gate SHALL reject a record under `malformed` (missing or unparsable field), `outside_window` (date not requested), `non_trading_day` (weekend or exchange holiday), `non_positive_price` (any price at or below 0), `ohlc_order` (low above high, or open or close outside [low, high]) or `negative_volume` (volume below 0). (PRD FR-25; SPEC FR-MKT-011; MID TC-03)

#### Scenario: Inverted OHLC is rejected
- **GIVEN** a record with low 101.00 and high 99.00
- **WHEN** it passes through the gate
- **THEN** it is rejected under `ohlc_order` and is not published

#### Scenario: Weekend record is rejected
- **GIVEN** a record dated on a Saturday inside the requested window
- **WHEN** it passes through the gate
- **THEN** it is rejected under `non_trading_day`

#### Scenario: Negative price is rejected
- **GIVEN** a record with close -5.00
- **WHEN** it passes through the gate
- **THEN** it is rejected under `non_positive_price`

#### Scenario: Unrequested date is rejected
- **GIVEN** a record for a Session outside the run's window
- **WHEN** it passes through the gate
- **THEN** it is rejected under `outside_window`

### Requirement: Handle duplicate Sessions
When the same Session appears more than once, the gate SHALL keep one copy and count the rest under `duplicate_removed` if all copies are identical, and MUST reject all copies under `duplicate_conflict` if any values differ. (PRD FR-25; SPEC FR-MKT-011; MID TC-02)

#### Scenario: Identical duplicates collapse to one
- **GIVEN** two identical records for the same Session
- **WHEN** they pass through the gate
- **THEN** one Bar is published and one record is counted as a duplicate removed

#### Scenario: Conflicting duplicates are all rejected
- **GIVEN** two records for the same Session with different closes
- **WHEN** they pass through the gate
- **THEN** both are rejected under `duplicate_conflict` and no Bar is published for that Session

### Requirement: Flag suspicious records
The gate SHALL publish a record with volume 0 flagged `zero_volume`, and a record whose absolute log return from the previous close exceeds 0.405 flagged `outlier`, except on a split day. When the outlier policy is configured to reject, such records MUST be rejected instead. (PRD FR-25; addendum D4)

#### Scenario: 60% jump is flagged
- **GIVEN** a close 60% above the previous close on a day with no split
- **WHEN** it passes through the gate with the default policy
- **THEN** the Bar is published with the `outlier` flag

#### Scenario: Split day is not an outlier
- **GIVEN** a close that halves on a recorded 2-for-1 split day
- **WHEN** it passes through the gate
- **THEN** no `outlier` flag is set

#### Scenario: Reject policy rejects outliers
- **GIVEN** the outlier policy configured to reject
- **WHEN** a record with a 60% jump passes through the gate
- **THEN** it is rejected under `outlier`

### Requirement: Rejected bars are retained
A rejected record MUST be stored as a Rejected bar with every rule it broke and its raw payload, and MUST NOT be silently dropped. (PRD FR-25; SPEC FR-MKT-011)

#### Scenario: Multiple broken rules are all recorded
- **GIVEN** a record with a negative price and negative volume
- **WHEN** it is rejected
- **THEN** the Rejected bar lists both `non_positive_price` and `negative_volume` and holds the raw payload

### Requirement: Published Bars are always valid
No published Bar SHALL have a price at or below 0 or high below low, and the database MUST refuse such a row even if it bypasses the gate. Prices MUST be fixed-precision decimals with 8 decimal places. (PRD FR-25; SPEC NFR-INT-001)

#### Scenario: Property test over generated inputs
- **GIVEN** randomly generated Vendor records
- **WHEN** they pass through the gate
- **THEN** no published Bar has a price at or below 0 or high below low

#### Scenario: Database refuses a bypassing row
- **GIVEN** a row with high below low
- **WHEN** it is inserted directly into the Bar table
- **THEN** the database refuses it

### Requirement: Session-close timestamps in UTC
Every published Bar's timestamp SHALL be its Session's actual close in UTC from the Trading calendar, including daylight-saving changes and early closes. (PRD FR-25)

#### Scenario: Early close
- **GIVEN** a Bar for the day after US Thanksgiving, an early-close Session
- **WHEN** it is published
- **THEN** its timestamp is 18:00 UTC (13:00 New York)

#### Scenario: Daylight-saving change
- **GIVEN** Bars on the Friday before and the Monday after the March daylight-saving change
- **WHEN** they are published
- **THEN** their timestamps are 21:00 UTC and 20:00 UTC respectively

### Requirement: Data gaps
An expected Session with no clean Bar SHALL be recorded as a Data gap only once its close plus 12 hours has passed. Holidays MUST NOT be recorded as gaps, and a gap SHALL resolve when its Bar arrives. (PRD FR-25)

#### Scenario: Late Bar is not yet a gap
- **GIVEN** the 22:30 UTC daily run and today's Bar not yet published by the Vendor
- **WHEN** the run ends
- **THEN** no Data gap is recorded for today

#### Scenario: Gap resolves on arrival
- **GIVEN** an open Data gap for a Session
- **WHEN** a later run publishes a clean Bar for it
- **THEN** the gap is marked resolved and reported as resolved in that run

#### Scenario: Holiday is never a gap
- **GIVEN** an exchange holiday inside the window
- **WHEN** any run ends
- **THEN** no Data gap exists for it

### Requirement: Versioned ruleset
The Ruleset version applied (Iteration 1: `2026.10.1`) SHALL be stored on each Ingestion run. (PRD FR-25)

#### Scenario: Run carries its Ruleset version
- **GIVEN** a completed run
- **WHEN** its record is read
- **THEN** it shows Ruleset version `2026.10.1`

### Requirement: Reconciliation report adds up
Each run SHALL produce a Reconciliation report for the run and for each Instrument where received = passed untouched + corrected + duplicates removed + rejected, listing counts per Cleaning rule, Quality flags, new and resolved Data gaps, new Bars and Revisions. (PRD FR-26; SPEC FR-MKT-011, FR-MKT-002; MID FR-02)

#### Scenario: Accounting identity holds
- **GIVEN** any generated set of Vendor records
- **WHEN** the report is built
- **THEN** for every Instrument and for the run total, received equals passed untouched plus corrected plus duplicates removed plus rejected

#### Scenario: Planted-fault report matches exactly
- **GIVEN** the Planted-fault dataset and its stored expected report
- **WHEN** it is ingested through the fixture Vendor
- **THEN** the produced report equals the expected report field for field

#### Scenario: Mismatch fails the check
- **GIVEN** a change to a Cleaning rule that alters one count
- **WHEN** the planted-fault test runs
- **THEN** it fails and names the differing field
