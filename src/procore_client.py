"""Read-only Procore REST client.

Only GET requests are sent to the API. The single POST is the OAuth token
request to the login server, which writes nothing to Procore.
"""
from __future__ import annotations

import logging
import os
import re
import time

import requests
from dotenv import load_dotenv

log = logging.getLogger(__name__)

HOSTS = {
    "production": ("https://login.procore.com/oauth/token", "https://api.procore.com"),
    "sandbox": ("https://login-sandbox.procore.com/oauth/token", "https://sandbox.procore.com"),
}


class ProcoreError(Exception):
    def __init__(self, status: int, url: str, body: str):
        super().__init__(f"HTTP {status} for {url}: {body[:300]}")
        self.status = status
        self.url = url


class ProcoreClient:
    def __init__(self, env_file: str | None = ".env"):
        load_dotenv(env_file)
        self.client_id = os.environ["PROCORE_CLIENT_ID"]
        self.client_secret = os.environ["PROCORE_CLIENT_SECRET"]
        self.company_id = os.environ["PROCORE_COMPANY_ID"]
        env = os.environ.get("PROCORE_ENV", "production")
        self.token_url, self.base = HOSTS[env]
        self.session = requests.Session()
        self._token: str | None = None
        self._token_expires = 0.0

    # ---- auth -------------------------------------------------------------
    def _refresh_token(self) -> None:
        resp = requests.post(
            self.token_url,
            auth=(self.client_id, self.client_secret),
            data={"grant_type": "client_credentials"},
            timeout=30,
        )
        if resp.status_code != 200:
            raise ProcoreError(resp.status_code, self.token_url, resp.text)
        data = resp.json()
        self._token = data["access_token"]
        # refresh 5 minutes early
        self._token_expires = time.time() + int(data.get("expires_in", 3600)) - 300
        log.info("Obtained Procore token (expires in %ss)", data.get("expires_in"))

    def _auth_headers(self) -> dict:
        if not self._token or time.time() >= self._token_expires:
            self._refresh_token()
        return {
            "Authorization": f"Bearer {self._token}",
            "Procore-Company-Id": str(self.company_id),
        }

    # ---- GET --------------------------------------------------------------
    def get_response(self, path: str, params: dict | None = None, max_retries: int = 6) -> requests.Response:
        url = path if path.startswith("http") else f"{self.base}{path}"
        delay = 2.0
        for attempt in range(max_retries + 1):
            resp = self.session.get(url, headers=self._auth_headers(), params=params, timeout=60)
            if resp.status_code == 401 and attempt == 0:
                self._token = None  # token revoked/expired early: refresh once
                continue
            if resp.status_code == 429 or resp.status_code >= 500:
                wait = delay
                reset = resp.headers.get("X-Rate-Limit-Reset")
                if resp.status_code == 429 and reset and reset.isdigit():
                    wait = max(1.0, int(reset) - time.time())
                log.warning("HTTP %s on %s, retrying in %.0fs", resp.status_code, url, wait)
                time.sleep(min(wait, 120))
                delay *= 2
                continue
            if resp.status_code >= 400:
                raise ProcoreError(resp.status_code, url, resp.text)
            return resp
        raise ProcoreError(resp.status_code, url, resp.text)

    def get(self, path: str, params: dict | None = None):
        return self.get_response(path, params).json()

    def get_all(self, path: str, params: dict | None = None, per_page: int = 100) -> list:
        """Follow page/per_page pagination until all records are read."""
        params = dict(params or {})
        params["per_page"] = per_page
        page, out = 1, []
        while True:
            params["page"] = page
            resp = self.get_response(path, params)
            data = resp.json()
            if isinstance(data, dict):  # some endpoints wrap results
                data = data.get("data", data.get("entities", [data]))
            out.extend(data)
            total = resp.headers.get("Total")
            link = resp.headers.get("Link", "")
            if total is not None and len(out) >= int(total):
                break
            if total is None and not re.search(r'rel="next"', link) and len(data) < per_page:
                break
            if not data:
                break
            page += 1
        return out
