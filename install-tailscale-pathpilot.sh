#!/usr/bin/env bash
# Standalone Tailscale installer for this Ubuntu 14.04 x86_64 PathPilot VM.
# Usage: bash install-tailscale-pathpilot.sh
# Installs standalone binaries and an Upstart job; does not use APT.
set -euo pipefail

if [ "$(uname -m)" != x86_64 ]; then
    echo 'This installer requires an x86_64 VM.' >&2
    exit 1
fi
if ! command -v initctl >/dev/null; then
    echo 'This installer requires Upstart (as used by Ubuntu 14.04).' >&2
    exit 1
fi

sudo -v

if [ ! -x /usr/local/bin/tailscale ] || [ ! -x /usr/local/bin/tailscaled ]; then
    tailscale_workdir=$(mktemp -d)
    trap 'rm -rf "$tailscale_workdir"' EXIT
    tailscale_version=1.104.1
    tailscale_url="https://pkgs.tailscale.com/stable/tailscale_${tailscale_version}_amd64.tgz"
    echo 'Downloading standalone Tailscale binaries...'
    if command -v curl >/dev/null; then
        curl -fL --connect-timeout 15 --max-time 180 "$tailscale_url" -o "$tailscale_workdir/tailscale.tgz"
    else
        wget --timeout=30 --tries=2 -O "$tailscale_workdir/tailscale.tgz" "$tailscale_url"
    fi
    tar xzf "$tailscale_workdir/tailscale.tgz" -C "$tailscale_workdir"
    sudo install -m 755 \
        "$tailscale_workdir/tailscale_${tailscale_version}_amd64/tailscale" \
        "$tailscale_workdir/tailscale_${tailscale_version}_amd64/tailscaled" \
        /usr/local/bin/
fi

sudo install -d -m 700 /var/lib/tailscale
sudo mkdir -p /var/run/tailscale
if ! sudo test -e /etc/init/tailscaled.conf; then
    sudo tee /etc/init/tailscaled.conf >/dev/null <<'EOF'
description "Tailscale networking"
start on runlevel [2345]
stop on runlevel [016]
respawn
respawn limit 5 60
pre-start exec mkdir -p /var/run/tailscale
exec /usr/local/bin/tailscaled --state=/var/lib/tailscale/tailscaled.state --socket=/var/run/tailscale/tailscaled.sock
EOF
fi

sudo modprobe tun
tailscale_service_status=$(sudo service tailscaled status 2>/dev/null || true)
case "$tailscale_service_status" in
    *start/running*) ;;
    *) sudo service tailscaled start ;;
esac

echo 'Open the login URL below to connect the VM to your Tailscale account.'
sudo /usr/local/bin/tailscale up --accept-dns=false
echo 'VM Tailscale address:'
/usr/local/bin/tailscale ip -4
echo 'Connect from another computer signed into Tailscale using: ssh operator@ADDRESS'
