# Spec Delta: market-returns

## Purpose

Computes and publishes one authoritative Return series per Instrument and records Corporate actions with both raw and adjusted prices, so no downstream module re-derives returns differently. Realizes PRD FR-27 and FR-28 (SPEC FR-MKT-003, FR-MKT-010).

## ADDED Requirements

### Requirement: Return series definitions
For each Instrument and Session the system SHALL store the log return ln(close_t / close_t-1), the adjusted log return computed the same way on the Vendor's split- and dividend-adjusted close, and 20- and 60-session volatility as the sample standard deviation (n - 1) of the last N adjusted log returns times the square root of 252, undefined until N returns exist. (PRD FR-27; SPEC FR-MKT-003)

#### Scenario: Values match the hand-computed fixture
- **GIVEN** the hand-computed returns fixture
- **WHEN** the Return series is computed
- **THEN** every value matches to within 1 x 10^-8 absolute

#### Scenario: Volatility undefined before N returns
- **GIVEN** an Instrument with 19 adjusted log returns
- **WHEN** the 20-session volatility is read
- **THEN** it is undefined (null), not zero

#### Scenario: Split day shows no adjusted jump
- **GIVEN** a 2-for-1 split Session
- **WHEN** the adjusted log return is computed
- **THEN** it shows no jump, while the raw log return reflects the halving

#### Scenario: Dividend day matches the adjusted closes
- **GIVEN** a cash dividend ex-date Session
- **WHEN** the adjusted log return is computed
- **THEN** it equals the value computed by hand from the adjusted closes

### Requirement: Recompute from the earliest change
After each run the system SHALL recompute the Return series for each affected Instrument starting at the earliest new or revised Session, store it, and publish it in the `bar.ingested` Event. A Revision on an old Session MUST trigger recomputation from that Session onward and nowhere else. (PRD FR-27, FR-23)

#### Scenario: Old Revision recomputes forward only
- **GIVEN** a Revision on a Session 30 Sessions ago
- **WHEN** the run ends
- **THEN** returns from that Session onward are recomputed and returns before it are unchanged

#### Scenario: Run with no changes recomputes nothing
- **GIVEN** a run that added and revised no Bars
- **WHEN** it ends
- **THEN** no Return series value changes and no `bar.ingested` Event is published

### Requirement: Corporate actions recorded
The system SHALL record each split in the Vendor data as one Corporate action with a split factor greater than 0, and each cash dividend as one Corporate action with the cash amount on its ex-date Session. (PRD FR-28; SPEC FR-MKT-010)

#### Scenario: Split recorded once
- **GIVEN** Vendor data with a 4-for-1 split
- **WHEN** it is ingested twice
- **THEN** exactly one Corporate action with split factor 4 exists

#### Scenario: Dividend recorded on ex-date
- **GIVEN** Vendor data with a 0.24 cash dividend
- **WHEN** it is ingested
- **THEN** one Corporate action with amount 0.24 exists on the ex-date Session

#### Scenario: Database refuses a non-positive split factor
- **GIVEN** the Corporate action table
- **WHEN** a split with factor 0 is inserted directly
- **THEN** the database refuses it

### Requirement: Raw and adjusted series both kept
The system SHALL keep raw Bars and serve adjusted prices on request, and MUST NOT overwrite raw Bars with adjusted values. (PRD FR-28; addendum D3)

#### Scenario: Adjusted request does not touch raw
- **GIVEN** an Instrument with a recorded split
- **WHEN** Bars are requested with `adjusted=true` and then without it
- **THEN** the first response is split-adjusted and the second returns the original raw values
