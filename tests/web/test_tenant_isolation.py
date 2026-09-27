import psycopg
import pytest

from app import db
from app.models import Job

KEY = "greenhouse:111"


def _seed_admin_job(pg_dsn) -> str:
    with psycopg.connect(pg_dsn) as conn:
        admin = db.get_user_by_username(conn, "admin")
        job = Job(key=KEY, title="T", url="https://ex.test/1", source_name="S", source_id="src-a")
        db.save_jobs(conn, [job], db.start_run(conn, user_id=admin["id"]), user_id=admin["id"])
        return admin["id"]


def _admin_row(pg_dsn, admin_id: str):
    with psycopg.connect(pg_dsn) as conn:
        return conn.execute(
            "SELECT status, removed_at, is_duplicate, location_override FROM jobs "
            "WHERE user_id = %s AND key = %s", (admin_id, KEY),
        ).fetchone()


@pytest.mark.parametrize("path,data", [
    ("/jobs/remove", {"key": KEY}),
    ("/jobs/status", {"key": KEY, "status": "applied"}),
    ("/jobs/duplicate", {"key": KEY}),
    ("/jobs/duplicate", {"key": KEY, "action": "clear"}),
    ("/jobs/location-override", {"key": KEY, "location": ""}),
], ids=["remove", "status", "dup", "undup", "clear-override"])
def test_member_cannot_mutate_another_users_job(member_client, pg_dsn, path, data):
    admin_id = _seed_admin_job(pg_dsn)
    before = _admin_row(pg_dsn, admin_id)
    resp = member_client.post(path, data=data, headers={"Accept": "application/json"})
    assert resp.status_code == 404
    assert _admin_row(pg_dsn, admin_id) == before


def test_member_clear_cache_leaves_other_users_jobs(member_client, pg_dsn):
    admin_id = _seed_admin_job(pg_dsn)
    resp = member_client.post("/settings/data/clear-cache", follow_redirects=False)
    assert resp.status_code == 303
    assert _admin_row(pg_dsn, admin_id) is not None
