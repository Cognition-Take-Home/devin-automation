"""Minimal client for the Devin REST API (v1).

Only the endpoints the automation needs are implemented. Auth is a bearer token read
from the ``DEVIN_API_KEY`` environment variable (or passed explicitly).
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
    is_new_session: bool | None = None


class DevinClient:
    def __init__(
        self,
        api_key: str | None = None,
        *,
        api_base: str = "https://api.devin.ai",
        transport=None,
    ):
        self.api_key = api_key or os.environ.get("DEVIN_API_KEY")
        self.api_base = api_base.rstrip("/")
        # ``transport`` lets tests inject a fake; signature: (method, url, headers, body) -> dict
        self._transport = transport or self._http_transport

    def create_session(
        self,
        prompt: str,
        *,
        title: str | None = None,
        tags: list[str] | None = None,
        idempotent: bool = True,
        max_acu_limit: int | None = None,
    ) -> CreatedSession:
        if not self.api_key:
            raise DevinApiError(
                "No Devin API key configured. Set the DEVIN_API_KEY environment variable."
            )
        body: dict = {"prompt": prompt, "idempotent": idempotent}
        if title:
            body["title"] = title
        if tags:
            body["tags"] = tags
        if max_acu_limit is not None:
            body["max_acu_limit"] = max_acu_limit

        data = self._transport(
            "POST",
            f"{self.api_base}/v1/sessions",
            self._headers(),
            json.dumps(body).encode("utf-8"),
        )
        if "session_id" not in data:
            raise DevinApiError(f"Unexpected response from Devin API: {data}")
        return CreatedSession(
            session_id=data["session_id"],
            url=data.get("url", ""),
            is_new_session=data.get("is_new_session"),
        )

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
