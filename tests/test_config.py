from dep_automation.config import Config
from dep_automation.models import Ecosystem


def test_from_dict_reads_state_path_and_devin():
    cfg = Config.from_dict(
        {
            "target_repo": "acme/target",
            "target_repo_path": "/tmp/target",
            "state_path": "/custom/state.json",
            "shortlist_size": 3,
            "cooldown_days": 14,
            "usage_paths": {"pypi": ["src"], "npm": ["frontend"]},
            "manifests": [{"path": "pyproject.toml", "include_optional": True}],
            "devin": {"api_version": "v1", "org_id": "org-xyz", "tags": ["t"]},
        }
    )
    assert cfg.state_path == "/custom/state.json"
    assert cfg.shortlist_size == 3
    assert cfg.cooldown_days == 14
    assert cfg.usage_paths_for(Ecosystem.PYPI) == ["src"]
    assert cfg.devin_api_version == "v1"
    assert cfg.devin_org_id == "org-xyz"
    assert cfg.devin_tags == ["t"]
    assert cfg.manifests[0].include_optional is True


def test_defaults():
    cfg = Config.from_dict({"target_repo": "a/b"})
    assert cfg.state_path == "state/processed.json"
    assert cfg.history_path == "state/history.jsonl"
    assert cfg.shortlist_size == 5
    assert cfg.cooldown_days == 30
    assert cfg.devin_api_version == "v3"
    # ecosystems with no configured path default to the whole repo
    assert cfg.usage_paths_for("npm") == ["."]
