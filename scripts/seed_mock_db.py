#!/usr/bin/env python3
"""Insert mocked articles, stories, and rewrites directly into PostgreSQL.

Unlike ``flask seed-sources`` / ``scripts/seed_dev_data.py`` (without
``--skip-sources``), this script does **not** populate ``news_sources`` or
``source_feeds``. It only writes content rows so you can exercise the app,
SQL, or the ops dashboard without running the fetch → embed → cluster →
rewrite pipeline.

The reader feed still matches stories using ``config/sources.yaml`` at runtime
(``load_sources()``). Mock articles must use ``source_id`` values that exist
there and share topics with the seeded user's ``user_topics``, or the feed
will stay empty.

Requires: migrations applied (``alembic upgrade head``), ``DATABASE_URL`` or
``POSTGRES_*`` env vars (see ``app.db.connection``).

**Running on the host (outside Docker)** while Postgres runs in Compose: publish
port ``5432`` (see ``docker-compose.override.yml``). Either omit
``DATABASE_URL`` and set ``POSTGRES_HOST=localhost`` (default when building
from ``POSTGRES_*``), or set e.g.
``DATABASE_URL=postgresql://dossier:PASSWORD@localhost:5432/dossier`` so the DB
name matches the container (``POSTGRES_DB``). If your ``.env`` uses a Docker
service hostname (e.g. ``@db:``), this script rewrites it to
``localhost`` unless ``DOSSIER_SKIP_DB_HOST_REMAP=1``.

Usage:
  python scripts/seed_mock_db.py
  python scripts/seed_mock_db.py --stories 5 --clear-mock
  MOCK_EMAIL=dev@localhost MOCK_PASSWORD=secret python scripts/seed_mock_db.py
  python scripts/seed_mock_db.py --skip-user --source-a 3cat --source-b vilaweb
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

MOCK_URL_BASE = "https://mock.dossier.invalid"

# Compose DB hostnames that only resolve on the Docker network.
_DOCKER_DB_HOST_ALIASES: tuple[str, ...] = ("db", "postgres")


def _configure_database_url_for_host_runner() -> None:
    """Point DATABASE_URL at localhost when .env still uses a Compose DB hostname."""
    if os.environ.get("DOSSIER_SKIP_DB_HOST_REMAP", "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        return
    url = os.environ.get("DATABASE_URL")
    if not url or not url.startswith("postgresql"):
        return
    for host in _DOCKER_DB_HOST_ALIASES:
        token = f"@{host}:"
        if token in url:
            new_url = url.replace(token, "@localhost:", 1)
            if new_url != url:
                os.environ["DATABASE_URL"] = new_url
                print(
                    "DATABASE_URL: remapped "
                    f"{host!r} → localhost (host-side seed). "
                    "Set DOSSIER_SKIP_DB_HOST_REMAP=1 to disable.",
                    file=sys.stderr,
                )
            return


def _article_id(source_id: str, url: str) -> str:
    return hashlib.sha256(f"{source_id}:{url}".encode()).hexdigest()[:16]


def _first_overlapping_source_pair(
    sources: list[dict[str, Any]],
) -> tuple[str, str, set[str]] | None:
    """Return (id_a, id_b, shared_topics) for two YAML sources with common topics."""
    for i, sa in enumerate(sources):
        ta = {t for t in (sa.get("topics") or []) if isinstance(t, str)}
        for sb in sources[i + 1 :]:
            tb = {t for t in (sb.get("topics") or []) if isinstance(t, str)}
            inter = ta & tb
            if inter:
                return (sa["id"], sb["id"], inter)
    if len(sources) >= 2:
        a, b = sources[0]["id"], sources[1]["id"]
        ta = set(sources[0].get("topics") or [])
        tb = set(sources[1].get("topics") or [])
        return (a, b, ta & tb or ta | tb)
    return None


def _ensure_dev_story(article_id_a: str, article_id_b: str) -> str | None:
    from app.db.stories import get_story_ids_for_articles, insert_story

    mapping = get_story_ids_for_articles([article_id_a, article_id_b])
    s_a = mapping.get(article_id_a)
    s_b = mapping.get(article_id_b)
    if s_a and s_b:
        if s_a == s_b:
            return s_a
        print(
            "Mock articles are attached to different stories; run with "
            "--clear-mock or fix the database.",
            file=sys.stderr,
        )
        return None
    if s_a or s_b:
        print(
            "Only one mock article is in a story; run with --clear-mock.",
            file=sys.stderr,
        )
        return None
    return insert_story([article_id_a, article_id_b])


def _ensure_user(email: str, password: str) -> int:
    import bcrypt

    from app.db import users as db_users

    existing = db_users.get_user_by_email(email)
    if existing:
        return int(existing["id"])
    password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    return db_users.create_user(email, password_hash)


def _ensure_profile_and_topics(user_id: int, topic_ids: list[str]) -> None:
    from app.db import users as db_users

    profile_data = {
        "location": "Local mock",
        "language": "ca",
        "high_contrast": False,
        "preferred_style": "neutral",
    }
    if db_users.get_profile(user_id):
        db_users.update_profile(user_id, profile_data)
    else:
        db_users.create_profile(user_id, profile_data)
    db_users.set_user_topics(user_id, topic_ids)


def clear_mock_rows(url_prefix: str) -> tuple[int, int]:
    """Remove stories tied to mock articles, then those articles. Returns counts."""
    from app.db.connection import get_connection, return_connection

    conn = get_connection()
    n_stories = 0
    n_articles = 0
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT sa.story_id
                FROM story_articles sa
                JOIN articles a ON a.id = sa.article_id
                WHERE a.url LIKE %s
                """,
                (f"{url_prefix}%",),
            )
            story_ids = [row[0] for row in cur.fetchall()]
            if story_ids:
                cur.execute(
                    "DELETE FROM stories WHERE id = ANY(%s)",
                    (story_ids,),
                )
                n_stories = cur.rowcount
            cur.execute(
                "DELETE FROM articles WHERE url LIKE %s",
                (f"{url_prefix}%",),
            )
            n_articles = cur.rowcount
        conn.commit()
    finally:
        return_connection(conn)
    return (n_stories, n_articles)


def seed_mock_db(
    *,
    num_stories: int,
    clear_mock: bool,
    skip_user: bool,
    sources_path: str | None,
    source_a: str | None,
    source_b: str | None,
) -> None:
    _configure_database_url_for_host_runner()

    from app.config import load_config, load_sources
    from app.db import articles as db_articles
    from app.db.stories import insert_story_rewrite
    from app.services import profile_service

    if clear_mock:
        removed_s, removed_a = clear_mock_rows(f"{MOCK_URL_BASE}/")
        print(f"Cleared mock data: {removed_s} stories, {removed_a} articles.")

    catalog = load_sources(sources_path)
    if not catalog:
        raise SystemExit("No sources in YAML — point --sources-path at a valid sources.yaml.")

    if source_a and source_b:
        ids = {s["id"] for s in catalog}
        if source_a not in ids or source_b not in ids:
            raise SystemExit(
                f"--source-a / --source-b must be ids present in sources.yaml "
                f"(got {source_a!r}, {source_b!r})."
            )
        ta = {
            t
            for t in next(s for s in catalog if s["id"] == source_a).get("topics", [])
            if isinstance(t, str)
        }
        tb = {
            t
            for t in next(s for s in catalog if s["id"] == source_b).get("topics", [])
            if isinstance(t, str)
        }
        topic_set = ta & tb or ta | tb or {"general"}
        sid_a, sid_b = source_a, source_b
    else:
        overlap = _first_overlapping_source_pair(catalog)
        if not overlap:
            raise SystemExit("Could not pick two sources from YAML; use --source-a and --source-b.")
        sid_a, sid_b, topic_set = overlap

    topic_list = sorted(topic_set) if topic_set else ["general"]
    if not skip_user:
        email = os.environ.get(
            "MOCK_EMAIL",
            os.environ.get("DEV_EMAIL", "dev@localhost"),
        )
        password = os.environ.get("MOCK_PASSWORD", os.environ.get("DEV_PASSWORD", "devpassword"))
        user_id = _ensure_user(email, password)
        _ensure_profile_and_topics(user_id, topic_list)
    else:
        user_id = None

    config = load_config()
    if user_id is not None:
        profile = profile_service.get_profile_with_selections(user_id)
        if not profile:
            raise RuntimeError("Profile missing after seed.")
        style, language = profile_service.get_reading_variant(profile, config)
    else:
        rewriting = config.get("rewriting", {})
        style = str(rewriting.get("default_style", "neutral"))
        language = str(rewriting.get("default_language", "ca"))

    now = datetime.now(UTC)
    story_ids_out: list[str] = []

    for i in range(num_stories):
        url_a = f"{MOCK_URL_BASE}/story-{i}/a"
        url_b = f"{MOCK_URL_BASE}/story-{i}/b"
        spec_a = {
            "title": f"[Mock {i}] Headline from source A",
            "url": url_a,
            "source_id": sid_a,
            "published_at": now,
            "raw_text": f"Mock RSS body A for story {i}.",
            "full_text": (
                f"Mock extracted article A for story {i}. "
                "Synthetic paragraph for clustering and reader tests."
            ),
            "categories": topic_list[:1] or ["general"],
        }
        spec_b = {
            "title": f"[Mock {i}] Related headline from source B",
            "url": url_b,
            "source_id": sid_b,
            "published_at": now,
            "raw_text": f"Mock RSS body B for story {i}.",
            "full_text": (
                f"Mock extracted article B for story {i}. "
                "Second synthetic paragraph with overlapping themes."
            ),
            "categories": topic_list[:2] if len(topic_list) > 1 else topic_list,
        }
        db_articles.insert_article(spec_a)
        db_articles.insert_article(spec_b)

        aid_a = _article_id(sid_a, url_a)
        aid_b = _article_id(sid_b, url_b)
        story_id = _ensure_dev_story(aid_a, aid_b)
        if not story_id:
            raise SystemExit(1)
        story_ids_out.append(story_id)

        title = f"[Mock {i}] Rewritten bundle (synthetic)"
        summary = f"Mock summary for story {i}: two synthetic sources merged for UI tests."
        full_text = (
            f"First paragraph of mock rewrite for story {i}.\n\n"
            "This text stands in for worker output; no LLM was called."
        )
        insert_story_rewrite(
            story_id,
            style,
            language,
            title=title,
            summary=summary,
            full_text=full_text,
            rewrite_failed=False,
            error_message=None,
        )

    print(
        f"Mock seed OK — {num_stories} stories "
        f"({sid_a!r} + {sid_b!r}), rewrite variant ({style!r}, {language!r})."
    )
    print(f"  Topics for user/profile: {topic_list}")
    if user_id is not None:
        login_email = os.environ.get(
            "MOCK_EMAIL",
            os.environ.get("DEV_EMAIL", "dev@localhost"),
        )
        print(f"  Log in as {login_email!r} (password MOCK_PASSWORD / DEV_PASSWORD or default).")
    print(f"  Story ids: {', '.join(story_ids_out)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stories",
        type=int,
        default=3,
        metavar="N",
        help="Number of two-article stories to create (default: 3)",
    )
    parser.add_argument(
        "--clear-mock",
        action="store_true",
        help=f"Delete existing rows whose URL starts with {MOCK_URL_BASE!r} first",
    )
    parser.add_argument(
        "--skip-user",
        action="store_true",
        help="Do not create or update a dev user (rewrites use app.yaml defaults)",
    )
    parser.add_argument(
        "--sources-path",
        default=None,
        help="Path to sources.yaml (default: config/sources.yaml)",
    )
    parser.add_argument(
        "--source-a",
        default=None,
        metavar="ID",
        help="First source_id (must exist in YAML); implies --source-b",
    )
    parser.add_argument(
        "--source-b",
        default=None,
        metavar="ID",
        help="Second source_id (must exist in YAML)",
    )
    args = parser.parse_args()

    if args.stories < 1:
        parser.error("--stories must be at least 1")
    if (args.source_a or args.source_b) and not (args.source_a and args.source_b):
        parser.error("Use both --source-a and --source-b together")

    seed_mock_db(
        num_stories=args.stories,
        clear_mock=args.clear_mock,
        skip_user=args.skip_user,
        sources_path=args.sources_path,
        source_a=args.source_a,
        source_b=args.source_b,
    )


if __name__ == "__main__":
    main()
