#!/usr/bin/env python3
"""Seed PostgreSQL with minimal data for local development.

Creates (idempotently):
  - Catalog rows from config/sources.yaml (same as ``flask seed-sources``)
  - A dev user with profile and topic selections
  - Two placeholder articles (distinct sources, overlapping topics)
  - One story linking those articles and a neutral Catalan rewrite

Requires: migrations applied (``alembic upgrade head``), DATABASE_URL or
POSTGRES_* env vars (see app.db.connection).

Usage:
  python scripts/seed_dev_data.py
  python scripts/seed_dev_data.py --skip-sources
  DEV_EMAIL=me@local.test DEV_PASSWORD=secret python scripts/seed_dev_data.py
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")


def _article_id(source_id: str, url: str) -> str:
    return hashlib.sha256(f"{source_id}:{url}".encode()).hexdigest()[:16]


def _ensure_dev_story(article_id_a: str, article_id_b: str) -> str | None:
    from app.db.stories import get_story_ids_for_articles, insert_story

    mapping = get_story_ids_for_articles([article_id_a, article_id_b])
    s_a = mapping.get(article_id_a)
    s_b = mapping.get(article_id_b)
    if s_a and s_b:
        if s_a == s_b:
            return s_a
        print(
            "Seed articles are attached to different stories; fix the DB or "
            "delete those rows, then re-run.",
            file=sys.stderr,
        )
        return None
    if s_a or s_b:
        print(
            "Only one seed article is in a story; fix the DB or remove "
            "orphan story links, then re-run.",
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
    password_hash = bcrypt.hashpw(
        password.encode("utf-8"), bcrypt.gensalt()
    ).decode("utf-8")
    return db_users.create_user(email, password_hash)


def _ensure_profile_and_topics(user_id: int) -> None:
    from app.db import users as db_users

    profile_data = {
        "location": "Barcelona",
        "language": "ca",
        "high_contrast": False,
        "preferred_style": "neutral",
    }
    if db_users.get_profile(user_id):
        db_users.update_profile(user_id, profile_data)
    else:
        db_users.create_profile(user_id, profile_data)
    db_users.set_user_topics(user_id, ["general", "politics"])


def seed_dev_data(*, skip_sources: bool, sources_path: str | None) -> None:
    from app.cli import run_seed_sources
    from app.config import load_config
    from app.db import articles as db_articles
    from app.db.stories import insert_story_rewrite
    from app.services import profile_service

    if not skip_sources:
        run_seed_sources(sources_path)

    email = os.environ.get("DEV_EMAIL", "dev@localhost")
    password = os.environ.get("DEV_PASSWORD", "devpassword")
    user_id = _ensure_user(email, password)
    _ensure_profile_and_topics(user_id)

    base = "https://invalid.invalid/dossier-dev"
    articles_spec: list[dict[str, object]] = [
        {
            "title": "[Dev] Placeholder — 3Cat",
            "url": f"{base}/3cat/sample",
            "source_id": "3cat",
            "published_at": datetime.now(UTC),
            "raw_text": "Placeholder raw text for local development.",
            "full_text": "Placeholder extracted text for local development.",
            "categories": ["general"],
        },
        {
            "title": "[Dev] Placeholder — Vilaweb",
            "url": f"{base}/vilaweb/sample",
            "source_id": "vilaweb",
            "published_at": datetime.now(UTC),
            "raw_text": "Placeholder raw text for local development.",
            "full_text": "Placeholder extracted text for local development.",
            "categories": ["general", "politics"],
        },
    ]
    for spec in articles_spec:
        db_articles.insert_article(spec)  # idempotent via ON CONFLICT

    aid_a = _article_id("3cat", str(articles_spec[0]["url"]))
    aid_b = _article_id("vilaweb", str(articles_spec[1]["url"]))

    story_id = _ensure_dev_story(aid_a, aid_b)
    if not story_id:
        raise SystemExit(1)

    config = load_config()
    profile = profile_service.get_profile_with_selections(user_id)
    if not profile:
        raise RuntimeError("Profile missing after seed; database may be misconfigured.")
    style, language = profile_service.get_reading_variant(profile, config)

    title = "[Dev] Notícia de prova per al desenvolupament local"
    summary = (
        "Resum de prova: dues fonts simulades agrupades en una història "
        "amb reescritura de demostració."
    )
    full_text = (
        "Aquest és el primer paràgraf de la reescritura de prova.\n\n"
        "El contingut real el generaria el worker amb el model; aquí només "
        "hi ha text estàtic per veure el lector i el fil sense executar "
        "la canonada."
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

    print(f"Dev seed OK — log in as {email!r} (password from DEV_PASSWORD or default)")
    print(f"  User id: {user_id}  Story id: {story_id}  Rewrite: ({style!r}, {language!r})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-sources",
        action="store_true",
        help="Do not run YAML → news_sources / source_feeds seeding",
    )
    parser.add_argument(
        "--sources-path",
        default=None,
        help="Path to sources.yaml (default: config/sources.yaml)",
    )
    args = parser.parse_args()
    seed_dev_data(skip_sources=args.skip_sources, sources_path=args.sources_path)


if __name__ == "__main__":
    main()
