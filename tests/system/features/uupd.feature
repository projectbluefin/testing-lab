@system_suite @uupd
Feature: uupd update orchestration
  Validates uupd policy layer and staged-update signals.

  Scenario: uupd config exists and is valid JSON
    * /etc/uupd/config.json exists and parses as valid JSON

  Scenario: uupd service unit is present
    * uupd.service unit is present on the system

  Scenario: bootc upgrade check runs without error
    * bootc upgrade --check exits cleanly

  Scenario: uupd modules are configured
    * at least one uupd module is enabled in config
