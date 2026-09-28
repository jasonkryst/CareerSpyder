import pytest

from app import checker, db, orchestrator
from app.models import Job

KEY = "greenhouse:1"


def _job(key: str = KEY, source_id: str = "src") -> Job:
    return Job(key=key, title="Engineer", url=f"https://boards.example/{key}",
               source_name="Acme", source_id=source_id)


@pytest.fixture
def two_users(pg_conn):
    alice = db.create_user(pg_conn, "alice", "alice@test.local", "x")
    bob = db.create_user(pg_conn, "bob", "bob@test.local", "x")
    return alice["id"], bob["id"]


def _save(conn, user_id: str, job: Job | None = None) -> None:
    db.save_jobs(conn, [job or _job()], db.start_run(conn, user_id=user_id), user_id=user_id)


def test_same_job_key_is_saved_once_per_user(pg_conn, two_users):
    alice, bob = two_users
    _save(pg_conn, alice)
    assert db.get_new_jobs(pg_conn, bob, [_job()]) == [_job()]
    _save(pg_conn, bob)
    count = pg_conn.execute("SELECT COUNT(*) FROM jobs WHERE key = %s", (KEY,)).fetchone()[0]
    assert count == 2


def test_reconcile_for_one_user_leaves_other_users_jobs_active(pg_conn, two_users):
    alice, bob = two_users
    _save(pg_conn, bob, _job(source_id="src-bob"))
    db.reconcile_jobs(pg_conn, alice, set(), set(), [])
    removed_at = pg_conn.execute("SELECT removed_at FROM jobs WHERE user_id = %s", (bob,)).fetchone()[0]
    assert removed_at is None


def test_run_once_for_one_user_leaves_other_users_jobs_active(pg_conn, two_users, monkeypatch):
    alice, bob = two_users
    monkeypatch.setattr(orchestrator, "geocode_pending", lambda *args, **kwargs: None)
    _save(pg_conn, bob, _job(source_id="src-bob"))
    orchestrator.run_once(pg_conn, [], user_id=alice)
    removed_at = pg_conn.execute("SELECT removed_at FROM jobs WHERE user_id = %s", (bob,)).fetchone()[0]
    assert removed_at is None


@pytest.mark.parametrize("mutate", [
    lambda conn, uid: db.mark_job_removed(conn, uid, KEY),
    lambda conn, uid: db.set_job_status(conn, uid, KEY, "applied"),
    lambda conn, uid: db.set_job_duplicate(conn, uid, KEY),
    lambda conn, uid: db.clear_job_duplicate(conn, uid, KEY),
    lambda conn, uid: db.clear_location_override(conn, uid, KEY),
], ids=["remove", "status", "dup", "undup", "clear-override"])
def test_job_mutations_by_a_non_owner_raise_keyerror(pg_conn, two_users, mutate):
    alice, bob = two_users
    _save(pg_conn, alice)
    with pytest.raises(KeyError):
        mutate(pg_conn, bob)
    row = pg_conn.execute(
        "SELECT status, removed_at, is_duplicate FROM jobs WHERE user_id = %s AND key = %s", (alice, KEY),
    ).fetchone()
    assert row == (None, None, False)


def test_clear_jobs_only_deletes_the_callers_jobs(pg_conn, two_users):
    alice, bob = two_users
    _save(pg_conn, alice)
    _save(pg_conn, bob)
    db.clear_jobs(pg_conn, bob)
    owners = [r[0] for r in pg_conn.execute("SELECT user_id::text FROM jobs").fetchall()]
    assert owners == [alice]


def test_clear_jobs_also_deletes_only_the_callers_job_status_history(pg_conn, two_users):
    alice, bob = two_users
    _save(pg_conn, alice)
    _save(pg_conn, bob)
    db.set_job_status(pg_conn, alice, KEY, "applied")
    db.set_job_status(pg_conn, bob, KEY, "rejected")

    db.clear_jobs(pg_conn, bob)

    owners = [
        r[0] for r in pg_conn.execute("SELECT user_id::text FROM job_status_history").fetchall()
    ]
    assert owners == [alice]


def test_mark_emailed_only_touches_the_callers_copy_of_a_shared_key(pg_conn, two_users):
    alice, bob = two_users
    _save(pg_conn, alice)
    _save(pg_conn, bob)
    db.mark_emailed(pg_conn, alice, [KEY])
    bob_emailed = pg_conn.execute(
        "SELECT emailed_at FROM jobs WHERE user_id = %s AND key = %s", (bob, KEY),
    ).fetchone()[0]
    assert bob_emailed is None


def test_check_job_urls_with_no_user_id_checks_each_owners_own_url(pg_conn, two_users):
    """None means "check every user's jobs" (the admin's manual Check job
    URLs) -- it must still check each owner's own copy of a shared key
    against that owner's own URL, not cross-contaminate results."""
    alice, bob = two_users
    key = "lever:dead"
    _save(pg_conn, alice, Job(key=key, title="E", url="https://alice.example/dead",
                               source_name="S", source_id="s"))
    _save(pg_conn, bob, Job(key=key, title="E", url="https://bob.example/alive",
                             source_name="S", source_id="s"))

    def fake_http_head(url, **kwargs):
        status = 404 if url == "https://alice.example/dead" else 200
        return type("Resp", (), {"status_code": status})()

    removed = checker.check_job_urls(pg_conn, http_head=fake_http_head, user_id=None)

    alice_removed = pg_conn.execute(
        "SELECT removed_at FROM jobs WHERE user_id = %s AND key = %s", (alice, key),
    ).fetchone()[0]
    bob_removed = pg_conn.execute(
        "SELECT removed_at FROM jobs WHERE user_id = %s AND key = %s", (bob, key),
    ).fetchone()[0]

    assert removed == 1
    assert alice_removed is not None
    assert bob_removed is None


def test_status_history_is_kept_per_owner(pg_conn, two_users):
    alice, bob = two_users
    _save(pg_conn, alice)
    _save(pg_conn, bob)
    db.set_job_status(pg_conn, alice, KEY, "applied")
    db.set_job_status(pg_conn, bob, KEY, "rejected")
    history = db.get_job_status_history(pg_conn, [(alice, KEY), (bob, KEY)])
    assert [e["status"] for e in history[(alice, KEY)]] == ["applied"]
    assert [e["status"] for e in history[(bob, KEY)]] == ["rejected"]
