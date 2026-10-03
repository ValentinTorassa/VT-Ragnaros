#!/usr/bin/env bash
# Build the .deb from an already-built wheel with nfpm.
#
#   uv build            # or: python3 -m build
#   packaging/deb/build-deb.sh [dist-dir]
#
# The wheel is unpacked into /usr/lib/python3/dist-packages (it is pure
# Python) and every console script in its entry_points.txt becomes a small
# /usr/bin wrapper for the system python3.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DIST="$(cd "${1:-$ROOT/dist}" && pwd)"
shopt -s nullglob
wheels=("$DIST"/ragnaros-*-py3-none-any.whl)
if (( ${#wheels[@]} != 1 )); then
  echo "build-deb: expected exactly one ragnaros wheel in $DIST, found ${#wheels[@]}" >&2
  exit 1
fi
command -v nfpm >/dev/null || { echo "build-deb: nfpm not found (https://nfpm.goreleaser.com)" >&2; exit 1; }

STAGE="$ROOT/build/deb"  # nfpm.yaml reads it from here
rm -rf "$STAGE"
mkdir -p "$STAGE"

RAGNAROS_VERSION="$(python3 - "${wheels[0]}" "$STAGE" <<'PY'
import configparser, os, sys, zipfile

wheel, stage = sys.argv[1], sys.argv[2]
site = os.path.join(stage, "dist-packages")
bindir = os.path.join(stage, "bin")
os.makedirs(bindir)
with zipfile.ZipFile(wheel) as zf:
    zf.extractall(site)
    info = next(n for n in zf.namelist() if n.endswith(".dist-info/entry_points.txt"))
    entry_points = zf.read(info).decode()
parser = configparser.ConfigParser()
parser.read_string(entry_points)
for name, target in parser["console_scripts"].items():
    module, func = target.split(":")
    with open(os.path.join(bindir, name), "w") as f:
        f.write(f"#!/usr/bin/python3\nimport sys\n\nfrom {module} import {func}\n\n"
                f"sys.exit({func}())\n")
    os.chmod(os.path.join(bindir, name), 0o755)
# the version is the second field of the wheel file name
print(os.path.basename(wheel).split("-")[1])
PY
)"
chmod -R u=rwX,go=rX "$STAGE"  # Debian wants 0755/0644 whatever the local umask
export RAGNAROS_VERSION

cd "$ROOT"
nfpm package --config packaging/deb/nfpm.yaml --packager deb --target "$DIST/"
