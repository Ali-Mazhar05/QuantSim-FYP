# Spec Delta: market-replay

## Purpose

Lets admins and quants define validated Replay sessions over historical Bars, and publishes the tick Event schema of the Market environment interface so replayed and simulated markets share one contract. Playback is Iteration 2. Realizes PRD FR-30 (SPEC FR-MKT-007 create, FR-MKT-008, FR-MKT-009 partial, NFR-INT-003).

## ADDED Requirements

### Requirement: Create a Replay session
The system SHALL let admins and quants create a Replay session with a name, 1 to 100 existing Instruments, a start time, an end time after the start time, and a speed greater than 0 and at most 1000. Any signed-in User SHALL be able to read it. (PRD FR-30; SPEC FR-MKT-007, FR-MKT-008)

#### Scenario: Quant creates a valid session
- **GIVEN** a quant and three existing Instruments
- **WHEN** they create a session from 2020-01-02 to 2020-12-31 at speed 10
- **THEN** it is created and a viewer can read it

#### Scenario: Invalid membership or speed is refused
- **GIVEN** a request with zero Instruments, more than 100, an unknown Instrument, or a speed of 0 or above 1000
- **WHEN** it is submitted
- **THEN** it is refused with HTTP 422

#### Scenario: Analyst or viewer cannot create
- **GIVEN** a signed-in analyst or viewer
- **WHEN** they create a Replay session
- **THEN** they get HTTP 403

### Requirement: Replay window is checked twice
A Replay session whose end time is not after its start time MUST be refused by the API with HTTP 422 and MUST also be refused by the database when inserted directly. (PRD FR-30; SPEC NFR-INT-003)

#### Scenario: Inverted window refused by the API
- **GIVEN** an admin
- **WHEN** they create a session whose end time equals or precedes its start time
- **THEN** the response is HTTP 422

#### Scenario: Inverted window refused by the database
- **GIVEN** the Replay session table
- **WHEN** a row with end time before start time is inserted directly
- **THEN** the database refuses it

### Requirement: Published tick Event schema
The tick Event schema of the Market environment interface SHALL exist under `contracts/events/` with a schema version, and an automated test MUST validate sample Events against it. The portfolio binding operations are delivered in Iteration 2. (PRD FR-30; SPEC FR-MKT-009 partial)

#### Scenario: Valid sample passes
- **GIVEN** a sample tick Event with every required field
- **WHEN** the schema test runs
- **THEN** the sample validates

#### Scenario: Invalid sample fails
- **GIVEN** a sample tick Event missing its schema version or carrying a non-decimal price
- **WHEN** the schema test runs
- **THEN** validation fails
