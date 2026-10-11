# Spec Delta: market-environments

## Purpose

Lets admins and quants define validated Market environments exactly as the POC frontend models them (name, type, universe, Instruments, date window, frequency, status), lets every signed-in User list and read them, and publishes the tick Event schema of the Market environment interface so replayed and simulated markets share one contract. Replay playback and synthetic generation are Iteration 2. Realizes PRD FR-30 (SPEC FR-MKT-007 create, FR-MKT-008, FR-MKT-009 partial, NFR-INT-003) and serves the POC Market Environments and Create Market Environment pages (PRD addendum section G).

## ADDED Requirements

### Requirement: Create a Market environment
The system SHALL let admins and quants create a Market environment with a name, a type (`historical_replay` or `synthetic_market`), a universe name, 1 to 100 existing Instruments, a start date, an end date after the start date, and a frequency (`daily`, `hourly` or `tick`). A new Market environment SHALL start with status `draft`. Analyst and viewer Users MUST get HTTP 403 on create. (PRD FR-30; SPEC FR-MKT-007, FR-MKT-008)

#### Scenario: Quant creates a valid Market environment
- **GIVEN** a quant and three existing Instruments
- **WHEN** they create a `historical_replay` Market environment named "US Technology Basket" from 2020-01-02 to 2020-12-31 with frequency `daily`
- **THEN** it is created with status `draft`

#### Scenario: Invalid membership is refused
- **GIVEN** a request with zero Instruments, more than 100, or an unknown Instrument
- **WHEN** it is submitted
- **THEN** it is refused with HTTP 422

#### Scenario: Analyst or viewer cannot create
- **GIVEN** a signed-in analyst or viewer
- **WHEN** they create a Market environment
- **THEN** they get HTTP 403

### Requirement: List and read Market environments
Any signed-in User SHALL be able to list Market environments and read one, receiving the fields the POC Market Environments page shows: name, type, universe, Instruments, start date, end date, frequency and status. Requests without a token MUST get HTTP 401. (PRD FR-30; addendum section G)

#### Scenario: Viewer lists Market environments
- **GIVEN** two Market environments and a signed-in viewer
- **WHEN** the viewer lists Market environments
- **THEN** both are returned, each with name, type, universe, Instruments, start date, end date, frequency and status

#### Scenario: Read one Market environment
- **GIVEN** an existing Market environment
- **WHEN** a signed-in User reads it by id
- **THEN** it is returned with the same fields

#### Scenario: Unknown Market environment
- **GIVEN** an id that does not exist
- **WHEN** it is read
- **THEN** the response is HTTP 404

#### Scenario: Unauthenticated listing is refused
- **GIVEN** a request with no token
- **WHEN** it lists Market environments
- **THEN** it gets HTTP 401

### Requirement: Market environment window is checked twice
A Market environment whose end date is not after its start date MUST be refused by the API with HTTP 422 and MUST also be refused by the database when inserted directly. (PRD FR-30; SPEC NFR-INT-003)

#### Scenario: Inverted window refused by the API
- **GIVEN** an admin
- **WHEN** they create a Market environment whose end date equals or precedes its start date
- **THEN** the response is HTTP 422

#### Scenario: Inverted window refused by the database
- **GIVEN** the Market environment table
- **WHEN** a row with an end date before its start date is inserted directly
- **THEN** the database refuses it

### Requirement: Only the POC's type, frequency and status values are accepted
A type other than `historical_replay` or `synthetic_market`, a frequency other than `daily`, `hourly` or `tick`, or a status other than `draft`, `ready` or `active` MUST be refused by the API with HTTP 422 and MUST be refused by the database when inserted directly. (PRD FR-30)

#### Scenario: Invalid type or frequency refused by the API
- **GIVEN** an admin
- **WHEN** they create a Market environment with type `live` or frequency `weekly`
- **THEN** the response is HTTP 422

#### Scenario: Invalid values refused by the database
- **GIVEN** the Market environment table
- **WHEN** a row with an unknown type, frequency or status is inserted directly
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
