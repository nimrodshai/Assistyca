"""News search: the latest dated items on a topic, for the conversational agent."""

from packages.tools.news_search.search import NEWS_SEARCH_MAX_RESULTS
from packages.tools.news_search.search import search_news

__all__ = ["NEWS_SEARCH_MAX_RESULTS", "search_news"]
