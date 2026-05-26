@developer_suite @distrobox
Feature: Distrobox container workflows
  Validates that Bluefin's distrobox integration creates, enters, and removes containers correctly.

  @distrobox_create
  Scenario: distrobox create runs without error
    * Run and save command output: "sh -lc 'distrobox rm test-box --force >/dev/null 2>&1 || true; distrobox create --name test-box --image docker.io/library/fedora:latest --yes 2>&1; echo exit:$?'"
    * Last command output contains "exit:0"

  @distrobox_list
  Scenario: created distrobox appears in list
    * Run and save command output: "distrobox list 2>&1"
    * Last command output contains "test-box"

  @distrobox_enter
  Scenario: distrobox enter runs a command inside the container
    * Run and save command output: "sh -lc 'distrobox enter test-box -- sh -lc \"echo inside-box\" 2>&1; echo exit:$?'"
    * Last command output contains "inside-box"
    * Last command output contains "exit:0"

  @distrobox_rm
  Scenario: distrobox rm removes the container
    * Run and save command output: "sh -lc 'distrobox rm test-box --force 2>&1; echo exit:$?'"
    * Last command output contains "exit:0"
