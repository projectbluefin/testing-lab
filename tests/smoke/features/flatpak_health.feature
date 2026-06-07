@smoke_suite
Feature: Flatpak runtime health
  Validates the Flatpak substrate is healthy at the system level.
  Regression for bluefin#4403 (flatpak repair should succeed after upgrades).

  @flatpak @health @regression @bluefin_4403
  Scenario: flatpak repair --user exits cleanly (bluefin#4403)
    * Run and save command output: "flatpak repair --user 2>&1; echo exit:$?"
    * Last command output stripped contains "exit:0"

  @flatpak @health
  Scenario: flatpak repair --system exits cleanly
    * Run and save command output: "flatpak repair --system 2>&1; echo exit:$?"
    * Last command output stripped contains "exit:0"
