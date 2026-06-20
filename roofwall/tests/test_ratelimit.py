"""Fixed-window rate limiter."""

import pytest

from roofwall.ratelimit import FixedWindowRateLimiter


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


def test_allows_up_to_limit_then_blocks():
    clock = FakeClock()
    rl = FixedWindowRateLimiter(max_requests=3, window_seconds=60, clock=clock)
    results = [rl.check("ip1") for _ in range(4)]
    assert [r.allowed for r in results] == [True, True, True, False]
    assert results[0].remaining == 2
    assert results[2].remaining == 0
    assert results[3].retry_after > 0


def test_window_resets_after_expiry():
    clock = FakeClock()
    rl = FixedWindowRateLimiter(max_requests=2, window_seconds=60, clock=clock)
    assert rl.check("ip").allowed
    assert rl.check("ip").allowed
    assert not rl.check("ip").allowed
    clock.advance(61)
    r = rl.check("ip")
    assert r.allowed
    assert r.remaining == 1


def test_keys_are_independent():
    clock = FakeClock()
    rl = FixedWindowRateLimiter(max_requests=1, window_seconds=60, clock=clock)
    assert rl.check("a").allowed
    assert rl.check("b").allowed  # different key, own bucket
    assert not rl.check("a").allowed


def test_retry_after_decreases_within_window():
    clock = FakeClock()
    rl = FixedWindowRateLimiter(max_requests=1, window_seconds=60, clock=clock)
    rl.check("ip")  # consume
    r1 = rl.check("ip")
    clock.advance(30)
    r2 = rl.check("ip")
    assert r1.retry_after == pytest.approx(60, abs=1e-6)
    assert r2.retry_after == pytest.approx(30, abs=1e-6)


def test_disabled_when_zero():
    rl = FixedWindowRateLimiter(max_requests=0)
    assert not rl.enabled
    for _ in range(100):
        assert rl.check("ip").allowed


def test_invalid_config():
    with pytest.raises(ValueError):
        FixedWindowRateLimiter(max_requests=-1)
    with pytest.raises(ValueError):
        FixedWindowRateLimiter(max_requests=5, window_seconds=0)


def test_default_clock_is_monotonic():
    rl = FixedWindowRateLimiter(max_requests=5)
    # Should not raise and should use a real clock.
    assert rl.check("ip").allowed
