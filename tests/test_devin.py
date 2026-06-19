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
