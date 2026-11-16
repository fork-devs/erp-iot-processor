@US10
Feature: Book workshop resources from a preventive alert
  A workshop advisor assigns a bay and an active technician when booking preventive maintenance.

  Background:
    Given the alert is pending and belongs to the advisor's workshop
    And the selected branch has a registered bay and an active technician

  Scenario: Book and link a preventive appointment
    When the advisor confirms a free time slot with those resources
    Then the appointment contains the alert's vehicle, diagnostic reason, bay and technician
    And the alert is attended and linked to the appointment
    And a confirmation email is queued when the customer has an email address

  Scenario Outline: Reject an occupied resource
    Given a different vehicle already has an active appointment that overlaps the selected <resource>
    When the advisor attempts the preventive booking
    Then the service returns HTTP 409
    And the alert stays pending

    Examples:
      | resource   |
      | bay        |
      | technician |

  Scenario: Retry a booking after confirmation
    Given the alert already has a linked appointment with the chosen date and resources
    When the advisor sends the same booking request again
    Then the service returns the same appointment ID
    And only one confirmation is queued

  Scenario: Accept the same resource after cancellation
    Given an overlapping appointment was cancelled
    When the advisor books a different vehicle using the released resources
    Then the service accepts the booking
