#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_DIR="$HOME/.config/ragnaros"

mkdir -p "$CONFIG_DIR"
ln -sfn "$REPO_DIR/daemon" "$CONFIG_DIR/daemon"
ln -sfn "$REPO_DIR/profiles" "$CONFIG_DIR/profiles"
ln -sfn "$REPO_DIR/assets" "$CONFIG_DIR/assets"
ln -sfn "$REPO_DIR/tools" "$CONFIG_DIR/tools"

sudo install -m 0644 "$REPO_DIR/udev/99-ragnaros.rules" /etc/udev/rules.d/99-ragnaros.rules
sudo install -m 0644 "$REPO_DIR/udev/ragnaros-usbhid.conf" /etc/modprobe.d/ragnaros-usbhid.conf
if command -v update-initramfs >/dev/null 2>&1; then
  sudo update-initramfs -u
fi
sudo udevadm control --reload-rules
sudo udevadm trigger

mkdir -p "$HOME/.config/systemd/user"
cp "$REPO_DIR/systemd/ragnarosd.service" "$HOME/.config/systemd/user/"
cp "$REPO_DIR/systemd/ragnaros-gif-refresh.service" "$REPO_DIR/systemd/ragnaros-gif-refresh.timer" "$HOME/.config/systemd/user/"
systemctl --user daemon-reload
systemctl --user enable ragnarosd.service
systemctl --user enable --now ragnaros-gif-refresh.timer

python3 -c "import PIL, yaml" || pip install --user -r "$REPO_DIR/requirements.txt"

echo "Installed. Reboot once to activate the Ragnaros HID quirk, then start with:"
echo "  systemctl --user start ragnarosd"
