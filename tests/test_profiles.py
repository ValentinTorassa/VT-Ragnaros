import glob
import os

import pytest
import yaml

import ragnarosd

PROFILES = sorted(glob.glob(os.path.join(os.environ["RAGNAROS_CONFIG"], "profiles", "*.yaml")))


def test_bundled_profiles_exist():
    assert len(PROFILES) >= 4


@pytest.mark.parametrize("path", PROFILES, ids=[os.path.basename(p) for p in PROFILES])
def test_bundled_profiles_are_valid(path):
    with open(path) as f:
        profile = yaml.safe_load(f)
    profile["_name"] = os.path.basename(path)[:-len(".yaml")]
    issues = ragnarosd.validate_profile(profile, os.environ["RAGNAROS_CONFIG"])
    assert issues == [], f"{path}: {issues}"


def test_validate_profile_catches_missing_asset():
    profile = {
        "_name": "broken",
        "keys": {"3": {"icon": "icons/ghost.png", "action": "true"}},
        "strip": {"segments": ["gifs/segments/missing.gif"]},
    }
    issues = ragnarosd.validate_profile(profile, os.environ["RAGNAROS_CONFIG"])
    assert any("missing asset gifs/segments/missing.gif" in i for i in issues)


def test_validate_profile_catches_bad_keys():
    profile = {
        "_name": "broken",
        "keys": {"12": {"action": "true"}, "x": {"action": "true"}, "1": {"icon": "icons/obs.png"}},
    }
    issues = ragnarosd.validate_profile(profile, os.environ["RAGNAROS_CONFIG"])
    assert any("outside 0-9" in i for i in issues)
    assert any("not an integer" in i for i in issues)
    assert any("no action or profile" in i for i in issues)


def test_load_profile_adds_name():
    profile = ragnarosd.load_profile("streaming")
    assert profile["_name"] == "streaming"
    assert "keys" in profile
