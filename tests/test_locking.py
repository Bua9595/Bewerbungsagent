import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tools.commands.mail_list import _lock_is_stale


def test_lock_stale_by_ttl():
    tmp_dir = Path("generated") / "test_tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    lock_path = tmp_dir / "mail_list.lock"
    started = (datetime.now(timezone.utc) - timedelta(minutes=10)).replace(microsecond=0)
    payload = {"started_at": started.isoformat().replace("+00:00", "Z")}
    lock_path.write_text(json.dumps(payload), encoding="utf-8")

    assert _lock_is_stale(lock_path, ttl_min=5)
    assert not _lock_is_stale(lock_path, ttl_min=15)

    try:
        lock_path.unlink()
    except Exception:
        pass
