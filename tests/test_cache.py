from __future__ import annotations

from fintrace.core.cache import ResponseCache, cache_key


def test_put_get_roundtrip(tmp_path) -> None:
    cache = ResponseCache(tmp_path / "cache.sqlite")
    key = cache_key("m", [{"role": "user", "content": "q"}], None, 0.0)
    assert cache.get(key) is None
    cache.put(key, {"content": "answer", "prompt_tokens": 3})
    assert cache.get(key) == {"content": "answer", "prompt_tokens": 3}
    cache.close()


def test_key_is_sensitive_to_messages(tmp_path) -> None:
    a = cache_key("m", [{"role": "user", "content": "q1"}], None, 0.0)
    b = cache_key("m", [{"role": "user", "content": "q2"}], None, 0.0)
    c = cache_key("m2", [{"role": "user", "content": "q1"}], None, 0.0)
    assert len({a, b, c}) == 3
