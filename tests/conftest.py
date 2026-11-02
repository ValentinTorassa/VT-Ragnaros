import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

# Never read or write the real user's files: no config overrides, no GIF
# theme, no usage log or saved profile. Profiles and assets then resolve to
# the bundled ones in the checkout.
_HOME = tempfile.mkdtemp(prefix="ragnaros-tests-")
os.environ["RAGNAROS_CONFIG"] = os.path.join(_HOME, "config")
os.environ["RAGNAROS_DATA"] = os.path.join(_HOME, "data")
os.environ["XDG_STATE_HOME"] = os.path.join(_HOME, "state")
os.environ["XDG_CONFIG_HOME"] = os.path.join(_HOME, "xdg-config")
os.environ["RAGNAROS_USAGE_LOG"] = os.path.join(_HOME, "state", "usage.jsonl")
# The Claude hook's Jev settings and key come from the environment too (and a
# test run inside Claude Code inherits CLAUDE_PROJECT_DIR): start from none.
for _name in ("RAGNAROS_JEV", "RAGNAROS_JEV_SKIP", "RAGNAROS_JEV_LOG", "RAGNAROS_JEV_KEY_FILE",
              "RAGNAROS_JEV_MODEL", "RAGNAROS_JEV_PROVIDER", "AI_GATEWAY_API_KEY",
              "OPENROUTER_API_KEY", "CLAUDE_PROJECT_DIR",
              "RAGNAROS_CLAUDE_HOOK_MODE", "RAGNAROS_CLAUDE_HOOK_SECONDS"):
    os.environ.pop(_name, None)
