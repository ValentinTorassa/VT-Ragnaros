#!/usr/bin/env bash
# ragnaros-reset: recover a USB-enumerated deck with a firmware sleep/wake.
#
# Restarting the user daemon is intentional: startup sends the proven HAN/DIS
# recovery sequence before repainting.  USB port/controller removal cannot
# cut power to this deck behind its self-powered hub and can leave it absent.
set -eu

if ! lsusb -d 0200:3001 | grep -q .; then
  echo "ragnaros-reset: deck is absent from USB; reconnect or power-cycle the deck/hub first" >&2
  exit 1
fi

systemctl --user restart ragnarosd.service

# The user service stays active while it waits for a missing/unopenable deck.
# Its control socket only exists after the daemon has actually opened the USB
# device and repainted it, so an active systemd unit alone is not success.
for ((attempt = 0; attempt < 10; attempt++)); do
  if ragnarosctl status >/dev/null 2>&1; then
    echo "ragnaros-reset: deck connected and display recovery requested"
    exit 0
  fi
  sleep 1
done

echo "ragnaros-reset: daemon could not connect to the deck; check journalctl --user -u ragnarosd" >&2
exit 1
