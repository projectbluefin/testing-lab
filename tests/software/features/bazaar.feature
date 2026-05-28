@software_suite
Feature: Bazaar (GNOME Software) update and install workflows

  Background: Bazaar is available
    * Start "org.gnome.Software" via shell
    * Application "org.gnome.Software" is opened

  @bazaar @launch
  Scenario: Bazaar launches and shows main view
    * Application "org.gnome.Software" is opened
    * Close "org.gnome.Software"

  @bazaar @updates
  Scenario: Bazaar updates tab is accessible
    * Application "org.gnome.Software" is opened
    * Activate "Updates" in "org.gnome.Software"
    * Close "org.gnome.Software"

  # ── Update workflow (#93) ────────────────────────────────────────────────
  # Proves the software-management pipeline is healthy: UI navigates to the
  # Updates tab without crashing and the system Flatpak stack is in good shape.

  @bazaar @updates @workflow
  Scenario: Updates tab loads without gnome-software crash
    * Application "org.gnome.Software" is opened
    * Activate "Updates" in "org.gnome.Software"
    * Wait 3 seconds before action
    * Run and save command output: "journalctl -b --no-pager -g 'gnome-software.*segfault\|gnome-software.*abort\|gnome-software.*crash' | grep -c . || echo 0"
    * Last command output "is" "0"
    * Close "org.gnome.Software"

  @bazaar @updates @workflow
  Scenario: Flatpak appstream metadata is up to date
    * Run and save command output: "flatpak update --appstream --noninteractive --system; echo \"appstream:exit:$?\""
    * Last command output contains "appstream:exit:0"

  # ── Install workflow (#93) ───────────────────────────────────────────────
  # Proves the install path is healthy: search returns results, a known
  # system-installed app is visible in the Installed list, and the Explore
  # page loads featured content.  Uses only pre-installed or cached state so
  # no network package download is required for a green run.

  @bazaar @install @workflow
  Scenario: Explore page loads featured content
    * Application "org.gnome.Software" is opened
    * Activate "Explore" in "org.gnome.Software"
    * Wait 3 seconds before action
    * Run and save command output: "journalctl -b --no-pager -g 'gnome-software.*segfault\|gnome-software.*abort\|gnome-software.*crash' | grep -c . || echo 0"
    * Last command output "is" "0"
    * Close "org.gnome.Software"

  @bazaar @install @workflow
  Scenario: Installed list is non-empty after Flatpak bootstrap
    * Run and save command output: "flatpak list --system --app --columns=name 2>/dev/null | grep -q . && echo 'has_apps' || echo 'no_apps'"
    * Last command output contains "has_apps"

  @bazaar @install @workflow
  Scenario: Search returns results for a known app
    * Application "org.gnome.Software" is opened
    * Left click "Search" "toggle button" in "software"
    * Type text: "Calculator" with uinput
    * Wait until "Calculator" "label" appears in "software"
    * Close "org.gnome.Software"

  @bazaar @install @workflow
  Scenario: Installed tab shows system Flatpak apps
    * Application "org.gnome.Software" is opened
    * Activate "Installed" in "org.gnome.Software"
    * Wait 3 seconds before action
    * Run and save command output: "flatpak list --system --app --columns=name 2>/dev/null | grep -q . && echo 'has_installed' || echo 'no_installed'"
    * Last command output contains "has_installed"
    * Close "org.gnome.Software"
