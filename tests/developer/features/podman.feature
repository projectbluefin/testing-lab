@developer_suite
Feature: Podman desktop and rootless runtime coverage
  Validates Podman Desktop UI plus rootless Podman and Docker user-space integration.
  Regression for dakota#430 (Podman Desktop Flatpak missing dependency).

  @podman_desktop @launch @regression @dakota_430
  Scenario: Podman Desktop Flatpak launches without missing dependency error (dakota#430)
    * Start application "podman_desktop" via "command"
    * Wait until "Podman Desktop" "frame" appears in "podman_desktop"
    * Application "podman_desktop" is running
    * No Flatpak missing-runtime error for "io.podman_desktop.PodmanDesktop"

  @podman_desktop @ui
  Scenario: Podman Desktop main window shows Dashboard
    * Start application "podman_desktop" via "command"
    * Wait until "Podman Desktop" "frame" appears in "podman_desktop"
    * Item "Dashboard" "label" is "showing" in "podman_desktop"

  @podman_desktop @close
  Scenario: Podman Desktop closes cleanly
    * Start application "podman_desktop" via "command"
    * Wait until "Podman Desktop" "frame" appears in "podman_desktop"
    * Close application "podman_desktop" via "shortcut"
    * Application "podman_desktop" is no longer running

  @podman_cli @rootless
  Scenario: podman info reports rootless storage configuration
    * Podman info reports rootless execution

  @podman_cli @quadlet
  Scenario: Podman quadlets use supported directories
    * Podman user quadlet directories are supported

  @podman_cli @systemd
  Scenario: Podman auto-update timer is active for the user
    * Podman auto-update timer is active for the user

  @podman_cli @linger
  Scenario: User lingering is enabled for rootless Podman services
    * User lingering is enabled

  @podman_cli @docker
  Scenario: Homebrew Docker runtime mapping uses a supported user-space socket
    * Homebrew Docker runtime mapping is valid when docker is installed
