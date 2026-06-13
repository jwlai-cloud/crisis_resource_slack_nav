#!/usr/bin/env bash
# GCE startup-script — runs on the VM host at every boot. Best-effort swap as OOM
# insurance for the 1 GB e2-micro (the agent is I/O-bound and idles ~400 MB, so this
# is belt-and-braces). The container itself is managed by create-with-container
# (--container-restart-policy=always); this script does NOT manage the container.
#
# NOTE: Container-Optimized OS (the default for create-with-container) restricts
# swap, so swapon may be a no-op there — it is harmless (|| true). On a Debian/Ubuntu
# VM it takes effect. If the agent ever OOMs on e2-micro, switch to e2-small (2 GB,
# ~$13/mo) — see deploy/README.md.
set -uo pipefail

SWAPFILE=/var/swapfile
if [ ! -f "$SWAPFILE" ]; then
  fallocate -l 2G "$SWAPFILE" 2>/dev/null || dd if=/dev/zero of="$SWAPFILE" bs=1M count=2048 2>/dev/null || true
  chmod 600 "$SWAPFILE" 2>/dev/null || true
  mkswap "$SWAPFILE" 2>/dev/null || true
fi
swapon "$SWAPFILE" 2>/dev/null || true
exit 0
