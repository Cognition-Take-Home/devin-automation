"""Minimal client for the Devin REST API.

Supports the current **v3** organization-scoped endpoint (default) and the legacy
**v1** endpoint. Auth is a bearer token (a ``cog_`` service-user key or PAT) read from
the ``DEVIN_API_KEY`` environment variable, or passed explicitly.

v3 sessions are created under an organization:
``POST /v3/organizations/{org_id}/sessions``. The org id comes from config or the
``DEVIN_ORG_ID`` environment variable.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass


class DevinApiError(RuntimeError):
    """Raised when the Devin API returns an error or is misconfigured."""


@dataclass
class CreatedSession:
    session_id: str
    url: str
    status: str | None = None


class DevinClient:
    def __init__(
        self,
        api_key: str | None = None,
        *,
        org_id: str | None = None,
        api_base: str = "https://api.devin.ai",
        api_version: str = "v3",
        transport=None,
    ):
        self.api_key = api_key or os.environ.get("DEVIN_API_KEY")
        self.org_id = org_id or os.environ.get("DEVIN_ORG_ID")
        self.api_base = api_base.rstrip("/")
        self.api_version = api_version
        # ``transport`` lets tests inject a fake; signature: (method, url, headers, body) -> dict
        self._transport = transport or self._http_transport

    def create_session(
        self,
        prompt: str,
        *,
        title: str | None = None,
        tags: list[str] | None = None,
        idempotent: bool = True,  # v1 only; ignored by v3
        max_acu_limit: int | None = None,
    ) -> CreatedSession:
        if not self.api_key:
            raise DevinApiError(
                "No Devin API key configured. Set the DEVIN_API_KEY environment variable."
            )

        url, body = self._build_request(prompt, title, tags, idempotent, max_acu_limit)
        data = self._transport("POST", url, self._headers(), json.dumps(body).encode("utf-8"))
        if "session_id" not in data:
            raise DevinApiError(f"Unexpected response from Devin API: {data}")
        return CreatedSession(
            session_id=data["session_id"],
            url=data.get("url", ""),
            status=data.get("status"),
        )

    def _build_request(
        self,
        prompt: str,
        title: str | None,
        tags: list[str] | None,
        idempotent: bool,
        max_acu_limit: int | None,
    ) -> tuple[str, dict]:
        body: dict = {"prompt": prompt}
        if title:
            body["title"] = title
        if tags:
            body["tags"] = tags
        if max_acu_limit is not None:
            body["max_acu_limit"] = max_acu_limit

        if self.api_version == "v1":
            body["idempotent"] = idempotent
            return f"{self.api_base}/v1/sessions", body

        if not self.org_id:
            raise DevinApiError(
                "Devin v3 API requires an organization id. Set DEVIN_ORG_ID or "
                "devin.org_id in the config."
            )
        return f"{self.api_base}/v3/organizations/{self.org_id}/sessions", body

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _http_transport(method: str, url: str, headers: dict, body: bytes) -> dict:
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise DevinApiError(f"Devin API HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise DevinApiError(f"Devin API request failed: {exc}") from exc
