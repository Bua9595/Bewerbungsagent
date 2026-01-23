from datetime import datetime, timedelta, timezone

from bewerbungsagent.job_state import should_send_reminder


def test_should_send_reminder_when_no_last_sent():
    now = datetime.now(timezone.utc)
    assert should_send_reminder(None, now, reminder_days=2, daily_reminders=False)


def test_should_send_reminder_by_days():
    now = datetime.now(timezone.utc)
    last_old = (now - timedelta(days=3)).isoformat().replace("+00:00", "Z")
    last_recent = (now - timedelta(days=1)).isoformat().replace("+00:00", "Z")
    assert should_send_reminder(last_old, now, reminder_days=2, daily_reminders=False)
    assert not should_send_reminder(last_recent, now, reminder_days=2, daily_reminders=False)


def test_should_send_reminder_daily_override():
    now = datetime.now(timezone.utc)
    last_recent = (now - timedelta(hours=2)).isoformat().replace("+00:00", "Z")
    assert should_send_reminder(last_recent, now, reminder_days=7, daily_reminders=True)
