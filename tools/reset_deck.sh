#!/usr/bin/env bash
# ragnaros-reset: recover a responsive USB deck with a firmware sleep/wake.
#
# Restarting the user daemon is intentional: startup sends the proven HAN/DIS
# recovery sequence before repainting.  USB port/controller removal cannot
# cut power to this deck behind its self-powered hub and can leave it absent.
set -eu

systemctl --user restart ragnarosd.service
echo "ragnaros-reset: display recovery requested"
