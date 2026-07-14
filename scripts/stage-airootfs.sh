#!/usr/bin/env bash
# Stage the config engine onto the archiso profile and render the default
# config into airootfs. Content-idempotent: files are only rewritten when
# their content changes, so `make test`'s ISO freshness check stays
# meaningful. Everything written here is gitignored build output.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

fail() {
    printf 'stage-airootfs: %s\n' "$*" >&2
    exit 1
}

command -v python3 >/dev/null || fail 'python3 is required'
python3 -c 'import yaml, jsonschema' 2>/dev/null ||
    fail 'python-yaml and python-jsonschema are required on the build host'

install_if_changed() {
    local src="$1" dst="$2"
    if ! cmp -s -- "$src" "$dst" 2>/dev/null; then
        mkdir -p "$(dirname "$dst")"
        cp -- "$src" "$dst"
    fi
}

# Mirror SRC_DIR into DST_DIR (skipping __pycache__), removing dest files
# that no longer exist in the source.
sync_tree() {
    local src="$1" dst="$2" file rel
    while IFS= read -r -d '' file; do
        rel="${file#"$src"/}"
        install_if_changed "$file" "$dst/$rel"
    done < <(find "$src" -name __pycache__ -prune -o -type f -print0)
    if [[ -d "$dst" ]]; then
        while IFS= read -r -d '' file; do
            rel="${file#"$dst"/}"
            [[ -f "$src/$rel" ]] || rm -- "$file"
        done < <(find "$dst" -type f -print0)
        find "$dst" -type d -empty -delete
    fi
}

# 1. Engine code and schema onto the image.
sync_tree core/fwos_core airootfs/usr/lib/fwos/fwos_core
sync_tree cli/fwos_cli airootfs/usr/lib/fwos/fwos_cli
install_if_changed config/schema.json airootfs/usr/lib/fwos/schema.json

# 2. Default config: the live source of truth and the committed baseline
# the first pre-apply backup derives the managed-file set from.
install_if_changed config/example-config.yaml airootfs/etc/project/config.yaml
install_if_changed config/example-config.yaml \
    airootfs/var/lib/project/committed-config.yaml

# 3. Render the default config on the build host; rendered service files
# are renderer output only and are never committed.
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
PYTHONPATH=core:cli python3 -m fwos_cli \
    --config config/example-config.yaml --schema config/schema.json \
    render --output "$tmp" >/dev/null
while IFS= read -r -d '' file; do
    rel="${file#"$tmp"/}"
    install_if_changed "$file" "airootfs/$rel"
done < <(find "$tmp" -type f -print0)

# Drop rendered networkd units for interfaces that no longer exist.
for unit in airootfs/etc/systemd/network/*.network; do
    [[ -e "$unit" ]] || continue
    [[ -f "$tmp/etc/systemd/network/$(basename "$unit")" ]] || rm -- "$unit"
done

printf 'stage-airootfs: ok\n'
