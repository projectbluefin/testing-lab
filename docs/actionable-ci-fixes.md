# Actionable CI Bug Fixes

## argo SA permissions (#153)
Argo SA needs VirtualMachine/VMI permissions in bluefin-test namespace:
```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  namespace: bluefin-test
  name: argo-vm-manager
rules:
- apiGroups: ["kubevirt.io"]
  resources: ["virtualmachines", "virtualmachineinstances"]
  verbs: ["get", "list", "watch", "create", "update", "delete"]
```

## bib-disk-configure: concurrent workflow race (#154)
When concurrent workflows run bib-disk-configure, disk.raw may already be moved to golden.
Add pre-job check: skip configure if golden disk exists.

## volumeMounts for workspace/ssh-key (#156)
Add volumeMounts to run-gnome-tests container for workspace and ssh-key paths.

## openssh-clients missing (#157)
Add `openssh-clients` to the runner pod container image or install it in the Dockerfile.

## dnf install on bootc/Bluefin (#159)
bootc/Bluefin is read-only; replace `sudo dnf install` with rpm-ostree or pre-build the required packages into the golden disk.

## gnome-ponytail-daemon + GDM auto-login (#161)
Add gnome-ponytail-daemon package and configure GDM auto-login in the golden disk image.

## Task Automation (#104, #114, #115, #116, #118)
- #104: Add upstream remote and gh CLI auth to ghost knuckle setup
- #114: Replace SSH shell hops with Argo workflow steps
- #115: Use Argo artifacts/exec instead of nested SSH/SCP
- #116: Migrate from QA_HOST SSH to Argo submit/wait/report
- #118: Remove ghost-host key coupling, use Argo artifact passing
