import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ["RAGNAROS_CONFIG"] = REPO
sys.path.insert(0, os.path.join(REPO, "daemon"))
