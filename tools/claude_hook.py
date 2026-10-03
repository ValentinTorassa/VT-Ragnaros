#!/usr/bin/env python3
"""Checkout entry point for the Claude Code hook (`ragnaros-claude-hook` when installed)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

from ragnaros.claude_hook import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
