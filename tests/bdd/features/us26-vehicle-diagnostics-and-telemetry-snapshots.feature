@US26 @EP11 @erp-iot-processor
# User Story: US26 - Query automated vehicle diagnostics and telemetry snapshots for technical validation
Feature: Automated Vehicle Diagnostics and Telemetry Snapshots
  As a workshop mechanic
  I want to query real-time automated diagnostics and time-series PID snapshots for a vehicle
  So that I can validate engine anomalies before confirming the final work order diagnosis

  Background:
    Given the "erp-iot-processor" REST API is available

  @US26 @happy-path
  # User Story: US26 - Retrieve automated vehicle diagnostics and telemetry snapshots
  Scenario: Mechanic retrieves real-time diagnostics and paginated telemetry snapshots for a vehicle
    Given an authenticated user with role "TECHNICIAN" in tenant "tenant-lima-01"
    And telemetry snapshots exist in TimescaleDB for vehicle "vehicle-uuid-01"
    When the client sends a "GET" request to "/api/v1/iot/diagnostics/vehicle-uuid-01"
    Then the response status code should be 200
    And the JSON response should contain "vehicle_id" and diagnostic anomaly indicators
    When the client sends a "GET" request to "/api/v1/vehicles/vehicle-uuid-01/telemetry-snapshots?page=0&size=20"
    Then the response status code should be 200
    And the JSON response should be an array of telemetry snapshot items

  @US26 @negative
  # User Story: US26 - Return HTTP 404 when latest device telemetry snapshot does not exist
  Scenario: Querying latest telemetry snapshot for an unrecorded OBD-II device returns HTTP 404
    Given an authenticated user with role "TECHNICIAN" in tenant "tenant-lima-01"
    When the client sends a "GET" request to "/api/v1/obd2-devices/unknown-device-999/telemetry-snapshots/latest"
    Then the response status code should be 404
    And the JSON response should contain an error detail indicating no telemetry snapshot found
