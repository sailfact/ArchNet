#!/usr/bin/env bash
set -euo pipefail

WAN_IFACES=(wan0 wan1)
LAN_IFACES=(lan0 lan1 lan2 lan3)

create_iface() {
    local name="$1"
    if ! ip link show "$name" &>/dev/null; then
        ip link add "$name" type dummy
    fi
    ip link set "$name" up
}

for ifc in "${WAN_IFACES[@]}" "${LAN_IFACES[@]}"; do
    create_iface "$ifc"
done

ip -brief link show
exec "$@"