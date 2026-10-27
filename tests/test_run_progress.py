import pytest

from app import run_progress


@pytest.fixture(autouse=True)
def _clear_progress():
    run_progress._clear_all()
    yield
    run_progress._clear_all()


def test_get_returns_none_when_no_run_started():
    assert run_progress.get("u1") is None


def test_start_then_update_reflects_current_source_and_done_count():
    run_progress.start("u1", total=5)
    run_progress.update("u1", "Acme Corp", done=2)
    assert run_progress.get("u1") == {"source": "Acme Corp", "done": 2, "total": 5}


def test_finish_clears_the_entry():
    run_progress.start("u1", total=5)
    run_progress.finish("u1")
    assert run_progress.get("u1") is None


def test_entries_are_isolated_per_user():
    run_progress.start("u1", total=5)
    run_progress.start("u2", total=9)
    run_progress.update("u1", "Acme", done=1)
    assert run_progress.get("u2") == {"source": None, "done": 0, "total": 9}


def test_update_after_finish_is_a_no_op():
    run_progress.start("u1", total=5)
    run_progress.finish("u1")
    run_progress.update("u1", "Acme", done=1)
    assert run_progress.get("u1") is None
