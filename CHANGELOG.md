# Changelog

Notable changes to VT-Ragnaros. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [0.1.2] - 2026-11-10

### Added

- `ragnaros diagnose`: a read-only Markdown report of every vendor-0200 device
  (or `--device VID:PID`) to paste into an issue: IDs and strings, interfaces
  and endpoints, HID report descriptors, device nodes and their permissions, the
  udev rules and usbhid quirks that cover it, and the ragnaros, kernel and
  distro versions. It never opens the device and leaves out the serial number,
  hostname and user names. See "Reporting a new device" in the README.
- `ragnarosd --experimental-pid` (or `RAGNAROS_EXPERIMENTAL_PID`), off by
  default: also opens an untested vendor-0200 product ID and drives it with the
  SS552 protocol, so the owner of a sibling deck can check whether images and
  input work. The daemon says EXPERIMENTAL at startup and on attach,
  `ragnarosctl status` shows it, and every raw input report is logged.
- Claude hook: an optional Jev step that tells a waiting, finished or stuck
  session apart (`jev: off | shadow | on`, off by default). Rules still decide
  permission prompts, `StopFailure` and background tasks; folders in `jev_skip`
  never reach Jev, and any failure falls back to the usual notice.
  `ragnaros-claude-hook review | label | eval` work over its log.
- `CITATION.cff` with software citation metadata.

### Changed

- CI runs on `ubuntu-24.04` instead of `ubuntu-latest`.
- Dependabot version updates are gone; the dependency audit in `security.yml`
  stays.

### Fixed

- README: the output endpoint `0x03` is interrupt, not bulk.

## [0.1.1] - 2026-10-14

### Added

- `debian/`: a Debian source package (pybuild, DEP-5 copyright, man pages,
  opt-in user units) built from a `+ds` repack without the app-logo key icons,
  plus a draft ITP in `packaging/debian/` (not filed).
- Security workflow with pip-audit and CodeQL. CI runs with read-only
  permissions and every action pinned by SHA.

### Changed

- The release workflow builds on Ubuntu 24.04 instead of `ubuntu-latest`.

### Fixed

- Album art is fetched off the main loop, with timeouts and an 8 MiB cap: a
  cover host that stalls no longer freezes the deck.
- Actions expand `~` at the start of an argument and after `--option=`. The
  README now says actions run without a shell.
- Flaky control-socket tests, and art tests that failed behind the dead proxy
  a Debian build sets.

## [0.1.0] - 2026-10-05

First tagged release.

- Userspace driver and daemon for the Redragon SS552 over libusb: icons and
  animated GIFs on the ten LCD keys and the four-panel touch strip, and a
  command for every key, knob, tap and swipe, mapped in YAML profiles.
- The strip shows what is playing, a system dashboard, desktop notifications
  or idle animations. Key layers, hot profile switching, OBS and pomodoro
  integrations, and a usage log.
- `ragnarosctl` control socket, a Claude Code hook that toasts on the strip,
  and the deck goes dark when the session locks.
- USB recovery without replugging the cable, and a firmware display reset.
- Packaged as `ragnaros` with console commands and opt-in GIF themes; a `.deb`,
  an AUR PKGBUILD, and a release workflow that attaches the wheel, sdist and
  `.deb` to every `v*` tag.

[0.1.2]: https://github.com/ValentinTorassa/VT-Ragnaros/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/ValentinTorassa/VT-Ragnaros/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/ValentinTorassa/VT-Ragnaros/releases/tag/v0.1.0
