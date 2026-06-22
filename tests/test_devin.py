import json

import pytest

from dep_automation.devin import DevinApiError, DevinClient


def _capture():
    captured = {}

    def transport(method, url, headers, body):
        captured["method"] = method
        captured["url"] = url
        captured["headers"] = headers
        captured["body"] = json.loads(body)
        return {
            "session_id": "devin-123",
            "url": "https://app.devin.ai/sessions/123",
            "status": "new",
        }

    return captured, transport


def test_v3_create_session_builds_request():
    captured, transport = _capture()
    client = DevinClient(api_key="key", org_id="org-abc", transport=transport)
    session = client.create_session("do it", title="t", tags=["x"], max_acu_limit=10)

    assert session.session_id == "devin-123"
    assert captured["method"] == "POST"
    assert captured["url"].endswith("/v3/organizations/org-abc/sessions")
    assert captured["headers"]["Authorization"] == "Bearer key"
    # v3 has no idempotent field
    assert captured["body"] == {
        "prompt": "do it",
        "title": "t",
        "tags": ["x"],
        "max_acu_limit": 10,
    }


def test_v1_create_session_builds_request():
    captured, transport = _capture()
    client = DevinClient(api_key="key", api_version="v1", transport=transport)
    client.create_session("do it", idempotent=True)
    assert captured["url"].endswith("/v1/sessions")
    assert captured["body"] == {"prompt": "do it", "idempotent": True}


def test_v3_requires_org_id():
    client = DevinClient(api_key="key", org_id=None, transport=lambda *a: {})
    with pytest.raises(DevinApiError):
        client.create_session("x")


def test_missing_api_key_raises():
    client = DevinClient(api_key=None, org_id="org-abc", transport=lambda *a: {})
    with pytest.raises(DevinApiError):
        client.create_session("x")


def test_unexpected_response_raises():
    client = DevinClient(api_key="k", org_id="org-abc", transport=lambda *a: {"oops": True})
    with pytest.raises(DevinApiError):
        client.create_session("x")


def test_get_session_parses_status_and_pr():
    captured = {}

    def transport(method, url, headers, body):
        captured["method"] = method
        captured["url"] = url
        return {
            "session_id": "s1",
            "status": "finished",
            "status_detail": "done",
            "acus_consumed": 4.2,
            "pull_requests": [
                {"pr_url": "https://github.com/o/r/pull/1", "pr_state": "open"},
                {"pr_url": "https://github.com/o/r/pull/2", "pr_state": "merged"},
            ],
        }

    client = DevinClient(api_key="k", org_id="org-abc", transport=transport)
    status = client.get_session("s1")

    assert captured["method"] == "GET"
    assert captured["url"].endswith("/v3/organizations/org-abc/sessions/s1")
    assert status.status == "finished"
    assert status.acus_consumed == 4.2
    # prefers the merged PR over the open one
    assert status.pr_state == "merged"
    assert status.pr_url.endswith("/pull/2")


def test_get_session_no_pr():
    transport = lambda *a: {"session_id": "s1", "status": "running", "pull_requests": []}  # noqa: E731
    client = DevinClient(api_key="k", org_id="org-abc", transport=transport)
    status = client.get_session("s1")
    assert status.pr_url is None
    assert status.status == "running"
