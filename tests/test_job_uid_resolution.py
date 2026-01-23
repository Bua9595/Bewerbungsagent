from tools.commands.tracker import resolve_job_uid


def test_resolve_job_uid_by_prefix():
    state = {
        "abcd1234": {
            "link": "https://example.com/job/1",
            "canonical_url": "https://example.com/job/1",
        }
    }
    assert resolve_job_uid(state, "abcd", "") == "abcd1234"


def test_resolve_job_uid_by_url():
    state = {
        "abcd1234": {
            "link": "https://example.com/job/1",
            "canonical_url": "https://example.com/job/1",
        }
    }
    assert resolve_job_uid(state, "", "https://example.com/job/1") == "abcd1234"


def test_resolve_job_uid_ambiguous_prefix():
    state = {
        "abcd1234": {"link": "https://example.com/job/1"},
        "abcd9999": {"link": "https://example.com/job/2"},
    }
    assert resolve_job_uid(state, "abcd", "") is None
