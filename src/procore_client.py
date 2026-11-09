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
        self.request_count = 0
        self._rl_remaining: int | None = None
        self._rl_reset = 0.0

    # ---- rate limiting -----------------------------------------------------
    # Procore returns X-Rate-Limit-Limit/Remaining/Reset (observed: 25 per ~10s
    # window). Pause before the window is exhausted instead of waiting for 429s.
    def _note_rate_limit(self, resp) -> None:
        rem, reset = resp.headers.get("X-Rate-Limit-Remaining"), resp.headers.get("X-Rate-Limit-Reset")
        if rem is not None and rem.isdigit():
            self._rl_remaining = int(rem)
        if reset is not None and reset.isdigit():
            self._rl_reset = float(reset)

    def _throttle(self) -> None:
        if self._rl_remaining is not None and self._rl_remaining <= 1:
            wait = self._rl_reset - time.time() + 0.5
            if wait > 0:
                time.sleep(min(wait, 120))
            self._rl_remaining = None

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
        resp = None
        rate_waits = 0
        attempt = 0
        while attempt <= max_retries:
            self._throttle()
            try:
                resp = self.session.get(url, headers=self._auth_headers(), params=params, timeout=60)
            except requests.RequestException as exc:  # network blip: back off and retry
                attempt += 1
                log.warning("Network error on %s (%s), retrying in %.0fs", url, exc, delay)
                time.sleep(delay)
                delay *= 2
                continue
            self._note_rate_limit(resp)
            self.request_count += 1
            if resp.status_code != 429:
                attempt += 1
            if resp.status_code == 401 and attempt == 1:
                self._token = None  # token revoked/expired early: refresh once
                continue
            if resp.status_code == 429:
                # Procore has a short window (~25 req/10 s) and an hourly limit (~3,600/h).
                # Wait for the reset either way; this does not count as a failed attempt.
                reset = resp.headers.get("X-Rate-Limit-Reset")
                wait = max(1.0, int(reset) - time.time() + 1) if reset and reset.isdigit() else 60.0
                rate_waits += 1
                if rate_waits > 20:
                    raise ProcoreError(429, url, "rate limited too many times")
                log.warning("Rate limited by Procore; waiting %.0fs (until the limit resets)", min(wait, 3700))
                time.sleep(min(wait, 3700))
                continue
            if resp.status_code >= 500:
                log.warning("HTTP %s on %s, retrying in %.0fs", resp.status_code, url, delay)
                time.sleep(delay)
                delay *= 2
                continue
            if resp.status_code >= 400:
                raise ProcoreError(resp.status_code, url, resp.text)
            return resp
        raise ProcoreError(getattr(resp, 'status_code', 0), url, getattr(resp, 'text', 'network error'))

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
