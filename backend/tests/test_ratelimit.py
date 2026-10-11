from app.ratelimit import RateLimiter


def _limiter(limit, now, **kwargs):
    return RateLimiter(limit, window_sec=100, clock=lambda: now[0], **kwargs)


def test_blocks_after_limit_and_recovers():
    now = [0.0]
    limiter = _limiter(2, now)
    assert limiter.acquire(["a"]) == 0
    assert limiter.acquire(["a"]) == 0
    assert limiter.acquire(["a"]) == 100
    now[0] = 50.0
    assert limiter.acquire(["a"]) == 50
    now[0] = 100.0
    assert limiter.acquire(["a"]) == 0


def test_blocked_request_records_nothing_for_other_keys():
    now = [0.0]
    limiter = _limiter(1, now)
    assert limiter.acquire(["b"]) == 0
    assert limiter.acquire(["a", "b"]) > 0
    assert limiter.acquire(["a"]) == 0  # "a" was not charged by the blocked request


def test_zero_limit_disables_limiting():
    now = [0.0]
    limiter = _limiter(0, now)
    for _ in range(100):
        assert limiter.acquire(["a"]) == 0


def test_key_table_stays_bounded():
    now = [0.0]
    limiter = _limiter(5, now, max_keys=3)
    for i in range(10):
        now[0] = float(i)
        limiter.acquire([f"k{i}"])
    assert len(limiter._buckets) <= 3
