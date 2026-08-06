"""Pluggable web-search providers used by the researcher node."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import httpx


class SearchProvider(ABC):
    @abstractmethod
    def search(self, query: str, max_results: int = 5) -> list[dict[str, Any]]: ...


class MockSearchProvider(SearchProvider):
    def search(self, query: str, max_results: int = 5) -> list[dict[str, Any]]:
        return [{"title": "Offline mock evidence", "url": "mock://search", "content": f"Deterministic result for: {query[:160]}"}]


class TavilySearchProvider(SearchProvider):
    def __init__(self, api_key: str):
        self.api_key = api_key

    def search(self, query: str, max_results: int = 5) -> list[dict[str, Any]]:
        response = httpx.post("https://api.tavily.com/search", json={"api_key": self.api_key, "query": query, "max_results": min(max_results, 8), "search_depth": "advanced"}, timeout=20)
        response.raise_for_status()
        return [{"title": item.get("title", ""), "url": item.get("url", ""), "content": item.get("content", "")[:2000]} for item in response.json().get("results", [])]
