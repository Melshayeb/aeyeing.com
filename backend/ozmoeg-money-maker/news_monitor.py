#!/usr/bin/env python3
"""
OzMoEg Money Maker — News Catalyst Monitor
Fetches and scores news for small-cap momentum trading.
"""
import re
import logging
import requests
from typing import List, Dict, Any, Tuple
from datetime import datetime, timedelta, timezone as dt_timezone
from dateutil import parser as date_parser
from webull_client import WebullClient

logger = logging.getLogger(__name__)

class NewsMonitor:
    """Monitor news and score catalyst impact 1–5."""

    # Ahmed Khaled catalyst ranking
    CATALYST_KEYWORDS = {
        5: [
            "acquisition", "acquired by", "buyout", "merger", "takeover",
            "acquired", "to be acquired", "strategic acquisition"
        ],
        4: [
            "fda approval", "patent granted", "patent award", "major contract",
            "partnership with", "collaboration with", "exclusive agreement",
            "licensing agreement", "breakthrough", "supply agreement",
            "supply contract", "strategic partnership", "technology partnership",
            "patent", "patents", "patent protection", "patent awarded",
            "granted patent", "wins patent", "new patent", "patent portfolio",
            "intellectual property"
        ],
        3: [
            "earnings beat", "beats earnings", "guidance raise", "raises guidance",
            "analyst upgrade", "price target raise", "strong demand",
            "revenue growth", "profit surge", "record revenue",
            "new contract", "contract award", "multi-year contract",
            "ai-powered", "artificial intelligence", "robotics", "automation",
            "autonomous", "machine learning"
        ],
        2: [
            "share buyback", "stock buyback", "insider buying", "insider purchase",
            "new product launch", "product launch", "expansion", "new market",
            "contracts awarded", "new customer",
            "voting control", "controlling stake", "majority stake",
            "strategic supply", "distribution agreement"
        ],
        1: [
            "strategic review", "exploring options", "letter of intent",
            "non-binding", "preliminary", "potential partnership",
            "considering", "evaluate"
        ]
    }

    # Red flags — avoid
    RED_FLAGS = [
        "offering", "public offering", "secondary offering",
        "dilution", "bankruptcy", "delisting",
        "sec investigation", "restated", "accounting irregularities",
        "going concern", "short report"
    ]

    # Drop news items older than this many days from analysis / website output
    MAX_NEWS_AGE_DAYS = 7

    def __init__(self, wb_client=None, config: Dict[str, Any] = None):
        # Accept either the raw legacy webull object or our WebullClient wrapper.
        if isinstance(wb_client, WebullClient):
            self.wb = wb_client._legacy_wb if hasattr(wb_client, '_legacy_wb') else wb_client
        else:
            self.wb = wb_client
        self.cfg = config or {}
        self.min_score = self.cfg.get('min_score', 3)
        self.min_sources = self.cfg.get('confirmation_sources', 2)

    def fetch_webull_news(self, ticker: str, items: int = 20, tId: int = None) -> List[Dict]:
        """Get news for a ticker from Webull API."""
        if not self.wb:
            return []
        try:
            raw = self.wb.get_news(ticker, tId=tId, items=items)
            if not raw:
                return []
            # Normalize
            if isinstance(raw, dict):
                return raw.get('news', [])
            return raw if isinstance(raw, list) else []
        except Exception as e:
            logger.warning("News fetch failed for %s: %s", ticker, e)
            return []

    def _parse_news_time(self, item: Dict) -> str:
        """Normalize any known Webull/ASX news timestamp field to ISO UTC string."""
        for key in ('newsTime', 'news_time', 'time', 'date', 'publishTime', 'createdTime'):
            val = item.get(key)
            if val:
                return val
        return ''

    def _news_age_text(self, item: Dict) -> str:
        """Return a human-readable age string like '2h ago', '3d ago', or the raw time if unparseable."""
        ts = self._parse_news_time(item)
        if not ts:
            return ''
        try:
            # Handle ISO 8601 with or without timezone, and some common formats
            ts_clean = str(ts).strip()
            parsed = date_parser.parse(ts_clean)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=dt_timezone.utc)
            now = datetime.now(dt_timezone.utc)
            delta = now - parsed
            total_seconds = max(0, int(delta.total_seconds()))
            if total_seconds < 60:
                return 'just now'
            if total_seconds < 3600:
                return f"{total_seconds // 60}m ago"
            if total_seconds < 86400:
                return f"{total_seconds // 3600}h ago"
            days = total_seconds // 86400
            if days < 30:
                return f"{days}d ago"
            if days < 365:
                return f"{days // 30}mo ago"
            return f"{days // 365}y ago"
        except Exception:
            # If we can't parse, still return the raw timestamp so the user sees it
            return str(ts)

    def _format_news_time(self, item: Dict) -> str:
        """Return a concise display time (age + raw date for older items)."""
        ts = self._parse_news_time(item)
        age = self._news_age_text(item)
        if not ts:
            return ''
        try:
            from dateutil import parser as date_parser
            parsed = date_parser.parse(str(ts))
            date_str = parsed.strftime('%d %b')
            if age:
                return f"{age} · {date_str}"
            return date_str
        except Exception:
            return age or str(ts)[:20]

    def score_headline(self, headline: str, body: str = "") -> Tuple[int, List[str]]:
        """
        Score a news item 0–5 based on catalyst keywords.
        Returns (score, matched_keywords).
        """
        text = f"{headline} {body}".lower()

        # Check red flags first
        for red in self.RED_FLAGS:
            if red in text:
                logger.warning("Red flag detected: '%s' in '%s'", red, headline)
                return -1, [red]  # Negative = avoid

        for score in sorted(self.CATALYST_KEYWORDS.keys(), reverse=True):
            for kw in self.CATALYST_KEYWORDS[score]:
                if kw in text:
                    return score, [kw]
        return 0, []

    def fetch_asx_announcements(self, tickers: List[str], items_per_page: int = 100) -> Dict[str, List[Dict]]:
        """Fetch today's ASX market announcements filtered to requested tickers.
        Returns {ticker: [announcement items]}.
        """
        if not tickers:
            return {}
        # API supports ?symbols=A,B,C (capitalised ASX codes)
        joined = ','.join(tickers)
        url = f"https://asx.api.markitdigital.com/asx-research/1.0/markets/announcements"
        params = {
            "symbols": joined,
            "itemsPerPage": max(items_per_page, 100),
            "summaryCountsDate": datetime.utcnow().strftime("%Y-%m-%d"),
            "includeFacets": "false",
        }
        try:
            resp = requests.get(url, params=params, timeout=20,
                                headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
            data = resp.json()
            items = data.get("data", {}).get("items", [])
            by_ticker: Dict[str, List[Dict]] = {t: [] for t in tickers}
            for item in items:
                sym = item.get("symbol") or ""
                if sym in by_ticker:
                    by_ticker[sym].append({
                        "title": item.get("headline", ""),
                        "source": "ASX Announcement",
                        "time": item.get("date", ""),
                        "url": item.get("url", ""),
                        "is_price_sensitive": item.get("isPriceSensitive", False),
                        "announcement_types": item.get("announcementTypes", []),
                    })
            return by_ticker
        except Exception as e:
            logger.warning("ASX announcements fetch failed: %s", e)
            return {}

    def analyze_ticker(self, ticker: str, ticker_id: int = None) -> Dict[str, Any]:
        """
        Fetch and analyze all news for a ticker, including ASX announcements when in AU market.
        Returns structured analysis.
        """
        news_items = self.fetch_webull_news(ticker, tId=ticker_id)
        # If configured for AU market, also fetch ASX announcements (ticker symbols are uppercase)
        if self.cfg.get('market', 'us').lower() == 'au':
            asx_ann = self.fetch_asx_announcements([ticker.upper()])
            # Flatten announcements into same format as Webull news
            for ann in asx_ann.get(ticker.upper(), []):
                news_items.append({
                    'title': ann.get('title', ''),
                    'content': '',
                    'source': 'ASX Announcement',
                    'time': ann.get('time', ''),
                    'url': ann.get('url', ''),
                })
        scored_items = []
        total_score = 0
        red_flags = []
        cutoff = datetime.now(dt_timezone.utc) - timedelta(days=self.MAX_NEWS_AGE_DAYS)

        for item in news_items:
            title = item.get('title', '')
            content = item.get('content', '')
            score, keywords = self.score_headline(title, content)

            if score == -1:
                red_flags.append({'title': title, 'flag': keywords[0]})
                continue

            display_time = self._format_news_time(item)
            raw_time = self._parse_news_time(item)

            # Skip stale items (> MAX_NEWS_AGE_DAYS) so the website doesn't show ancient news
            if raw_time:
                try:
                    p = date_parser.parse(str(raw_time))
                    if p.tzinfo is None:
                        p = p.replace(tzinfo=dt_timezone.utc)
                    if p < cutoff:
                        continue
                except Exception:
                    pass

            scored_items.append({
                'title': title,
                'source': item.get('source', 'Webull'),
                'time': display_time,
                'raw_time': raw_time,
                'url': item.get('url', ''),
                'score': score,
                'keywords': keywords
            })
            total_score += score

        # Sort by score desc, then by recency (raw_time descending)
        def _recency_key(item):
            try:
                t = item.get('raw_time', '')
                if not t:
                    return ''
                p = date_parser.parse(str(t))
                if p.tzinfo is None:
                    p = p.replace(tzinfo=dt_timezone.utc)
                return p.isoformat()
            except Exception:
                return ''
        scored_items.sort(key=lambda x: (x['score'], _recency_key(x)), reverse=True)

        # Determine overall catalyst rating
        high_scores = [i for i in scored_items if i['score'] >= self.min_score]
        all_sources = set(i['source'] for i in scored_items)
        unique_sources = len(set(i['source'] for i in high_scores))

        # Only require multiple unique sources if we actually fetched from multiple sources
        min_unique_sources = min(2, len(all_sources)) if all_sources else 1
        catalyst_confirmed = len(high_scores) >= self.min_sources and unique_sources >= min_unique_sources

        # Build human-readable reasons for inclusion or exclusion
        reasons = []
        if red_flags:
            reasons.append("news red flags")
        if catalyst_confirmed:
            reasons.append(f"catalyst confirmed ({len(high_scores)} items, score ≥{self.min_score})")
        elif not scored_items:
            reasons.append("no fresh news")
        else:
            reasons.append(f"low catalyst score (max {max((i['score'] for i in scored_items), default=0)}/5)")
        if red_flags:
            reasons.append(f"red flags: {', '.join(sorted({rf['flag'] for rf in red_flags}))}")
        exclusion_reason = "; ".join(reasons) if reasons else ""

        max_score = max((i['score'] for i in scored_items), default=0)
        # Red flags kill the headline score so the quality gate treats the ticker as low-impact.
        if red_flags and max_score < 2:
            max_score = 0

        return {
            'ticker': ticker,
            'total_items': len(news_items),
            'scored_items': scored_items,
            'headlines': scored_items,
            'red_flags': red_flags,
            'max_score': max_score,
            'avg_score': round(total_score / len(scored_items), 1) if scored_items else 0,
            'catalyst_confirmed': catalyst_confirmed,
            'high_impact_count': len(high_scores),
            'top_headline': scored_items[0]['title'] if scored_items else None,
            'news_filter_reason': exclusion_reason,
        }

    def analyze(self, ticker: str, ticker_id: int = None) -> Dict[str, Any]:
        """Compatibility alias for main.py which calls .analyze(ticker)."""
        return self.analyze_ticker(ticker, ticker_id=ticker_id)
