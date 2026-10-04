#!/usr/bin/env bash
# ragnaros-reset: recover a USB-enumerated deck with a firmware sleep/wake.
set -eu

if ! lsusb -d 0200:3001 | grep -q .; then
  echo "ragnaros-reset: deck is absent from USB; reconnect or power-cycle the deck/hub first" >&2
  exit 1
fi

# Start the daemon if its control socket is unavailable. A running service can
# still be waiting for a device, so wait for the socket rather than its unit.
if ! ragnarosctl status >/dev/null 2>&1; then
  systemctl --user restart ragnarosd.service
fi

for ((attempt = 0; attempt < 10; attempt++)); do
  if ragnarosctl status >/dev/null 2>&1; then
    if ragnarosctl reset-display; then
      echo "ragnaros-reset: display reset and profile repainted"
      exit 0
    fi
    echo "ragnaros-reset: display reset failed; check journalctl --user -u ragnarosd" >&2
    exit 1
  fi
  sleep 1
done

echo "ragnaros-reset: daemon could not connect to the deck; check journalctl --user -u ragnarosd" >&2
exit 1
