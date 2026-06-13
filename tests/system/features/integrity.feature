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

  # Regression guard: dakota#841, bluefin-lts boot failure 2026-06-13.
  # File capabilities (security.capability xattrs) are injected by chunka
  # during image export. If the export tool produces a multi-layer image
  # (e.g. buildah commit without --squash), chunka's xattr injection fails
  # silently and the system either refuses to boot or loses container support.
  Scenario: key executables retain composefs file capabilities
    * newuidmap has cap_setuid file capability
    * newgidmap has cap_setgid file capability
    * ping has cap_net_raw file capability
