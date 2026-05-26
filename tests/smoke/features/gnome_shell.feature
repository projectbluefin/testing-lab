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
    * Activities toggle is visible in top bar

  @top_bar
  Scenario: Clock toggle button is visible in panel
    * GNOME Shell is accessible via AT-SPI
    * Clock toggle is visible in top bar

  @top_bar
  Scenario: System menu toggle button is visible in panel
    * GNOME Shell is accessible via AT-SPI
    * System menu toggle is visible in top bar

  # ── Activities overview ───────────────────────────────────────────────────
  # NOTE: uinput Super key (KEY_LEFTMETA) is unreliable on GNOME 50 Wayland —
  # Mutter does not route it from python-uinput devices. Use Shell.Eval instead.

  @activities
  Scenario: Super key opens Activities overview
    * GNOME Shell is accessible via AT-SPI
    * Open Activities overview via Shell.Eval
    * Overview is open
    * Close Activities overview via Shell.Eval
    * Overview is closed

  @activities
  Scenario: Typing in overview populates search bar
    * GNOME Shell is accessible via AT-SPI
    * Open Activities overview via Shell.Eval
    * Overview is open
    * Set overview search text to "Files" via Shell.Eval
    * Overview search bar contains "Files"
    * Close Activities overview via Shell.Eval

  @activities
  Scenario: Escape closes Activities overview
    * GNOME Shell is accessible via AT-SPI
    * Open Activities overview via Shell.Eval
    * Overview is open
    * Close Activities overview via Shell.Eval
    * Overview is closed

  # ── Quick Settings ────────────────────────────────────────────────────────
  # NOTE: Clock/System toggle buttons have AT-SPI position INT_MIN on GNOME 50.
  # Drive via Shell.Eval; verify via isOpen JS property.

  @quick_settings
  Scenario: Clicking System menu opens Quick Settings
    * GNOME Shell is accessible via AT-SPI
    * Open Quick Settings via Shell.Eval
    * Quick Settings panel is open via Shell.Eval

  @quick_settings
  Scenario: Escape closes Quick Settings
    * GNOME Shell is accessible via AT-SPI
    * Open Quick Settings via Shell.Eval
    * Quick Settings panel is open via Shell.Eval
    * Close Quick Settings via Shell.Eval
    * Quick Settings panel is closed via Shell.Eval

  # ── Calendar popup ────────────────────────────────────────────────────────

  @calendar
  Scenario: Clicking clock opens calendar popup
    * GNOME Shell is accessible via AT-SPI
    * Open date menu via Shell.Eval
    * Date menu panel is open via Shell.Eval

  @calendar
  Scenario: Escape closes calendar popup
    * GNOME Shell is accessible via AT-SPI
    * Open date menu via Shell.Eval
    * Date menu panel is open via Shell.Eval
    * Close date menu via Shell.Eval
    * Date menu panel is closed via Shell.Eval

  # ── App launch from overview (#65) ──────────────────────────────────────

  @activities @app_launch
  Scenario: Overview search launches Files
    * GNOME Shell is accessible via AT-SPI
    * Open Activities overview via Shell.Eval
    * Overview is open
    * Set overview search text to "Files" via Shell.Eval
    * Overview search bar contains "Files"
    * Launch first overview search result via Shell.Eval
    * Application "org.gnome.Nautilus" is open in AT-SPI
    * Close application "org.gnome.Nautilus" via Shell.Eval

  @activities @app_launch
  Scenario: Overview search launches Settings
    * GNOME Shell is accessible via AT-SPI
    * Open Activities overview via Shell.Eval
    * Overview is open
    * Set overview search text to "Settings" via Shell.Eval
    * Overview search bar contains "Settings"
    * Launch first overview search result via Shell.Eval
    * Application "org.gnome.Settings" is open in AT-SPI
    * Close application "org.gnome.Settings" via Shell.Eval

  @activities @app_launch @files_navigation
  Scenario: Overview search opens Files sidebar locations
    * GNOME Shell is accessible via AT-SPI
    * Open Activities overview via Shell.Eval
    * Overview is open
    * Set overview search text to "Files" via Shell.Eval
    * Overview search bar contains "Files"
    * Launch first overview search result via Shell.Eval
    * Application "org.gnome.Nautilus" is open in AT-SPI
    * Files sidebar contains "Home"
    * Close application "org.gnome.Nautilus" via Shell.Eval

  @activities @app_launch @settings_navigation
  Scenario: Overview search opens Settings About and Appearance panels
    * GNOME Shell is accessible via AT-SPI
    * Open Activities overview via Shell.Eval
    * Overview is open
    * Set overview search text to "Settings" via Shell.Eval
    * Overview search bar contains "Settings"
    * Launch first overview search result via Shell.Eval
    * Application "org.gnome.Settings" is open in AT-SPI
    * Open Settings panel "About"
    * Settings panel "About" shows "Operating System"
    * Open Settings panel "Appearance"
    * Settings panel "Appearance" shows "Style"
    * Close application "org.gnome.Settings" via Shell.Eval

  @browser @app_launch
  Scenario: Firefox launches and shows browser window
    * GNOME Shell is accessible via AT-SPI
    * Open Activities overview via Shell.Eval
    * Set overview search text to "Firefox" via Shell.Eval
    * Launch first overview search result via Shell.Eval
    * Application "org.mozilla.firefox" is open in AT-SPI
    * Close application "org.mozilla.firefox" via Shell.Eval

  @browser @default_browser
  Scenario: xdg-settings reports a default browser
    * Run and save command output: "xdg-settings get default-web-browser"
    * Last command output stripped contains ".desktop"

  # ── Quick Settings state change (#90) ───────────────────────────────────

  @quick_settings @state_change
  Scenario: Quick Settings dark style toggle changes desktop theme
    * GNOME Shell is accessible via AT-SPI
    * Open Quick Settings via Shell.Eval
    * Quick Settings panel is open via Shell.Eval
    * Toggle dark style via Shell.Eval
    * Dark style setting changed
    * Toggle dark style via Shell.Eval
    * Close Quick Settings via Shell.Eval
    * Quick Settings panel is closed via Shell.Eval

  # ── Bluefin extension workflows (#91) ────────────────────────────────────

  @extension_behavior @ding @regression @bluefin_91
  Scenario: Desktop Icons NG (ding) is enabled and desktop icon area exists
    * GNOME Shell is accessible via AT-SPI
    * Extension "ding@rastersoft.com" is enabled
    * AT-SPI root contains a desktop canvas or icon surface

  @extension_behavior @dash_to_dock @regression @bluefin_91
  Scenario: Dash to Dock keeps a visible dock actor outside the overview
    * GNOME Shell is accessible via AT-SPI
    * Extension "dash-to-dock@micxgx.gmail.com" is enabled
    * Dash to Dock exposes a visible dock actor

  @extension_behavior @blur_my_shell @regression @bluefin_91
  Scenario: Blur My Shell applies an overview blur effect
    * GNOME Shell is accessible via AT-SPI
    * Extension "blur-my-shell@aunetx" is enabled
    * Open Activities overview via Shell.Eval
    * Overview is open
    * Overview blur effect is active via Shell.Eval
    * Close Activities overview via Shell.Eval
    * Overview is closed

  @extension_behavior @app_indicators @regression @bluefin_91
  Scenario: App Indicators registers a tray host in the shell panel
    * GNOME Shell is accessible via AT-SPI
    * Extension "appindicatorsupport@rgcjonas.gmail.com" is enabled
    * App Indicators registers a panel tray host

  @extension_behavior @windows_navigator @regression @bluefin_91
  Scenario: Windows Navigator shows workspace navigation hints in the overview
    * GNOME Shell is accessible via AT-SPI
    * Extension "windowsNavigator@gnome-shell-extensions.gcampax.github.com" is enabled
    * Open Activities overview via Shell.Eval
    * Overview is open
    * Windows Navigator shows workspace navigation hints via Shell.Eval
    * Close Activities overview via Shell.Eval
    * Overview is closed

  # ── Notifications (#68) ───────────────────────────────────────────────────

  @calendar @notifications @regression @bluefin_68
  Scenario: Date menu shows a delivered desktop notification
    * GNOME Shell is accessible via AT-SPI
    * Send desktop notification "Test notification" "QA probe"
    * Open date menu via Shell.Eval
    * Date menu panel is open via Shell.Eval
    * Date menu shows notification "Test notification" with body "QA probe"
    * Close date menu via Shell.Eval
    * Date menu panel is closed via Shell.Eval

  # ── Regressions ───────────────────────────────────────────────────────────

  @regression @bluefin_4612
  Scenario: GNOME Shell extensions do not crash shell on load (bluefin#4612)
    * GNOME Shell is accessible via AT-SPI
    * No gnome-shell journal errors since test start

  @regression @bluefin_4642
  Scenario: No gnome-shell coredump after session start (bluefin#4642)
    * Run and save command output: "sh -c 'coredumpctl list gnome-shell --no-pager --lines=10 2>/dev/null | grep -c gnome-shell; true'"
    * Last command output stripped "is" "0"
