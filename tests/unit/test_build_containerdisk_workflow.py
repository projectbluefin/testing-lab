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
