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


def _seed_geocoded_admin_job(pg_dsn) -> None:
    with psycopg.connect(pg_dsn) as conn:
        conn.execute(
            "INSERT INTO geocoded_locations (location, display_name, region, status, lat, lng) "
            "VALUES ('Secret City, ZZ', 'Secret City, Zedland', 'Zedland', 'resolved', 1, 1)"
        )
        conn.commit()
        admin = db.get_user_by_username(conn, "admin")
        job = Job(key="lever:secret", title="T", url="https://ex.test/s", source_name="S",
                  source_id="src-a", location="Secret City, ZZ")
        db.save_jobs(conn, [job], db.start_run(conn, user_id=admin["id"]), user_id=admin["id"])


def test_member_filter_dropdowns_exclude_other_users_locations(member_client, pg_dsn):
    _seed_geocoded_admin_job(pg_dsn)
    for path in ("/jobs", "/jobs/map"):
        body = member_client.get(path).text
        assert "Secret City, Zedland" not in body
        assert "Zedland" not in body


def test_admin_filter_dropdowns_still_list_all_locations(client, pg_dsn):
    _seed_geocoded_admin_job(pg_dsn)
    assert "Secret City, Zedland" in client.get("/jobs").text


def test_admin_view_has_no_action_controls_on_other_users_rows(client, pg_dsn, member_user_id_for_admin):
    with psycopg.connect(pg_dsn) as conn:
        job = Job(key="lever:m1", title="Member Job", url="https://ex.test/m", source_name="S", source_id="src-m")
        db.save_jobs(conn, [job], db.start_run(conn, user_id=member_user_id_for_admin), user_id=member_user_id_for_admin)
    body = client.get("/jobs").text
    assert "Member Job" in body
    assert 'action="/jobs/remove"' not in body
    assert 'action="/jobs/status"' not in body


def test_admin_view_keeps_each_owners_history_separate(client, pg_dsn, admin_user_id, member_user_id_for_admin):
    with psycopg.connect(pg_dsn) as conn:
        for owner, status in ((admin_user_id, "applied"), (member_user_id_for_admin, "rejected")):
            job = Job(key="lever:shared", title="Shared", url="https://ex.test/x", source_name="S", source_id="src")
            db.save_jobs(conn, [job], db.start_run(conn, user_id=owner), user_id=owner)
            db.set_job_status(conn, owner, "lever:shared", status)
    body = client.get("/jobs").text
    assert body.count("Shared") >= 2
    # "Applied"/"Rejected" also appear in the status filter dropdown, so assert
    # against the per-row history markup rendered by jobs.html instead.
    assert body.count("<li>Applied &mdash;") == 1
    assert body.count("<li>Rejected &mdash;") == 1
