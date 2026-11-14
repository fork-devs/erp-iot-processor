@US27 @EP11 @erp-iot-processor
# User Story: US27 - Manage preventive DTC alerts and convert them into maintenance appointments
Feature: Preventive DTC Fault Code Alerts
  As a service advisor or workshop administrator
  I want to query preventive DTC and anomaly alerts by vehicle and severity
  So that recurring faults are detected early and converted into preventive service appointments

  Background:
    Given the "erp-iot-processor" REST API is available

  @US27 @happy-path
  # User Story: US27 - Query DTC alerts filtered by severity for a vehicle
  Scenario: Service advisor retrieves CRITICAL DTC alerts for a monitored vehicle
    Given an authenticated user with role "SERVICE_ADVISOR" in tenant "tenant-lima-01"
    And MongoDB contains recorded DTC alerts for vehicle "vehicle-uuid-01"
    When the client sends a "GET" request to "/api/v1/vehicles/vehicle-uuid-01/dtc-alerts?severity=CRITICAL&page=0&size=20"
    Then the response status code should be 200
    And each item in the JSON array should contain "id", "vehicle_id", "dtc_code", and "severity" equal to "CRITICAL"

  @US27 @negative
  # User Story: US27 - Reject unauthenticated access to vehicle DTC alerts
  Scenario: Querying DTC alerts without a valid JWT token returns HTTP 401 Unauthorized
    When the client sends an unauthenticated "GET" request to "/api/v1/vehicles/vehicle-uuid-01/dtc-alerts"
    Then the response status code should be 401
    And the JSON response should indicate missing or invalid authentication credentials
