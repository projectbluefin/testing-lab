# Copyright 2013-2014 CoreOS, Inc.
# Distributed under the terms of the GNU General Public License v2
#
# Builds the CoreOS (Flatcar) kernel from coreos-sources.
# Ported from coreos-kernel-6.12.ebuild.

EAPI=7

CROS_WORKON_PROJECT="flatcar/coreos-overlay"
CROS_WORKON_LOCALNAME="."
CROS_WORKON_SUBTREE="sys-kernel/coreos-kernel"

inherit cros-workon toolchain-funcs savedconfig

DESCRIPTION="Builds the CoreOS (Flatcar) kernel binary"
HOMEPAGE="https://www.kernel.org"

# Uses sources installed by coreos-sources
RDEPEND="=sys-kernel/coreos-sources-${PV}"
DEPEND="${RDEPEND}
	sys-kernel/linux-headers
	dev-util/pahole"

KEYWORDS="amd64 arm64"
IUSE="custom-cflags"

pkg_setup() {
	# Kernel build requires a cross-compile prefix for cross-arch scenarios
	export CROSS_COMPILE="$(tc-getBUILD_PROG STRIP strip 2>/dev/null || true)"
}

src_configure() {
	# Copy the default Flatcar kernel config from the installed sources
	KV_FULL=$(ls /usr/src/ | grep "${PV}" | head -1)
	KSRC="/usr/src/linux-${KV_FULL}"
	if [[ -z "${KV_FULL}" || ! -d "${KSRC}" ]]; then
		die "coreos-sources-${PV} not found in /usr/src"
	fi
	export KSRC
	cd "${KSRC}"
	make ARCH=x86_64 flatcar_defconfig
	# Merge any Flatcar config fragments
	for frag in "${FILESDIR}"/config.d/*.config; do
		[[ -f "${frag}" ]] && scripts/kconfig/merge_config.sh -m .config "${frag}"
	done
}

src_compile() {
	cd "${KSRC}"
	emake -j$(nproc) ARCH=x86_64 bzImage modules
}

src_install() {
	cd "${KSRC}"
	local kv=$(make -s ARCH=x86_64 kernelrelease)
	dodir /boot
	install -m0644 arch/x86_64/boot/bzImage "${D}/boot/vmlinuz-${kv}"
	install -m0644 System.map "${D}/boot/System.map-${kv}"
	install -m0644 .config "${D}/boot/config-${kv}"
	dosym "vmlinuz-${kv}" /boot/vmlinuz
}
