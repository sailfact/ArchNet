#!/usr/bin/env bash
# License: GPL-3.0-or-later

iso_name="mycustomlinux"
iso_label="MY_CUSTOM_ARCH_$(date +%Y%m)"
iso_publisher="YourName <https://github.com/yourusername>"
iso_application="Custom Arch Linux Live/Installation CD"
iso_version="$(date +%Y.%m.%d)"
install_dir="arch"
buildmodes=('iso')
bootmodes=('bios.syslinux.mbr' 'bios.syslinux.eltorito' 'uefi-ia32.grub.esp' 'uefi-x64.grub.esp' 'uefi-ia32.grub.eltorito' 'uefi-x64.grub.eltorito')

# File permissions for the live ISO environment
file_permissions=(
  ["/etc/shadow"]="0:0:400"
)