@smoke_suite
Feature: GNOME Shell smoke tests
  Validates GNOME Shell is functional on a fresh Bluefin boot.
  All steps use qecore common_steps unless noted as custom.
  Runs on every PR against latest and lts variants.

  # ── Top bar ──────────────────────────────────────────────────────────────

  @top_bar
  Scenario: GNOME Shell process is running and accessible via AT-SPI
    * GNOME Shell is accessible via AT-SPI
    * Dump panel children to log
    * Dump gnome-shell AT-SPI tree to results

  @top_bar
  Scenario: Panel is present in AT-SPI tree
    * GNOME Shell is accessible via AT-SPI
    * Panel is present in AT-SPI tree

  @top_bar
  Scenario: Activities toggle button is visible in panel
    * GNOME Shell is accessible via AT-SPI
    * Item "Activities" "toggle button" is "showing" in "gnome-shell"

  @top_bar
  Scenario: Clock toggle button is visible in panel
    * GNOME Shell is accessible via AT-SPI
    * Clock toggle is visible in top bar

  @top_bar
  Scenario: System menu toggle button is visible in panel
    * GNOME Shell is accessible via AT-SPI
    * System menu toggle is visible in top bar

  # ── Activities overview ───────────────────────────────────────────────────

  @activities
  Scenario: Super key opens Activities overview
    * Key combo: "<super>" with uinput
    * Overview is open
    * Press key: "Escape" with uinput
    * Overview is closed

  @activities
  Scenario: Typing in overview populates search bar
    * Key combo: "<super>" with uinput
    * Overview is open
    * Type text: "Files" with uinput
    * Overview search bar contains "Files"
    * Press key: "Escape" with uinput

  @activities
  Scenario: Escape closes Activities overview
    * Key combo: "<super>" with uinput
    * Overview is open
    * Press key: "Escape" with uinput
    * Overview is closed

  # ── Quick Settings ────────────────────────────────────────────────────────

  @quick_settings
  Scenario: Clicking System menu opens Quick Settings
    * System menu toggle is visible in top bar
    * Left click "System" "toggle button" in "gnome-shell"
    * Item "Quick Settings" "frame" is "showing" in "gnome-shell"

  @quick_settings
  Scenario: Escape closes Quick Settings
    * System menu toggle is visible in top bar
    * Left click "System" "toggle button" in "gnome-shell"
    * Item "Quick Settings" "frame" is "showing" in "gnome-shell"
    * Press key: "Escape" with uinput
    * Item "Quick Settings" "frame" is not "showing" in "gnome-shell"

  # ── Calendar popup ────────────────────────────────────────────────────────

  @calendar
  Scenario: Clicking clock opens calendar popup
    * Clock toggle is visible in top bar
    * Left click "clock" "toggle button" in "gnome-shell"
    * Item "calendar" "calendar" is "showing" in "gnome-shell"

  @calendar
  Scenario: Escape closes calendar popup
    * Clock toggle is visible in top bar
    * Left click "clock" "toggle button" in "gnome-shell"
    * Item "calendar" "calendar" is "showing" in "gnome-shell"
    * Press key: "Escape" with uinput
    * Item "calendar" "calendar" is not "showing" in "gnome-shell"

  # ── Regressions ───────────────────────────────────────────────────────────

  @regression @bluefin_4612
  Scenario: GNOME Shell extensions do not crash shell on load (bluefin#4612)
    * GNOME Shell is accessible via AT-SPI
    * Run and save command output: "sh -c 'journalctl --no-pager -b -p err..emerg --lines=50 2>/dev/null | grep -c gnome-shell; true'"
    * Last command output stripped "is" "0"

  @regression @bluefin_4642
  Scenario: No gnome-shell coredump after session start (bluefin#4642)
    * Run and save command output: "sh -c 'coredumpctl list gnome-shell --no-pager --lines=10 2>/dev/null | grep -c gnome-shell; true'"
    * Last command output stripped "is" "0"
