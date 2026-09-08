#!/usr/bin/env bash
# ragnaros-reset: software replug for the Ragnaros deck.
#
# Power-cycles the deck's USB hub port so a hung firmware re-enumerates,
# without touching the cable. The daemon notices the drop and picks the
# device back up on its own (no daemon restart needed).
#
# Needs root; the installer adds a passwordless sudoers rule, so plain
# `ragnaros-reset` from ~/.local/bin just works.
set -u

SELF="$(readlink -f "$0")"
[ "$(id -u)" -eq 0 ] || exec sudo -n "$SELF" "$@"

find_deck() {
    for d in /sys/bus/usb/devices/*/idVendor; do
        dir="$(dirname "$d")"
        if [ "$(cat "$dir/idVendor" 2>/dev/null)" = "0200" ] &&
           [ "$(cat "$dir/idProduct" 2>/dev/null)" = "3001" ]; then
            basename "$dir"
            return 0
        fi
    done
    return 1
}

toggle_port() {  # $1 = device base name like "5-1.4"
    local base="$1" hub port portctl
    hub="${base%.*}"
    port="${base##*.}"
    portctl="/sys/bus/usb/devices/$hub/$hub:1.0/$hub-port$port/disable"
    if [ ! -w "$portctl" ]; then
        return 1
    fi
    echo 1 > "$portctl"
    sleep 2
    echo 0 > "$portctl"
    return 0
}

DECK="$(find_deck)" || true

if [ -n "$DECK" ]; then
    # deck still on the bus: power-cycle its own hub port
    if toggle_port "$DECK"; then
        echo "ragnaros-reset: power-cycled hub port for $DECK"
    else
        echo "ragnaros-reset: no per-port power control for $DECK, removing device" >&2
        echo 1 > "/sys/bus/usb/devices/$DECK/remove" 2>/dev/null
    fi
else
    # deck already gone: power-cycle every external hub port so it re-enumerates
    echo "ragnaros-reset: deck not on bus, cycling all hub ports" >&2
    for h in /sys/bus/usb/devices/*-*:1.0; do
        hubdir="$(dirname "$h")"
        case "$(basename "$hubdir")" in
            *-0) continue ;;  # root hub
        esac
        for p in "$h"-*/disable; do
            [ -w "$p" ] || continue
            echo 1 > "$p" 2>/dev/null
            sleep 1
            echo 0 > "$p" 2>/dev/null
        done
    done
fi

# wait for the deck to come back
for _ in $(seq 1 15); do
    sleep 1
    if [ -n "$(find_deck)" ]; then
        echo "ragnaros-reset: deck is back on the bus"
        exit 0
    fi
done

# last resort: force a bus rescan
udevadm trigger --action=add >/dev/null 2>&1
sleep 2
if [ -n "$(find_deck)" ]; then
    echo "ragnaros-reset: deck is back on the bus"
    exit 0
fi

echo "ragnaros-reset: deck did not re-enumerate; a cable replug is needed" >&2
exit 1
