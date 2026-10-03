#!/usr/bin/env python3
"""Run the daemon from a git checkout (the path install.sh's unit points at).

Packaged installs get a `ragnarosd` command instead; both run
ragnaros.daemon.main().
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

from ragnaros.daemon import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
