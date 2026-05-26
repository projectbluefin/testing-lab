@system_suite @integrity
Feature: composefs and image integrity
  Validates composefs mounts and image integrity contracts.

  Scenario: composefs is active on the root filesystem
    * composefs is used for the root filesystem mount

  Scenario: prepare-root.conf exists and is readable
    * /etc/prepare-root.conf exists and is readable

  Scenario: /usr is backed by a composefs overlay
    * /usr mount shows composefs or overlay backing

  Scenario: image signature policy file exists
    * /etc/containers/policy.json exists and is readable
