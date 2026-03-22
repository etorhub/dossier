# Location-Based News Source Discovery
## AI Agent Operational Document

> **Version 1.0 · All methods legal & ethical · Built for daily reliability**  
> *Internal Operational Document — For Agent Use Only*

---

## Table of Contents

1. [Purpose & Objectives](#1-purpose--objectives)
2. [Target Scope & Location Input](#2-target-scope--location-input)
3. [Discovery Pipeline](#3-discovery-pipeline)
4. [Source Quality Scoring](#4-source-quality-scoring)
5. [Consumption Method Detection](#5-consumption-method-detection)
6. [Database Schema](#6-database-schema)
7. [Legal & Ethical Framework](#7-legal--ethical-framework)
8. [Daily Ingestion Architecture](#8-daily-ingestion-architecture)
9. [Agent Execution Specification](#9-agent-execution-specification)
10. [Output & Monitoring](#10-output--monitoring)
11. [Quick-Start Checklist](#11-quick-start-checklist)

---

## 1. Purpose & Objectives

This document defines the full operational specification for an AI agent tasked with discovering, evaluating, and cataloguing location-based news sources across any country or region. The agent must operate strictly within legal and ethical boundaries, prioritizing source quality and reliability for daily news ingestion into a centralized database.

> **Mission Statement**  
> For a given geographic target (country, region, or city), the agent will autonomously discover all publicly accessible, legitimate news sources, determine how to consume them programmatically (API, RSS/Atom feed, scraping with consent), document them in a structured database schema, and verify daily reliability. No paywalled content extraction, no unauthorized scraping, no circumvention of access controls.

### 1.1 Core Goals

- Discover the maximum number of legitimate, high-quality news sources for a target location
- Identify the best programmatic consumption method for each source (API > RSS/Atom > official embed > scraping with robots.txt compliance)
- Populate a structured database with source metadata and ingestion instructions
- Ensure all sources can provide at least one new article per day reliably
- Stay fully compliant with copyright law, robots.txt, Terms of Service, and applicable data regulations (GDPR, CCPA, etc.)

### 1.2 Out of Scope

- Extracting full article body text behind paywalls
- Bypassing CAPTCHA or authentication mechanisms
- Scraping any source that explicitly disallows it via robots.txt or ToS
- Storing personally identifiable information from articles
- Re-publishing content without attribution

---

## 2. Target Scope & Location Input

### 2.1 Location Specification Schema

The agent accepts a structured location input object when triggered. This allows targeting at multiple geographic granularities:

```json
{
  "target": {
    "country_code": "ES",
    "country_name": "Spain",
    "region": "Catalonia",
    "city": "Barcelona",
    "languages": ["es", "ca", "en"],
    "scope": "national|regional|local",
    "include_international": true
  },
  "discovery_depth": "full",
  "update_existing": false
}
```

> **Field reference:** `country_code` uses ISO 3166-1 alpha-2. `languages` use ISO 639-1 codes. `scope` controls geographic granularity. `discovery_depth` controls how exhaustive the search is.

### 2.2 Discovery Depth Levels

| Depth | Sources Targeted | Est. Time |
|---|---|---|
| `quick` | Major nationals only (top 10) | ~2 min |
| `standard` | National + regional + major digital | ~10 min |
| `full` | All: national, regional, local, niche, aggregators | ~30 min |

---

## 3. Discovery Pipeline

### 3.1 Phase 1 — Seeded Reference Discovery

The agent begins with structured, trusted reference sources before doing any open web search. These sources are authoritative and reduce noise.

#### 3.1.1 Curated Reference Databases

| Source | URL | What It Provides |
|---|---|---|
| NewsAPI.org | https://newsapi.org/docs/endpoints/sources | Country-filtered list of sources with API access |
| GDELT Project | https://www.gdeltproject.org | Global media monitoring, country coverage metadata |
| ABYZ News Links | http://www.abyznewslinks.com | Human-curated directory by country |
| Mondo Times | http://www.mondotimes.com | Global newspaper directory by region |
| W3Newspapers | https://www.w3newspapers.com | Country/city newspaper index |
| Newspaper3k dataset | https://github.com/codelucas/newspaper | Source list used by the newspaper3k Python library |
| AllYouCanRead | https://www.allyoucanread.com | Magazines & newspapers by country |
| Reuters Institute | https://reutersinstitute.politics.ox.ac.uk | Annual Digital News Report with country source rankings |

#### 3.1.2 Country-Specific Registries

For each target country, check official press/media associations:

- **EU countries:** European Journalism Centre (EJC) media landscapes
- **US:** US Press Association directories, Newseum newspaper front pages
- **UK:** IPSO-regulated publications list
- **LatAm:** Periodistas de America directory
- **Asia:** Asia Media Forum country profiles
- **Africa:** African Media Initiative (AMI) directory

---

### 3.2 Phase 2 — Search-Based Discovery

The agent performs targeted web searches to surface sources not in static directories, especially newer digital-native outlets.

#### 3.2.1 Search Query Templates

```python
# Query generation — substitute {country}, {language}, {region}

QUERY_TEMPLATES = [
    "news sites in {country}",
    "best {language} news websites {country}",
    "{country} newspaper RSS feed",
    "online news portal {country} site:*.{country_tld}",
    "{region} local news RSS",
    "{country} media outlets API access",
    "site:github.com {country} news RSS feeds list",
    "{country} press freedom index top publications",
]

# Also query aggregator sources:
AGGREGATOR_QUERIES = [
    "filetype:opml {country} news feeds",
    "awesome {country} news datasets github",
    "feedly bundle {country} news",
]
```

#### 3.2.2 Search Engine Strategy

| Search Engine | Priority Use Case | Access Method |
|---|---|---|
| Bing Search API | Primary — reliable API, good intl coverage | API key (commercial tier) |
| SerpAPI / Serper.dev | Google results via proxy API | API key |
| DuckDuckGo | Fallback — no API needed, scraping-tolerant | HTML scraping (allowed per ToS) |
| Common Crawl Index | Batch domain discovery for a TLD | S3 API (free) |

---

### 3.3 Phase 3 — TLD & Domain Enumeration

Scan the country-code top-level domain (ccTLD) for news-related domains using publicly available zone files or Common Crawl data:

```python
# Use Common Crawl index to find all domains from a country TLD
# that contain news-like content (no scraping required — index is public)

import requests
import json

def query_common_crawl_for_news_domains(tld: str, year: str = '2024') -> list:
    index_url = f'https://index.commoncrawl.org/CC-MAIN-{year}-*-index'
    params = {
        'url': f'*.{tld}/news*',
        'output': 'json',
        'limit': 1000
    }
    r = requests.get(index_url, params=params)
    domains = set()
    for line in r.text.splitlines():
        d = json.loads(line)
        domains.add(d['url'].split('/')[2])
    return list(domains)
```

---

### 3.4 Phase 4 — Validation & Scoring

Every discovered candidate source must pass a multi-factor validation before database insertion:

| Validation Check | Method | Pass Criteria |
|---|---|---|
| Domain resolves | DNS + HTTP HEAD request | HTTP 200 within 5s |
| Content is news | Keyword match + meta tag check | news/article schema present |
| Language match | langdetect on homepage text | Matches target language(s) |
| robots.txt check | Fetch /robots.txt, parse | No `Disallow: /` for crawlers |
| ToS compliance | Check /terms for scraping prohibitions | No explicit scraping ban |
| Update frequency | Check Sitemap lastmod / RSS pubDate | At least 1 article/day |
| Feed availability | Try /feed, /rss, /atom, /sitemap.xml | Machine-readable feed found |
| HTTPS enabled | SSL cert check | Valid cert required |

---

## 4. Source Quality Scoring

Each source receives a composite quality score (0–100) used to prioritize ingestion and display ranking. The score is recalculated on first insert and refreshed monthly.

### 4.1 Scoring Dimensions

| Dimension | Weight | Measurement Method |
|---|---|---|
| Editorial Reputation | 25% | Reuters Inst. report, RSF press freedom index, Newsguard rating |
| Publication Frequency | 20% | Articles/day over last 30 days from feed |
| Consumption Method Quality | 20% | API=100, Official RSS=80, Sitemap=60, compliant scrape=40 |
| Feed Completeness | 15% | % of feed items with title + description + pubDate + link |
| HTTPS + Security | 10% | SSL grade via SSL Labs API |
| Geographic Relevance | 10% | % of articles geotagged or mentioning target region |

### 4.2 Score Calculation

```python
WEIGHTS: dict[str, float] = {
    "editorial_reputation": 0.25,
    "publication_frequency": 0.20,
    "consumption_method": 0.20,
    "feed_completeness": 0.15,
    "security": 0.10,
    "geo_relevance": 0.10,
}

CONSUMPTION_SCORES: dict[str, int] = {
    "json_api": 100,
    "rss": 80,
    "atom": 80,
    "sitemap": 60,
    "google_news_rss": 55,
    "scrape_structured": 40,
    "scrape_html": 20,
}


def calculate_quality_score(source: dict) -> float:
    scores = {
        "editorial_reputation": lookup_reputation_score(source["domain"]),
        "publication_frequency": min(source["articles_per_day"] / 10 * 100, 100),
        "consumption_method": CONSUMPTION_SCORES.get(source["feed_type"], 0),
        "feed_completeness": source["feed_completeness_pct"],
        "security": source["ssl_grade_score"],
        "geo_relevance": source["geo_relevance_pct"],
    }
    return sum(scores[key] * WEIGHTS[key] for key in WEIGHTS)
```

---

## 5. Consumption Method Detection

The agent must determine the best way to programmatically receive daily news updates from each source. Methods are tried in priority order.

### 5.1 Priority Order

1. Official REST/GraphQL API with news endpoint
2. Official RSS 2.0 or Atom feed
3. Google News RSS for the source domain (always available, no ToS issues)
4. XML Sitemap with `lastmod` dates (Google News sitemap standard)
5. robots.txt-compliant HTML scraping with structured data (`schema.org/NewsArticle`)

### 5.2 API Detection

```python
API_PATH_CANDIDATES = [
    '/api/news', '/api/v1/articles', '/api/latest',
    '/wp-json/wp/v2/posts',          # WordPress REST API
    '/api/v3/content',               # Common CMS patterns
    '/.well-known/openapi.json',     # OpenAPI spec
]

DEVELOPER_DOC_PATHS = [
    '/developers', '/api', '/developer',
    '/docs/api', '/api-docs', '/openapi.yaml'
]

def detect_api(base_url: str) -> dict | None:
    for path in API_PATH_CANDIDATES:
        resp = safe_get(base_url + path)
        if resp and resp.headers.get('Content-Type', '').startswith('application/json'):
            return {
                'type': 'json_api',
                'endpoint': base_url + path,
                'auth_required': resp.status_code == 401
            }
    return None
```

### 5.3 RSS/Atom Feed Detection

```python
FEED_PATH_CANDIDATES = [
    '/feed', '/rss', '/rss.xml', '/feed.xml', '/atom.xml',
    '/feeds/posts/default',   # Blogger
    '/?feed=rss2',            # WordPress
    '/news/rss.xml', '/en/rss.xml',
    '/sitemap_news.xml',      # Google News Sitemap
]

# Also parse HTML <link> tags for autodiscovery:
# <link rel="alternate" type="application/rss+xml" href="...">

# Fallback: Google News RSS (always legal, no ToS issue)
GOOGLE_NEWS_RSS = 'https://news.google.com/rss/search?q=site:{domain}&hl={lang}&gl={country}'
```

### 5.4 Google News as Universal Fallback

> **Note:** For any source that lacks its own feed or API, the agent can use Google News RSS filtered by the `site:` operator. This is fully legal, requires no scraping, and provides normalized metadata.  
> Format: `https://news.google.com/rss/search?q=site:DOMAIN&hl=LANG&gl=COUNTRY_CODE`  
> This should be the last resort after exhausting official feeds, but it is always a valid fallback.

---

## 6. Database Schema

All discovered sources and their ingestion metadata are inserted into the following PostgreSQL schema.

### 6.1 `news_sources` Table

```sql
CREATE TABLE news_sources (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    domain          VARCHAR(255) NOT NULL UNIQUE,
    name            VARCHAR(255) NOT NULL,
    description     TEXT,
    homepage_url    VARCHAR(500) NOT NULL,

    -- Geographic targeting
    country_code    CHAR(2) NOT NULL,          -- ISO 3166-1 alpha-2
    region          VARCHAR(100),               -- State / province
    city            VARCHAR(100),               -- City if local
    geo_scope       VARCHAR(20) NOT NULL,       -- 'national'|'regional'|'local'

    -- Languages (array of ISO 639-1 codes)
    languages       VARCHAR(10)[] NOT NULL,

    -- Quality & trust
    quality_score   DECIMAL(5,2),               -- 0.00–100.00
    is_verified     BOOLEAN DEFAULT FALSE,
    newsguard_rating CHAR(1),                   -- A/B/C/D/F if available
    rsf_listed      BOOLEAN DEFAULT FALSE,

    -- Status & lifecycle
    status          VARCHAR(20) DEFAULT 'active',  -- active|inactive|paused|banned
    last_checked_at TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
```

### 6.2 `source_feeds` Table

```sql
CREATE TABLE source_feeds (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id       UUID NOT NULL REFERENCES news_sources(id) ON DELETE CASCADE,

    -- Feed identification
    feed_type       VARCHAR(20) NOT NULL,
    -- 'rss' | 'atom' | 'json_api' | 'graphql' | 'sitemap'
    -- | 'google_news_rss' | 'scrape_structured' | 'scrape_html'

    feed_url        VARCHAR(1000) NOT NULL,
    feed_label      VARCHAR(100),               -- e.g. 'main', 'politics', 'local'

    -- API-specific
    api_key_required BOOLEAN DEFAULT FALSE,
    api_key_env_var  VARCHAR(100),              -- Env var name, e.g. 'REUTERS_API_KEY'
    api_rate_limit   INTEGER,                   -- Requests per day
    api_auth_type    VARCHAR(20),               -- 'bearer'|'apikey'|'oauth2'|'none'

    -- Pagination & polling
    supports_pagination BOOLEAN DEFAULT FALSE,
    pagination_param VARCHAR(50),               -- e.g. 'page', 'offset', 'cursor'
    poll_interval_minutes INTEGER DEFAULT 60,
    last_fetched_at  TIMESTAMPTZ,
    last_item_guid   VARCHAR(500),              -- Dedup anchor

    -- Feed health
    consecutive_failures INTEGER DEFAULT 0,
    avg_articles_per_day DECIMAL(6,2),
    feed_active      BOOLEAN DEFAULT TRUE,

    created_at      TIMESTAMPTZ DEFAULT NOW()
);
```

### 6.3 `source_discovery_log` Table

```sql
CREATE TABLE source_discovery_log (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id        UUID REFERENCES news_sources(id),
    discovery_run_id UUID NOT NULL,
    target_location  JSONB NOT NULL,            -- Input location object
    discovery_method VARCHAR(50),               -- 'directory'|'search'|'tld_scan'|'manual'
    validation_result JSONB,                    -- Full validation check results
    rejected_reason  TEXT,
    created_at       TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for common queries
CREATE INDEX idx_ns_country   ON news_sources(country_code);
CREATE INDEX idx_ns_region    ON news_sources(country_code, region);
CREATE INDEX idx_ns_quality   ON news_sources(quality_score DESC);
CREATE INDEX idx_sf_source    ON source_feeds(source_id);
CREATE INDEX idx_sf_poll      ON source_feeds(last_fetched_at) WHERE feed_active = TRUE;
```

---

## 7. Legal & Ethical Framework

> ⚠️ **Non-Negotiable Constraints**  
> Every action taken by the agent must comply with the following rules. These are hard limits, not optional optimizations. Any source that cannot be consumed within these constraints must be marked as `status='banned'` in the database rather than worked around.

### 7.1 robots.txt Compliance

```python
# robots.txt must be checked before ANY HTTP request to a domain
from urllib.robotparser import RobotFileParser
import time

def is_scraping_allowed(domain: str, path: str, user_agent: str = '*') -> bool:
    rp = RobotFileParser()
    rp.set_url(f'https://{domain}/robots.txt')
    try:
        rp.read()    # Respect crawl-delay directive too
        crawl_delay = rp.crawl_delay(user_agent)
        if crawl_delay:
            time.sleep(crawl_delay)
        return rp.can_fetch(user_agent, f'https://{domain}{path}')
    except Exception:
        return False  # If robots.txt unreachable, assume disallowed
```

### 7.2 Terms of Service Checks

- Before indexing a source, fetch `/terms`, `/terms-of-service`, `/legal`, `/tos`
- Use NLP keyword detection for phrases: `no scraping`, `no automated access`, `no crawling`, `no data mining`, `prohibit bots`
- If any prohibition is found: mark source as `status='banned'`, log reason, skip all feed attempts
- If ToS page is unavailable: proceed with robots.txt compliance only, flag for human review

### 7.3 Copyright & Reproduction Rules

- **During discovery**, the agent collects only: source domain, name, homepage URL, feed URLs, geographic metadata, and quality scores. No article content is fetched during the discovery phase.
- **During daily ingestion** (handled by the fetching pipeline, not discovery), the app stores article metadata (title, URL, pubDate, author, description) and full article text **when the source provides it openly** via RSS `<content:encoded>` or API response. Full text is only stored from open publishers — never extracted from behind paywalls.
- All stored content is attributed to the original source with canonical URL preserved
- Content is rewritten as a reading aid, not republished verbatim — every article links to the original

### 7.4 Rate Limiting

```python
RATE_LIMIT_DEFAULTS = {
    'min_delay_between_requests_ms': 2000,   # 2 seconds between requests to same domain
    'max_requests_per_domain_per_hour': 60,
    'respect_retry_after_header': True,
    'backoff_on_429': True,
    'backoff_multiplier': 2.0,
    'max_backoff_seconds': 3600,
}

# For RSS/feed polling:  once per poll_interval_minutes (default: 60 min)
# For initial discovery: once per source (no repeat within 24h)
# For API endpoints:     strictly respect the documented rate limit
```

### 7.5 Data Regulation Compliance

| Regulation | Applicable Region | Key Requirement |
|---|---|---|
| GDPR | EU/EEA | No storage of personal data from articles; lawful basis for processing |
| CCPA | California, USA | No sale of collected data; honor opt-out signals |
| NetzDG | Germany | Platform-specific content rules for German sources |
| DPDPA 2023 | India | Personal data minimization for Indian sources |
| PIPL | China | Data localization requirements if processing CN data |

---

## 8. Daily Ingestion Architecture

Once sources are in the database, the daily ingestion pipeline consumes them on a schedule. The following describes how the feed layer should operate.

### 8.1 Polling Schedule

```python
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

POLL_SCHEDULES = {
    # Sources publishing >50 articles/day
    "high_frequency": {
        "cron": "*/15 * * * *",  # Every 15 minutes
        "query": "SELECT * FROM source_feeds WHERE avg_articles_per_day > 50",
    },
    # Sources publishing 5–50 articles/day
    "medium_frequency": {
        "cron": "0 * * * *",  # Every hour
        "query": "SELECT * FROM source_feeds WHERE avg_articles_per_day BETWEEN 5 AND 50",
    },
    # Sources publishing <5 articles/day
    "low_frequency": {
        "cron": "0 6,12,18 * * *",  # 3x per day
        "query": "SELECT * FROM source_feeds WHERE avg_articles_per_day < 5",
    },
    # Health check for all active feeds
    "health_check": {
        "cron": "0 0 * * *",  # Daily at midnight
        "action": "verify_feed_still_active",
    },
}


def register_poll_jobs(scheduler: BackgroundScheduler) -> None:
    for tier, config in POLL_SCHEDULES.items():
        if "action" in config:
            scheduler.add_job(verify_feed_health, CronTrigger.from_crontab(config["cron"]))
        else:
            scheduler.add_job(
                poll_feeds_tier,
                CronTrigger.from_crontab(config["cron"]),
                args=[config["query"]],
                id=f"poll_{tier}",
            )
```

### 8.2 Feed Fetch & Parse Flow

```python
import feedparser
import httpx

from app.db import articles as articles_db


def ingest_feed(feed: dict) -> dict:
    """Fetch a single feed and store new articles."""
    # 1. Rate limit check
    rate_limiter.wait(feed["domain"])

    # 2. Conditional GET (use ETag / Last-Modified to avoid re-processing)
    headers: dict[str, str] = {}
    if feed.get("last_etag"):
        headers["If-None-Match"] = feed["last_etag"]
    if feed.get("last_modified"):
        headers["If-Modified-Since"] = feed["last_modified"]

    resp = httpx.get(feed["feed_url"], headers=headers, timeout=15)
    if resp.status_code == 304:
        return {"new_items": 0, "status": "not_modified"}

    # 3. Parse feed
    parsed = feedparser.parse(resp.text)

    # 4. Deduplicate against last_item_guid + DB check
    new_items = [
        entry for entry in parsed.entries
        if entry.get("id") != feed.get("last_item_guid")
        and not articles_db.exists_by_source_and_url(feed["source_id"], entry.link)
    ]

    # 5. Store article metadata + full text when available
    for item in new_items:
        full_text = item.get("content", [{}])[0].get("value") if item.get("content") else None
        articles_db.insert({
            "source_id": feed["source_id"],
            "title": item.get("title", ""),
            "url": item.link,
            "published_at": item.get("published"),
            "raw_text": (item.get("summary") or "")[:500],
            "full_text": full_text,
            "guid": item.get("id"),
        })

    return {"new_items": len(new_items), "status": "ok"}
```

### 8.3 Failure Handling & Circuit Breaker

```python
CIRCUIT_BREAKER_THRESHOLDS = {
    'soft_fail_count':          3,   # After 3 consecutive failures: log warning
    'hard_fail_count':         10,   # After 10: set feed_active=FALSE
    'alert_threshold':          5,   # After 5: send alert to monitoring
    'retry_dormant_after_days': 7    # Re-try disabled feeds after 7 days
}

# Error classification:
# HTTP 429 / 503  →  Backoff, do NOT count as failure
# HTTP 404        →  Feed URL changed; trigger re-discovery
# HTTP 401/403    →  ToS violation suspected; flag for review
# Timeout         →  Count as failure, exponential backoff
# Parse error     →  Count as failure, check for format change
```

---

## 9. Agent Execution Specification

### 9.1 Agent Pseudocode

```python
import asyncio
import uuid
import logging
from typing import Any

logger = logging.getLogger(__name__)


async def discover_news_sources(location: dict) -> None:
    run_id = uuid.uuid4()
    logger.info("Discovery run %s started for %s", run_id, location)

    # PHASE 1: Reference databases (parallel)
    phase1_results = await asyncio.gather(
        query_newsapi(location),
        query_abyz_directory(location),
        query_gdelt(location),
        query_w3newspapers(location),
    )
    candidates_p1 = [src for batch in phase1_results for src in batch]

    # PHASE 2: Web search discovery
    candidates_p2: list[dict[str, Any]] = []
    for query in generate_search_queries(location):
        results = await search_engine.search(query)
        candidates_p2.extend(extract_domains(results))
        await asyncio.sleep(1.5)  # Rate limiting

    # PHASE 3: TLD scan (only for 'full' depth)
    candidates_p3: list[dict[str, Any]] = []
    if location.get("discovery_depth") == "full":
        candidates_p3 = await scan_country_tld(location["country_code"])

    # Deduplicate
    all_candidates = deduplicate(candidates_p1 + candidates_p2 + candidates_p3)

    # PHASE 4: Validate & score each candidate
    validated: list[dict[str, Any]] = []
    for candidate in all_candidates:
        result = await validate_source(candidate)
        await log_discovery(run_id, result)
        if result["passed"]:
            validated.append(result)

    # PHASE 5: Detect feeds + calculate quality scores
    for source in validated:
        source["feeds"] = await detect_feeds(source)
        source["quality_score"] = calculate_quality_score(source)

    # PHASE 6: Upsert into database
    await db.upsert_sources(validated)
    logger.info(
        "Discovery run %s complete: %d candidates, %d inserted",
        run_id, len(all_candidates), len(validated),
    )
```

### 9.2 Required Environment Variables

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | Yes | PostgreSQL connection string (e.g. `postgresql://dossier:pass@db:5432/dossier`) |
| `BING_SEARCH_API_KEY` | Recommended | Microsoft Bing Search v7 API key |
| `SERPAPI_KEY` | Optional | SerpAPI key for Google result fallback |
| `NEWSAPI_KEY` | Recommended | NewsAPI.org key for source directory queries |
| `NEWSGUARD_API_KEY` | Optional | NewsGuard reputation scores API |
| `LOG_LEVEL` | No (default: `info`) | Logging verbosity: `debug\|info\|warn\|error` |
| `RATE_LIMIT_MS` | No (default: `2000`) | Milliseconds between same-domain requests |

---

## 10. Output & Monitoring

### 10.1 Discovery Run Report

After each discovery run, the agent generates a structured report and inserts a summary row into the discovery log. Key metrics:

- Total candidates found across all phases
- Breakdown: passed validation / rejected (with reason distribution)
- New sources inserted vs. updated vs. skipped (already known)
- Feed type distribution: API / RSS / Sitemap / Google News fallback / None
- Average quality score for inserted sources
- Sources flagged for human review (ToS ambiguity, unusual access patterns)

### 10.2 Health Monitoring Queries

```sql
-- Sources due for re-validation (not checked in 30 days)
SELECT id, domain, quality_score, last_checked_at
FROM news_sources
WHERE last_checked_at < NOW() - INTERVAL '30 days'
  AND status = 'active'
ORDER BY quality_score DESC;

-- Feeds with consecutive failures > 3
SELECT sf.feed_url, ns.domain, sf.consecutive_failures, sf.last_fetched_at
FROM source_feeds sf
JOIN news_sources ns ON ns.id = sf.source_id
WHERE sf.consecutive_failures > 3 AND sf.feed_active = TRUE;

-- Coverage by country
SELECT country_code,
       COUNT(*) AS total_sources,
       AVG(quality_score)::DECIMAL(5,2) AS avg_quality,
       SUM(CASE WHEN status='active' THEN 1 ELSE 0 END) AS active
FROM news_sources
GROUP BY country_code
ORDER BY total_sources DESC;
```

---

## 11. Quick-Start Checklist

Use this checklist before first deployment:

1. Set all required environment variables (`DATABASE_URL`, `BING_SEARCH_API_KEY`, `NEWSAPI_KEY`)
2. Run database migrations to create `news_sources`, `source_feeds`, `source_discovery_log` tables
3. Test robots.txt parser module against 5 known domains before enabling scraping module
4. Configure rate limiter with conservative defaults (2000ms delay) before first run
5. Run a `quick` depth discovery on one known country to verify pipeline end-to-end
6. Review the `rejected_reason` distribution from the first run log
7. Enable the daily polling cron jobs only after verifying at least 10 valid feeds
8. Set up monitoring alerts for `consecutive_failures > 5` on active feeds
9. Schedule monthly `quality_score` recalculation and source re-validation jobs
10. Document any country-specific legal requirements not covered in this spec (e.g. Chinese sources, Russian sources)

---

*This document is intended for AI agent operation only. All discovery methods described are designed to be fully legal and ethical. Review with legal counsel if deploying in jurisdictions with specific web-crawling or data-collection regulations.*
