from dep_automation.config import Config


def test_from_dict_reads_state_path_and_devin():
    cfg = Config.from_dict(
        {
            "target_repo": "acme/target",
            "target_repo_path": "/tmp/target",
            "state_path": "/custom/state.json",
            "manifests": [{"path": "pyproject.toml", "include_optional": True}],
            "devin": {"api_version": "v1", "org_id": "org-xyz", "tags": ["t"]},
        }
    )
    assert cfg.state_path == "/custom/state.json"
    assert cfg.devin_api_version == "v1"
    assert cfg.devin_org_id == "org-xyz"
    assert cfg.devin_tags == ["t"]
    assert cfg.manifests[0].include_optional is True


def test_state_path_default():
    cfg = Config.from_dict({"target_repo": "a/b"})
    assert cfg.state_path == "state/processed.json"
    assert cfg.devin_api_version == "v3"
