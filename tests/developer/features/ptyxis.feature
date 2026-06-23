@developer_suite
Feature: Ptyxis terminal smoke tests
  Validates Ptyxis terminal launches, accepts input, and runs brew/podman.
  Ptyxis AT-SPI name confirmed: root.application("ptyxis").
  Regression coverage for bluefin#4620 (Vulkan spam in terminal).

  Background:
    * Start application "ptyxis" via "command"
    * Make sure window is focused for wayland testing

  @ptyxis @launch
  Scenario: Ptyxis launches and window is accessible
    * Application "ptyxis" is running
    * Item "Ptyxis" "frame" is "showing" in "ptyxis"

  @ptyxis @input
  Scenario: Terminal accepts keyboard input
    * Type text: "echo bluefin-test" with uinput
    * Press key: "Return" with uinput
    * Terminal output in ptyxis contains "bluefin-test"

  @ptyxis @brew
  Scenario: brew is on PATH and returns version string
    * Type text: "brew --version" with uinput
    * Press key: "Return" with uinput
    * Terminal output in ptyxis contains "Homebrew"

  @ptyxis @podman
  Scenario: podman is available in terminal
    * Type text: "podman --version" with uinput
    * Press key: "Return" with uinput
    * Terminal output in ptyxis contains "podman version"

  @ptyxis @regression @bluefin_4620
  Scenario: No Vulkan validation spam on terminal open (bluefin#4620)
    * Run and save command output: "journalctl -b --no-pager --since=\"${TEST_JOURNAL_SINCE:-1 minute ago}\" -g 'VUID-' | grep -c 'VUID-' || true"
    * Last command output "is" "0"

  @ptyxis @new_tab @wip
  Scenario: New tab opens via keyboard shortcut
    * Key combo: "<Shift><Ctrl><T>" with uinput
    * Ptyxis has "2" tabs

  @ptyxis @close
  Scenario: Ptyxis closes via shortcut
    * Close application "ptyxis" via "shortcut"
    * Application "ptyxis" is no longer running
