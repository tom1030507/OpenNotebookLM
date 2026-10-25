"""Search configured web providers for importable public pages."""
import requests

from app.config import Settings
from app.utils.network import UnsafeURLError, validate_http_url_syntax


class WebSearchService:
    """Run a search through the configured provider and normalize its results."""

    def __init__(self, settings: Settings):
        """Store the deployment's search configuration.

        Args:
            settings: Application settings containing provider credentials.

        Returns:
            None.
        """
        self.settings = settings

    @property
    def enabled(self) -> bool:
        """Return whether the configured provider has its required setting.

        Returns:
            Whether web discovery can make a provider request.
        """
        return self.settings.search_enabled

    def search(self, query: str, count: int) -> list[dict[str, str]]:
        """Search the selected provider and return safe, unique results.

        Args:
            query: Search terms supplied by the project editor.
            count: Maximum number of results to return.

        Returns:
            Results with title, normalized URL, and snippet fields.

        Raises:
            requests.RequestException: If the provider request fails.
        """
        if not self.enabled:
            return []
        count = max(1, min(count, 20))
        provider = self.settings.search_provider

        if provider == "searxng":
            response = requests.get(
                "%s/search" % (self.settings.searxng_url or "").rstrip("/"),
                params={"q": query, "format": "json"},
                timeout=10,
            )
            response.raise_for_status()
            items = response.json().get("results", [])
        elif provider == "brave":
            response = requests.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": query, "count": count},
                headers={"X-Subscription-Token": self.settings.brave_search_api_key},
                timeout=10,
            )
            response.raise_for_status()
            items = (response.json().get("web") or {}).get("results", [])
        elif provider == "tavily":
            response = requests.post(
                "https://api.tavily.com/search",
                headers={"Authorization": "Bearer %s" % self.settings.tavily_api_key},
                json={
                    "query": query,
                    "search_depth": "basic",
                    "max_results": count,
                    "include_answer": False,
                    "include_raw_content": False,
                },
                timeout=10,
            )
            response.raise_for_status()
            items = response.json().get("results", [])
        else:
            return []

        results = []
        seen = set()
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            try:
                url = validate_http_url_syntax(item.get("url"))
            except UnsafeURLError:
                continue
            if url in seen:
                continue
            seen.add(url)
            results.append({
                "title": str(item.get("title") or "").strip()[:300],
                "url": url,
                "snippet": str(item.get("content") or item.get("description") or "").strip()[:500],
            })
            if len(results) == count:
                break
        return results
