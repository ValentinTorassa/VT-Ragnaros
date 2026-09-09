#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_DIR="$HOME/.config/ragnaros"
SYSTEMD_DIR="$HOME/.config/systemd/user"

ok()   { printf '  \033[32mok\033[0m    %s\n' "$1"; }
bad()  { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; FAILED=1; }
info() { printf '  \033[2m--\033[0m    %s\n' "$1"; }

doctor() {
  local FAILED=0
  echo "ragnaros doctor"

  echo " install:"
  for sub in daemon profiles assets tools; do
    if [[ -e "$CONFIG_DIR/$sub" ]]; then
      ok "$CONFIG_DIR/$sub"
    else
      bad "$CONFIG_DIR/$sub missing (dangling symlink?) - run: $0"
    fi
  done
  if [[ -x "$CONFIG_DIR/daemon/ragnarosd.py" ]]; then
    ok "daemon script executable"
  else
    bad "daemon script not executable: $CONFIG_DIR/daemon/ragnarosd.py"
  fi

  echo " system:"
  if [[ -f /etc/udev/rules.d/99-ragnaros.rules ]]; then
    ok "udev rule installed"
  else
    bad "udev rule missing (/etc/udev/rules.d/99-ragnaros.rules)"
  fi
  if [[ -f /etc/modprobe.d/ragnaros-usbhid.conf ]]; then
    ok "usbhid quirk installed"
  else
    bad "usbhid quirk missing (/etc/modprobe.d/ragnaros-usbhid.conf)"
  fi
  if lsusb 2>/dev/null | grep -q "0200:3001"; then
    ok "Ragnaros device present on USB"
  else
    info "Ragnaros device not on USB (fine if unplugged)"
  fi

  echo " service:"
  if [[ -f "$SYSTEMD_DIR/ragnarosd.service" ]]; then
    ok "user unit installed"
  else
    bad "user unit missing: $SYSTEMD_DIR/ragnarosd.service"
  fi
  if systemctl --user is-enabled ragnarosd.service &>/dev/null; then
    ok "unit enabled"
  else
    bad "unit not enabled"
  fi
  if systemctl --user is-active ragnarosd.service &>/dev/null; then
    ok "unit active"
  else
    info "unit not active - start with: systemctl --user start ragnarosd"
  fi

  echo " python:"
  if python3 -c "import PIL, yaml" &>/dev/null; then
    ok "pillow + pyyaml importable"
  else
    bad "python deps missing - run: pip install --user -r requirements.txt"
  fi

  echo " reset helper:"
  if [[ -x "$HOME/.local/bin/ragnaros-reset" ]]; then
    ok "~/.local/bin/ragnaros-reset"
  else
    bad "~/.local/bin/ragnaros-reset missing - re-run: $0"
  fi

  if (( FAILED )); then
    echo "result: FAIL (re-run ./install.sh to repair symlinks and units)"
    exit 1
  fi
  echo "result: all checks passed"
}

case "${1:-}" in
  doctor|--doctor) doctor; exit 0 ;;
esac

# default: full (re)install
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

# display-recovery helper
chmod +x "$REPO_DIR/tools/reset_deck.sh"
sudo rm -f /etc/sudoers.d/ragnaros-reset
mkdir -p "$HOME/.local/bin"
ln -sfn "$REPO_DIR/tools/reset_deck.sh" "$HOME/.local/bin/ragnaros-reset"

mkdir -p "$SYSTEMD_DIR"
cp "$REPO_DIR/systemd/ragnarosd.service" "$SYSTEMD_DIR/"
cp "$REPO_DIR/systemd/ragnaros-gif-refresh.service" "$REPO_DIR/systemd/ragnaros-gif-refresh.timer" "$SYSTEMD_DIR/"
systemctl --user daemon-reload
systemctl --user enable ragnarosd.service
systemctl --user enable --now ragnaros-gif-refresh.timer

python3 -c "import PIL, yaml" || pip install --user -r "$REPO_DIR/requirements.txt"

echo "Installed. Reboot once to activate the Ragnaros HID quirk, then start with:"
echo "  systemctl --user start ragnarosd"
echo "Health check anytime with: ./install.sh doctor"
