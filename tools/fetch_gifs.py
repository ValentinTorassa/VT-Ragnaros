#!/usr/bin/env python3
"""Checkout entry point for `ragnaros-fetch-gifs` (the GIF refresh timer runs it)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

from ragnaros.fetch_gifs import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
