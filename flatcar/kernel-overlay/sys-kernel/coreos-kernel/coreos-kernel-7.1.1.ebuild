# Copyright 2013-2014 CoreOS, Inc.
# Distributed under the terms of the GNU General Public License v2
#
# Builds the CoreOS (Flatcar) kernel from coreos-sources.
# Ported from coreos-kernel-6.12.ebuild.

EAPI=7

inherit toolchain-funcs

DESCRIPTION="Builds the CoreOS (Flatcar) kernel binary"
HOMEPAGE="https://www.kernel.org"
LICENSE="GPL-2"
SLOT="0"
S="${WORKDIR}"

# Uses sources installed by coreos-sources
RDEPEND="=sys-kernel/coreos-sources-${PV}"
DEPEND="${RDEPEND}
	sys-kernel/linux-headers"

KEYWORDS="amd64 arm64"
IUSE="custom-cflags"
RESTRICT="userpriv"

src_configure() {
	# Copy the default Flatcar kernel config from the installed sources
	KV_FULL=$(ls "${SYSROOT}/usr/src/" | grep "${PV}" | head -1)
	KSRC="${SYSROOT}/usr/src/${KV_FULL}"
	if [[ -z "${KV_FULL}" || ! -d "${KSRC}" ]]; then
		die "coreos-sources-${PV} not found in ${SYSROOT}/usr/src"
	fi
	export KSRC
	addwrite "${KSRC}"
	cd "${KSRC}"
	cp -v "${FILESDIR}/../../coreos-modules/files/amd64_defconfig-7.1" .config
	make ARCH=x86_64 olddefconfig
	# Merge any Flatcar config fragments
	for frag in "${FILESDIR}"/config.d/*.config; do
		[[ -f "${frag}" ]] && scripts/kconfig/merge_config.sh -m .config "${frag}"
	done
}

src_compile() {
	addwrite "${KSRC}"
	cd "${KSRC}"
	emake -j$(nproc) ARCH=x86_64 bzImage modules
}

src_install() {
	addwrite "${KSRC}"
	cd "${KSRC}"
	local kv=$(make -s ARCH=x86_64 kernelrelease)
	# coreos-postinst expects the kernel in /usr/boot (merged-usr layout)
	# bzImage can be a symlink in some build setups; install the real file.
	install -D -m0644 "$(readlink -f arch/x86_64/boot/bzImage)" \
		"${D}/usr/boot/vmlinuz-${kv}" || die
	dosym "vmlinuz-${kv}" /usr/boot/vmlinuz
	insinto "/usr/lib/modules/${kv}/build"
	doins System.map .config
}
