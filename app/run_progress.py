import threading

_lock = threading.Lock()
_progress: dict[str, dict] = {}


def start(user_id: str, total: int) -> None:
    with _lock:
        _progress[user_id] = {"source": None, "done": 0, "total": total}


def update(user_id: str, source_name: str, done: int) -> None:
    with _lock:
        entry = _progress.get(user_id)
        if entry is not None:
            entry["source"] = source_name
            entry["done"] = done


def finish(user_id: str) -> None:
    with _lock:
        _progress.pop(user_id, None)


def get(user_id: str) -> dict | None:
    with _lock:
        entry = _progress.get(user_id)
        return dict(entry) if entry is not None else None


def _clear_all() -> None:
    """Test-only: reset all in-memory progress state between tests."""
    with _lock:
        _progress.clear()
