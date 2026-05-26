@system_suite @bootc
Feature: bootc image lifecycle
  Validates that Bluefin is running as an image-based OS via bootc.

  Scenario: bootc status reports active deployment
    * bootc status reports a valid active deployment

  Scenario: /usr is mounted read-only
    * /usr is mounted read-only

  Scenario: active deployment has a valid image reference
    * active deployment image reference is present and non-empty

  Scenario: staged deployment visibility
    * bootc status can query for staged updates without error
