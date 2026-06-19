import json

import pytest

from dep_automation.devin import DevinApiError, DevinClient


def test_create_session_builds_request():
    captured = {}

    def transport(method, url, headers, body):
        captured["method"] = method
        captured["url"] = url
        captured["headers"] = headers
        captured["body"] = json.loads(body)
        return {"session_id": "devin-123", "url": "https://app.devin.ai/sessions/123"}

    client = DevinClient(api_key="key", transport=transport)
    session = client.create_session("do it", title="t", tags=["x"], max_acu_limit=10)

    assert session.session_id == "devin-123"
    assert captured["method"] == "POST"
    assert captured["url"].endswith("/v1/sessions")
    assert captured["headers"]["Authorization"] == "Bearer key"
    assert captured["body"] == {
        "prompt": "do it",
        "idempotent": True,
        "title": "t",
        "tags": ["x"],
        "max_acu_limit": 10,
    }


def test_missing_api_key_raises():
    client = DevinClient(api_key=None, transport=lambda *a: {})
    with pytest.raises(DevinApiError):
        client.create_session("x")


def test_unexpected_response_raises():
    client = DevinClient(api_key="k", transport=lambda *a: {"oops": True})
    with pytest.raises(DevinApiError):
        client.create_session("x")
