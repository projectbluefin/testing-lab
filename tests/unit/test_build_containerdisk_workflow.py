from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_build_containerdisk_uses_writable_usrlocal_overlay_for_wrapper_tools():
    workflow = (ROOT / "argo/workflow-templates/build-containerdisk.yaml").read_text(
        encoding="utf-8"
    )

    assert "mkdir -p /var/usrlocal/sbin /var/usrlocal/bin" in workflow
    assert 'export PATH="/var/usrlocal/sbin:/var/usrlocal/bin:${PATH}"' in workflow
    assert '"/usr/local/sbin/${TOOL}"' not in workflow
    assert '"/usr/local/bin/${TOOL}"' not in workflow


def test_build_containerdisk_prepares_podman_tempdir_before_bootable_derivation():
    workflow = (ROOT / "argo/workflow-templates/build-containerdisk.yaml").read_text(
        encoding="utf-8"
    )

    assert "mkdir -p /var/tmp" in workflow
    assert 'export TMPDIR="/var/tmp"' in workflow
    assert (
        "bootc exec-in-host-mount-namespace mkdir -p /var/tmp\\n"
        "export TMPDIR=/var/tmp\\n"
        'exec bootc exec-in-host-mount-namespace %s "$@"\\n'
    ) in workflow


def test_build_containerdisk_bootable_derivation_does_not_require_boot_vmlinuz():
    workflow = (ROOT / "argo/workflow-templates/build-containerdisk.yaml").read_text(
        encoding="utf-8"
    )

    assert (
        'test -e \\"/usr/lib/modules/\\${kver}/vmlinuz\\" || cp /boot/vmlinuz '
        '\\"/usr/lib/modules/\\${kver}/vmlinuz\\"'
    ) in workflow


def test_build_containerdisk_uses_unverified_registry_transport_for_local_bootable_image():
    workflow = (ROOT / "argo/workflow-templates/build-containerdisk.yaml").read_text(
        encoding="utf-8"
    )

    assert 'SOURCE_IMGREF="docker://${BOOTABLE_IMAGE_REMOTE}"' in workflow
    assert 'SOURCE_IMGREF="ostree-unverified-registry:${BOOTABLE_IMAGE_REMOTE}"' not in workflow
    assert 'mkdir -p /etc/containers/registries.conf.d' in workflow
    assert 'location = "192.168.1.102:30500"' in workflow
    assert 'insecure = true' in workflow
