import logging
from typing import List, Optional, Dict, Any
import httpx
from cachetools import TTLCache

from app.core.config import settings

logger = logging.getLogger(__name__)

# Cache trending results for 1 hour to avoid rate limits
_trends_cache: TTLCache = TTLCache(maxsize=100, ttl=3600)


class TrendingContentService:
    """Aggregates trending topics from Google Trends, LinkedIn (via RapidAPI), and URL metadata."""

    # -----------------------------------------------------------------------
    # Google Trends (via pytrends)
    # -----------------------------------------------------------------------

    async def get_google_trends(
        self,
        keywords: List[str],
        timeframe: str = "now 7-d",
        geo: str = "US",
    ) -> List[Dict[str, Any]]:
        """Return trending interest data for keywords from Google Trends."""
        cache_key = f"google:{','.join(keywords)}:{timeframe}:{geo}"
        if cache_key in _trends_cache:
            return _trends_cache[cache_key]

        try:
            from pytrends.request import TrendReq
            pytrends = TrendReq(hl="en-US", tz=360)
            pytrends.build_payload(keywords[:5], cat=0, timeframe=timeframe, geo=geo)
            data = pytrends.interest_over_time()

            if data.empty:
                result = []
            else:
                result = []
                for kw in keywords:
                    if kw in data.columns:
                        avg_interest = int(data[kw].mean())
                        peak_interest = int(data[kw].max())
                        result.append({
                            "keyword": kw,
                            "avg_interest": avg_interest,
                            "peak_interest": peak_interest,
                            "source": "google_trends",
                            "timeframe": timeframe,
                            "geo": geo,
                        })

            _trends_cache[cache_key] = result
            return result

        except ImportError:
            logger.warning("pytrends not installed. Run: pip install pytrends")
            return []
        except Exception as e:
            logger.warning(f"Google Trends error: {e}")
            return []

    # -----------------------------------------------------------------------
    # LinkedIn Trending via RapidAPI
    # -----------------------------------------------------------------------

    async def get_linkedin_trending(self, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetch LinkedIn trending posts via RapidAPI."""
        if not settings.RAPIDAPI_KEY:
            return []

        cache_key = f"linkedin_trending:{category}"
        if cache_key in _trends_cache:
            return _trends_cache[cache_key]

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                params = {}
                if category:
                    params["category"] = category

                resp = await client.get(
                    "https://linkedin-data-api.p.rapidapi.com/get-trending-feed",
                    headers={
                        "X-RapidAPI-Key": settings.RAPIDAPI_KEY,
                        "X-RapidAPI-Host": settings.RAPIDAPI_LINKEDIN_TRENDS_HOST,
                    },
                    params=params,
                )

                if resp.status_code != 200:
                    logger.warning(f"LinkedIn trends API returned {resp.status_code}")
                    return []

                data = resp.json()
                items = data.get("data", data) if isinstance(data, dict) else data
                result = []
                for item in (items[:20] if isinstance(items, list) else []):
                    result.append({
                        "title": item.get("title") or item.get("text", "")[:100],
                        "url": item.get("url") or item.get("postUrl", ""),
                        "engagement": item.get("totalReactionCount") or item.get("engagement", 0),
                        "author": item.get("author", {}).get("fullName") if isinstance(item.get("author"), dict) else "",
                        "source": "linkedin",
                    })

                _trends_cache[cache_key] = result
                return result

        except Exception as e:
            logger.warning(f"LinkedIn trends error: {e}")
            return []

    # -----------------------------------------------------------------------
    # LinkedIn Post Search via RapidAPI
    # -----------------------------------------------------------------------

    async def search_linkedin_posts(
        self,
        access_token: str,
        keyword: str,
        sort_by: str = "RECENCY",  # RECENCY | RELEVANCE
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Search LinkedIn posts by hashtag using the official LinkedIn API (Community Management API).

        Uses the connected LinkedIn SocialAccount's OAuth token.
        Requires w_member_social scope (already requested during OAuth connect).
        Note: hashtag post search may require LinkedIn partner review for production volumes.
        """
        # Convert keyword to a hashtag URN (spaces → remove, lowercase)
        hashtag = keyword.lower().replace(" ", "").replace("#", "")
        hashtag_urn = f"urn:li:hashtag:{hashtag}"

        cache_key = f"linkedin_official:{hashtag}:{sort_by}"
        if cache_key in _trends_cache:
            return _trends_cache[cache_key]

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    "https://api.linkedin.com/rest/posts",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "LinkedIn-Version": "202502",
                        "X-Restli-Protocol-Version": "2.0.0",
                    },
                    params={
                        "q": "hashtag",
                        "hashtag": hashtag_urn,
                        "count": min(limit, 50),
                        "sortBy": sort_by,
                    },
                )

                if resp.status_code == 401:
                    raise ValueError("LinkedIn token expired. Please reconnect your LinkedIn account in Social Accounts settings.")

                if resp.status_code == 403:
                    raise ValueError(
                        "LinkedIn post search requires additional API permissions. "
                        "Your app has been submitted for review — this feature will be enabled once approved."
                    )

                if resp.status_code == 422:
                    raise ValueError(f"Invalid hashtag or search parameters for keyword '{keyword}'.")

                if resp.status_code == 404:
                    logger.warning(f"LinkedIn official search returned 404 (RESOURCE_NOT_FOUND): {resp.text[:300]}")
                    raise ValueError("RESOURCE_NOT_FOUND: LinkedIn hashtag post search requires Community Management API (under review).")

                if resp.status_code != 200:
                    logger.warning(f"LinkedIn official search returned {resp.status_code}: {resp.text[:300]}")
                    raise ValueError(f"LinkedIn API returned {resp.status_code}. Check that your LinkedIn account is connected.")

                data = resp.json()
                elements = data.get("elements", [])

                result = []
                for item in elements[:limit]:
                    # Extract post text (commentary field in LinkedIn REST API)
                    commentary = ""
                    content_obj = item.get("content") or {}
                    if isinstance(item.get("commentary"), str):
                        commentary = item["commentary"]
                    elif isinstance(content_obj, dict):
                        commentary = content_obj.get("article", {}).get("description", "") or ""

                    # Build post URL from URN
                    post_urn = item.get("id", "")
                    post_url = ""
                    if post_urn:
                        urn_id = post_urn.split(":")[-1]
                        post_url = f"https://www.linkedin.com/feed/update/{post_urn}"

                    # Engagement stats
                    social = item.get("socialDetail") or {}
                    likes = (social.get("likesSummary") or {}).get("totalLikes", 0)
                    comments = (social.get("commentsSummary") or {}).get("totalFirstLevelComments", 0)
                    reshares = (social.get("resharesSummary") or {}).get("totalShares", 0)

                    result.append({
                        "title": commentary[:300],
                        "url": post_url,
                        "author": item.get("author", ""),
                        "author_avatar": "",
                        "author_headline": "",
                        "engagement": likes,
                        "comments": comments,
                        "reposts": reshares,
                        "image": "",
                        "posted_at": str(item.get("createdAt", "")),
                        "source": "linkedin_official",
                    })

                _trends_cache[cache_key] = result
                return result

        except ValueError:
            raise
        except Exception as e:
            logger.warning(f"LinkedIn official post search error: {e}")
            raise ValueError(f"LinkedIn search failed: {e}")

    # -----------------------------------------------------------------------
    # Hacker News — free, no API key required
    # -----------------------------------------------------------------------

    async def get_hackernews_trending(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Fetch top stories from Hacker News API (no key required)."""
        cache_key = "hackernews_top"
        if cache_key in _trends_cache:
            return _trends_cache[cache_key]

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get("https://hacker-news.firebaseio.com/v0/topstories.json")
                if resp.status_code != 200:
                    return []
                ids = resp.json()[:limit]

                import asyncio
                async def fetch_story(sid: int) -> Optional[Dict]:
                    r = await client.get(f"https://hacker-news.firebaseio.com/v0/item/{sid}.json")
                    return r.json() if r.status_code == 200 else None

                stories = await asyncio.gather(*[fetch_story(sid) for sid in ids])

            result = []
            for s in stories:
                if not s or s.get("type") != "story":
                    continue
                result.append({
                    "title": s.get("title", ""),
                    "url": s.get("url", f"https://news.ycombinator.com/item?id={s.get('id')}"),
                    "engagement": s.get("score", 0),
                    "author": s.get("by", ""),
                    "source": "hackernews",
                })

            _trends_cache[cache_key] = result
            return result

        except Exception as e:
            logger.warning(f"Hacker News trending error: {e}")
            return []

    # -----------------------------------------------------------------------
    # Google News RSS — free, no API key required
    # -----------------------------------------------------------------------

    async def get_google_news_rss(self, query: str = "business technology", limit: int = 20) -> List[Dict[str, Any]]:
        """Fetch trending news from Google News RSS (no key required)."""
        import re
        cache_key = f"google_news:{query}"
        if cache_key in _trends_cache:
            return _trends_cache[cache_key]

        try:
            encoded = query.replace(" ", "+")
            url = f"https://news.google.com/rss/search?q={encoded}&hl=en-US&gl=US&ceid=US:en"
            async with httpx.AsyncClient(
                timeout=15,
                headers={"User-Agent": "Mozilla/5.0 (compatible; HeyGenAlly/1.0)"},
                follow_redirects=True,
            ) as client:
                resp = await client.get(url)
                if resp.status_code != 200:
                    return []
                xml = resp.text

            items = re.findall(r"<item>(.*?)</item>", xml, re.DOTALL)
            result = []
            for item in items[:limit]:
                title_m = re.search(r"<title>(.*?)</title>", item, re.DOTALL)
                link_m = re.search(r"<link>(.*?)</link>", item, re.DOTALL)
                source_m = re.search(r"<source[^>]*>(.*?)</source>", item, re.DOTALL)
                title = re.sub(r"<[^>]+>", "", title_m.group(1)).strip() if title_m else ""
                link = link_m.group(1).strip() if link_m else ""
                source = source_m.group(1).strip() if source_m else "Google News"
                if title:
                    result.append({
                        "title": title,
                        "url": link,
                        "engagement": 0,
                        "author": source,
                        "source": "google_news",
                    })

            _trends_cache[cache_key] = result
            return result

        except Exception as e:
            logger.warning(f"Google News RSS error: {e}")
            return []

    # -----------------------------------------------------------------------
    # URL Metadata Extraction
    # -----------------------------------------------------------------------

    async def extract_post_metadata(self, url: str) -> Dict[str, Any]:
        """Fetch a URL and extract Open Graph / meta tags for AI context."""
        try:
            async with httpx.AsyncClient(
                timeout=10,
                follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0 (compatible; HeyGenAlly/1.0)"},
            ) as client:
                resp = await client.get(url)
                if resp.status_code != 200:
                    return {"url": url, "title": "", "description": "", "image": ""}

                html = resp.text

            # Parse Open Graph tags without requiring lxml
            import re

            def _meta(prop: str) -> str:
                pattern = rf'<meta[^>]+(?:property|name)=["\'](?:og:)?{prop}["\'][^>]+content=["\'](.*?)["\']'
                m = re.search(pattern, html, re.IGNORECASE)
                if m:
                    return m.group(1).strip()
                # Also try content-first order
                pattern2 = rf'<meta[^>]+content=["\'](.*?)["\'][^>]+(?:property|name)=["\'](?:og:)?{prop}["\']'
                m2 = re.search(pattern2, html, re.IGNORECASE)
                return m2.group(1).strip() if m2 else ""

            title = _meta("title") or _meta("og:title")
            description = _meta("description") or _meta("og:description")
            image = _meta("image") or _meta("og:image")

            # Fallback: grab <title> tag
            if not title:
                tm = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
                title = tm.group(1).strip() if tm else ""

            # Extract readable body text: strip tags, collapse whitespace
            body_html = re.sub(r'<(script|style|nav|header|footer|aside|form)[^>]*>.*?</\1>', '', html, flags=re.DOTALL | re.IGNORECASE)
            body_text = re.sub(r'<[^>]+>', ' ', body_html)
            body_text = re.sub(r'&[a-z]+;', ' ', body_text)
            body_text = re.sub(r'\s{2,}', '\n', body_text).strip()
            # Keep first ~3000 chars of meaningful text
            body_text = body_text[:3000]

            return {
                "url": url,
                "title": title[:300],
                "description": description[:500],
                "image": image,
                "body_text": body_text,
            }

        except Exception as e:
            logger.warning(f"URL metadata extraction failed for {url}: {e}")
            return {"url": url, "title": "", "description": "", "image": ""}
