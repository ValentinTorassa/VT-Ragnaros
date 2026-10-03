"""ragnaros: one-time setup for a pip/pipx install.

  ragnaros install-system [--print]     udev rules + usbhid quirk (sudo, one reboot)
  ragnaros install-service [--print]    systemd user unit for ragnarosd
  ragnaros paths                        where profiles, assets and GIF themes live

The .deb and AUR packages already install the udev rules, the quirk and
the user units; there you only run `systemctl --user enable --now ragnarosd`.
"""
import argparse
import os
import platform
import shlex
import shutil
import subprocess
import sys

from . import __version__, control, paths, theme

UDEV_RULES = "70-ragnaros.rules"
QUIRK_CONF = "ragnaros-usbhid.conf"
LEGACY_RULES = "/etc/udev/rules.d/99-ragnaros.rules"  # what install.sh used to write
QUIRK_PARAM = "usbhid.quirks=0x0200:0x3001:0x00000004"
PACKAGED_UNIT_EXEC = {"ragnarosd": "/usr/bin/ragnarosd",
                      "ragnaros-fetch-gifs": "/usr/bin/ragnaros-fetch-gifs"}


# -- install-system -------------------------------------------------------------
def system_files():
    udev = paths.bundled("udev")
    return [(os.path.join(udev, UDEV_RULES), f"/etc/udev/rules.d/{UDEV_RULES}"),
            (os.path.join(udev, QUIRK_CONF), f"/etc/modprobe.d/{QUIRK_CONF}")]


def packaged_system_files():
    return [f"/usr/lib/udev/rules.d/{UDEV_RULES}", f"/usr/lib/modprobe.d/{QUIRK_CONF}"]


def usbhid_builtin(release=None, modules_dir="/lib/modules"):
    """True when usbhid is compiled into the kernel: modprobe.d cannot reach it."""
    release = release or platform.release()
    try:
        with open(os.path.join(modules_dir, release, "modules.builtin")) as f:
            return any(line.strip().endswith("/usbhid.ko") for line in f)
    except OSError:
        return False


def initramfs_command():
    """usbhid loads from the initramfs on most distros, so it must carry the quirk."""
    for tool, cmd in (("update-initramfs", ["update-initramfs", "-u"]),
                      ("mkinitcpio", ["mkinitcpio", "-P"]),
                      ("dracut", ["dracut", "--force"])):
        if shutil.which(tool):
            return cmd
    return None


def system_plan():
    cmds = [["install", "-m", "0644", src, dst] for src, dst in system_files()]
    if os.path.exists(LEGACY_RULES):
        cmds.append(["rm", "-f", LEGACY_RULES])
    initramfs = initramfs_command()
    if initramfs:
        cmds.append(initramfs)
    cmds += [["udevadm", "control", "--reload-rules"], ["udevadm", "trigger"]]
    return [["sudo", *c] for c in cmds]


def install_system(args):
    files = system_files()
    missing = [src for src, _ in files if not os.path.exists(src)]
    if missing:
        print(f"ragnaros: bundled files missing: {', '.join(missing)}", file=sys.stderr)
        return 1
    if all(os.path.exists(p) for p in packaged_system_files()) and not args.force:
        print("The udev rules and the usbhid quirk are already installed by your package\n"
              f"manager ({', '.join(packaged_system_files())}). Nothing to do; "
              "--force installs the /etc copies anyway.")
        return 0
    plan = system_plan()
    if args.print:
        for src, dst in files:
            print(f"# {dst}")
            with open(src) as f:
                print(f.read().rstrip())
            print()
        print("# commands")
        for cmd in plan:
            print(shlex.join(cmd))
    else:
        print("Installing the udev rules and the usbhid quirk (needs sudo):")
        for cmd in plan:
            print(f"  $ {shlex.join(cmd)}")
            result = subprocess.run(cmd)
            if result.returncode != 0:
                print(f"ragnaros: failed ({result.returncode}): {shlex.join(cmd)}",
                      file=sys.stderr)
                return result.returncode
    if usbhid_builtin():
        print(f"\nusbhid is built into this kernel, so modprobe.d cannot reach it: add\n"
              f"  {QUIRK_PARAM}\nto the kernel command line (bootloader config) instead.")
    if not args.print:
        print("\nReboot once so usbhid loads with the quirk; then the deck is yours.\n"
              "Next: ragnaros install-service")
    return 0


# -- install-service --------------------------------------------------------------
def command_path(name, module):
    """How systemd should start one of our commands from this installation."""
    sibling = os.path.join(os.path.dirname(sys.executable), name)
    if os.access(sibling, os.X_OK):
        return sibling
    found = shutil.which(name)
    if found:
        return os.path.realpath(found)
    return f"{sys.executable} -m {module}"


def unit_text(filename, exec_paths):
    with open(os.path.join(paths.bundled(os.path.join("packaging", "systemd")), filename)) as f:
        text = f.read()
    for name, packaged in PACKAGED_UNIT_EXEC.items():
        text = text.replace(packaged, exec_paths[name])
    return text


def user_unit_dir():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "systemd", "user")


def install_service(args):
    exec_paths = {"ragnarosd": command_path("ragnarosd", "ragnaros.daemon"),
                  "ragnaros-fetch-gifs": command_path("ragnaros-fetch-gifs",
                                                      "ragnaros.fetch_gifs")}
    units = ["ragnarosd.service"]
    if args.gif_refresh:
        units += ["ragnaros-gif-refresh.service", "ragnaros-gif-refresh.timer"]
    texts = {u: unit_text(u, exec_paths) for u in units}
    if args.print:
        for unit, text in texts.items():
            print(f"# {os.path.join(user_unit_dir(), unit)}\n{text}")
        return 0
    directory = user_unit_dir()
    for unit, text in texts.items():
        dst = os.path.join(directory, unit)
        if os.path.exists(dst) and not args.force:
            with open(dst) as f:
                if f.read() != text:
                    print(f"ragnaros: {dst} exists and differs (a git-checkout install?);\n"
                          "  rerun with --force to replace it, or --print to compare.",
                          file=sys.stderr)
                    return 1
    os.makedirs(directory, exist_ok=True)
    for unit, text in texts.items():
        with open(os.path.join(directory, unit), "w") as f:
            f.write(text)
        print(f"wrote {os.path.join(directory, unit)}")
    steps = [["systemctl", "--user", "daemon-reload"],
             ["systemctl", "--user", "enable", "ragnarosd.service"]]
    if args.gif_refresh:
        steps.append(["systemctl", "--user", "enable", "--now", "ragnaros-gif-refresh.timer"])
    for cmd in steps:
        if subprocess.run(cmd).returncode != 0:
            print(f"ragnaros: failed: {shlex.join(cmd)}", file=sys.stderr)
            return 1
    print("Enabled. Start it with: systemctl --user start ragnarosd")
    return 0


# -- paths ----------------------------------------------------------------------------
def show_paths(args):
    gif_theme = theme.load()
    rows = [
        ("config", paths.config_dir()),
        ("data", paths.data_dir()),
        ("profiles", "  ".join(paths.profile_dirs())),
        ("assets", "  ".join(paths.asset_roots())),
        ("gif theme", f"{gif_theme.get('theme', '?')} ({theme.path()})" if gif_theme
         else "none - bundled idle art (ragnaros-fetch-gifs to opt in)"),
        ("udev", paths.bundled("udev")),
        ("control", control.socket_path()),
    ]
    for key, value in rows:
        print(f"{key:<10} {value}")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="ragnaros", description="Setup helpers for the Ragnaros deck daemon.",
        epilog="The daemon itself is `ragnarosd`; drive it with `ragnarosctl`.")
    parser.add_argument("--version", action="version", version=f"ragnaros {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="command")

    p = sub.add_parser("install-system",
                       help="install the udev rules and the usbhid quirk (sudo)")
    p.add_argument("--print", action="store_true",
                   help="show the files and commands instead of running them")
    p.add_argument("--force", action="store_true",
                   help="install /etc copies even if a package already ships them")
    p.set_defaults(func=install_system)

    p = sub.add_parser("install-service", help="install the ragnarosd systemd user unit")
    p.add_argument("--print", action="store_true", help="show the units instead of writing")
    p.add_argument("--force", action="store_true", help="replace existing unit files")
    p.add_argument("--gif-refresh", action="store_true",
                   help="also enable the weekly opt-in GIF theme refresh timer")
    p.set_defaults(func=install_service)

    p = sub.add_parser("paths", help="show where profiles, assets and GIF themes live")
    p.set_defaults(func=show_paths)

    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
