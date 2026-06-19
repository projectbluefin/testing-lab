@developer_suite
Feature: ujust devmode toggle
  Validates that `ujust devmode` behaves correctly and does not prompt
  to enable developer mode when it is already active.
  Regression for bluefin#4209.

  @devmode @regression @bluefin_4209
  Scenario: ujust devmode does not prompt to enable when already enabled (bluefin#4209)
    * ujust is available on PATH
    * Run ujust devmode and capture output
    * ujust devmode output does not prompt to re-enable
