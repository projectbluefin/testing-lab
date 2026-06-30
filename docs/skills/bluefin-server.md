---
name: bluefin-server
description: >
  Build, verify, and maintain the FSDK-based bluefin-server bootc image, including
  compilation elements, offline Cargo setups, and containerDisk conversion.
  Use when modifying server-image configs, troubleshooting sandboxed BuildStream builds,
  or resolving bootc target installation requirements.
metadata:
  context7-sources:
    - /bootc-dev/bootc
    - /ostreedev/ostree
    - /freedesktop/freedesktop-sdk
---

# bluefin-server Building and Maintenance — testing-lab Skill

## When to Use

- Building or debugging the FSDK-based `bluefin-server-bootc` image on the cluster.
- Troubleshooting sandboxed, networkless Cargo compiles inside FSDK elements.
- Handling `bootc install to-disk` requirements and resolving `prepare-root.conf` or filesystem failures.
- Converting OCI images to KubeVirt `containerDisk` volumes for server testing.

## When NOT to Use

- Managing standard downstream Fedora/CentOS Bluefin images → `ci-tooling.md`.
- Deploying virtual machine instances for GNOME Shell UI testing → `kubevirt-vms.md`.
- Managing Flatcar kernel life-cycles or Nebraska updates → `flatcar-node-onboarding.md`.

---

## Core Process

### 1. Maintain Sandboxed Offline Cargo Builds
BuildStream manual/script sandboxes have **no internet access**. All Rust/Cargo dependencies must be fully offline-vendored:

1. Package dependencies using `cargo vendor` and compress with `zstd` into a `-vendor.tar.zstd` archive.
2. In `bootc.bst`, declare both the gzip source tree and the raw `.zstd` vendor archive. BuildStream's tar plugin automatically extracts `.tar.gz` but leaves `.tar.zstd` raw.
3. Extract the `.zstd` archive in the build script using host tools:
   ```bash
   tar --zstd -xf bootc-vendor.tar.zstd
   ```
4. Generate a local `.cargo/config.toml` redirecting `crates-io` and any git dependencies (e.g., `composefs-ctl`) to local directories:
   ```toml
   [source.crates-io]
   replace-with = "vendored-sources"

   [source.vendored-sources]
   directory = "vendor"

   [patch."https://github.com/composefs/composefs-rs"]
   composefs-ctl = { path = "vendor/composefs-ctl" }
   ```
5. Remove test subdirectories (like `crates/tests-integration`) from the workspace to bypass missing network and system dependencies, and compile with `cargo build --release --offline -p bootc`.

### 2. Ensure Bootc Target Readiness
`bootc install to-disk` (used in containerDisk conversion) asserts on the presence of `/usr/lib/ostree/prepare-root.conf` (or `/etc/ostree/prepare-root.conf`) inside the OCI image. If it is missing, compilation will crash with `Failed to find ostree/prepare-root.conf`.

Always include `bluefin-server/prepare-root-config.bst` in `os-stack.bst` to write a basic config:
```ini
[sysroot]
readonly=false
```

### 3. Convert and Run as KubeVirt containerDisk
The built image must be converted to a `containerDisk` using the `build-containerdisk` workflow template:

1. Always specify `-p filesystem=ext4` (or `xfs`/`btrfs`) when running the conversion workflow for custom images. Without it, the automatic detection loop falls back to empty args and crashes with `No root filesystem specified`.
2. Keep the allocation size reasonable (`-p disk-size=10G`) to secure rapid build-times on the cluster NVMe.

---

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "I can build Cargo projects online by enabling network access in the element." | BuildStream policy prohibits network access during build phase to enforce complete reproducibility. All sources must be pre-fetched during fetch phase. |
| "prepare-root.conf is only needed at runtime, so we can omit it from the OCI build." | `bootc install to-disk` performs static image validation before writing blocks and refuses to install images lacking this file. |
| "We should use a default 25G disk-size for all conversions." | For 2GB server images, a 10G disk-size is faster to allocate, compress, and move, while leaving plenty of runtime space for container operations. |

## Red Flags

- `bootc install` failing with `Failed to find ostree/prepare-root.conf` → Missing the `prepare-root-config` dependency in `os-stack.bst`.
- `cargo` compiler failing with network errors inside BuildStream → Forgot to configure `.cargo/config.toml` or missing `--offline` flag.
- `build-containerdisk` failing with `No root filesystem specified` → Forgot to pass `-p filesystem=ext4` to the workflow submission.

## Verification

- [ ] `skopeo inspect --tls-verify=false docker://192.168.1.102:30500/bluefin-server-bootc:latest` returns a valid OCI manifest.
- [ ] `podman run --rm --tls-verify=false --entrypoint=ls 192.168.1.102:30500/bluefin-server-bootc:latest /usr/lib/ostree/prepare-root.conf` completes successfully.
- [ ] `build-containerdisk` workflow completes and pushes to `bluefin-containerdisk` with the target tag.
