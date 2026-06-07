@system_suite @filesystem
Feature: filesystem configuration
  Validates filesystem-level expectations for Bluefin installations.

  @btrfs @regression @bluefin_4655
  Scenario: btrfs root has compression enabled (bluefin#4655)
    * root filesystem compression is enabled if btrfs
