@flatcar_suite
Feature: Flatcar boot smoke tests
  Validates Flatcar Container Linux boots cleanly and core services are running.
  Tests run from the Argo runner pod via SSH (FLATCAR_VM_IP env var).
  No GNOME desktop — no qecore or AT-SPI.

  Background:
    * Flatcar VM is reachable over SSH

  @flatcar @boot
  Scenario: systemd reaches multi-user.target
    * Run SSH command: "systemctl is-active multi-user.target"
    * SSH command output "is" "active"

  @flatcar @boot
  Scenario: No systemd units are in failed state
    * Run SSH command: "systemctl is-system-running"
    * SSH command output is not "degraded" and not "failed"

  @flatcar @containerd
  Scenario: containerd service is active
    * Run SSH command: "systemctl is-active containerd"
    * SSH command output "is" "active"

  @flatcar @containerd
  Scenario: containerd socket is reachable
    * Run SSH command: "sudo ctr version"
    * SSH command return code is "0"

  @flatcar @network
  Scenario: Network interface has an IP address
    * Run SSH command: "ip -4 addr show eth0 | grep -c inet"
    * SSH command return code is "0"

  @flatcar @network
  Scenario: DNS resolution works
    * Run SSH command: "getent hosts ghcr.io"
    * SSH command return code is "0"

  @flatcar @version
  Scenario: Flatcar version file is present
    * Run SSH command: "cat /etc/os-release | grep -c FLATCAR"
    * SSH command return code is "0"
