import pytest


@pytest.fixture
def tmp_db_path(tmp_path):
    return str(tmp_path / "state.db")
