"""Shared HTTP plumbing for connectors."""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from pma.models import MarketSnapshot

log = logging.getLogger(__name__)


class ConnectorError(RuntimeError):
    pass


class AuthRequiredError(ConnectorError):
    """Platform requires API credentials that are not configured."""


class BaseConnector(ABC):
    """A connector turns a platform API into unified MarketSnapshots.

    Requests honor standard HTTP(S)_PROXY environment variables, so a local
    proxy can be configured via .env without code changes.
    """

    platform: str = "base"

    def __init__(self, timeout: int = 30, pages: int = 3, page_size: int = 100):
        self.timeout = timeout
        self.pages = pages
        self.page_size = page_size
        self.session = requests.Session()
        retry = Retry(
            total=3, backoff_factor=1.0,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retry))

    @abstractmethod
    def fetch_markets(self, top_n: int) -> List[MarketSnapshot]:
        """Fetch current market data, ranked by 24h volume, top_n capped."""

    def get_json(self, url: str, params: Optional[dict] = None,
                 headers: Optional[dict] = None) -> dict:
        try:
            resp = self.session.get(url, params=params, headers=headers,
                                    timeout=self.timeout)
        except requests.RequestException as e:
            raise ConnectorError(f"{self.platform}: request failed: {e}") from e
        if resp.status_code in (401, 403):
            raise AuthRequiredError(
                f"{self.platform}: HTTP {resp.status_code} - credentials "
                f"required or invalid")
        resp.raise_for_status()
        return resp.json()
