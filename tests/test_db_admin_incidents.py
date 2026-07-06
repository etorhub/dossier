"""Tests for app/db/admin.py get_incidents().

Uses real database when DATABASE_URL is set (e.g. in Docker).
Skips when no database available.
"""

import pytest

from app.db import admin as admin_db


def _has_db() -> bool:
    """Check if we can connect to the database."""
    try:
        conn = admin_db.get_connection()
        admin_db.return_connection(conn)
        return True
    except Exception:
        return False


def _insert_job_run(job_name: str, trigger: str, status: str = "success") -> int:
    conn = admin_db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO job_runs (job_name, status, trigger)
                VALUES (%s, %s, %s)
                RETURNING id
                """,
                (job_name, status, trigger),
            )
            row = cur.fetchone()
            assert row is not None
            job_id: int = row[0]
        conn.commit()
        return job_id
    finally:
        admin_db.return_connection(conn)


def _delete_job_runs(job_ids: list[int]) -> None:
    conn = admin_db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM job_runs WHERE id = ANY(%s)", (job_ids,))
        conn.commit()
    finally:
        admin_db.return_connection(conn)


@pytest.mark.skipif(not _has_db(), reason="Database not available")
def test_get_incidents_flags_frequent_scheduled_rewrites() -> None:
    """More than 2 scheduled rewrite_articles runs in 24h raises an incident —
    this is the exact failure mode where a missing config/app.yaml falls back
    to a fast dev cron and burns paid inference credits."""
    job_ids = [_insert_job_run("rewrite_articles", "scheduled") for _ in range(3)]
    try:
        incidents = admin_db.get_incidents({})
        anomalies = [i for i in incidents if i["type"] == "rewrite_frequency_anomaly"]
        assert len(anomalies) == 1
        assert "3 times" in anomalies[0]["title"]
        assert anomalies[0]["severity"] == "error"
    finally:
        _delete_job_runs(job_ids)


@pytest.mark.skipif(not _has_db(), reason="Database not available")
def test_get_incidents_no_anomaly_for_single_daily_rewrite() -> None:
    """A single scheduled rewrite run (the expected daily cadence) does not
    trigger the anomaly incident."""
    job_ids = [_insert_job_run("rewrite_articles", "scheduled")]
    try:
        incidents = admin_db.get_incidents({})
        anomalies = [i for i in incidents if i["type"] == "rewrite_frequency_anomaly"]
        assert anomalies == []
    finally:
        _delete_job_runs(job_ids)


@pytest.mark.skipif(not _has_db(), reason="Database not available")
def test_get_incidents_ignores_manual_rewrite_runs() -> None:
    """Manual/remote rewrite runs (trigger='manual') don't count toward the
    scheduled-frequency anomaly, since running the remote-rewrite script
    independently of the NAS's own 06:00 job is an expected, documented flow."""
    job_ids = [_insert_job_run("rewrite_articles", "manual") for _ in range(5)]
    try:
        incidents = admin_db.get_incidents({})
        anomalies = [i for i in incidents if i["type"] == "rewrite_frequency_anomaly"]
        assert anomalies == []
    finally:
        _delete_job_runs(job_ids)
