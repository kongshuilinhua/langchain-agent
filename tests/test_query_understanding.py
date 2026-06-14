from core.services.agents import normalize_query_understanding, DEFAULT_QUERY_UNDERSTANDING


def test_normalize_defaults_on_empty():
    result = normalize_query_understanding(None)
    assert result == DEFAULT_QUERY_UNDERSTANDING


def test_normalize_clamps_threshold_and_turns():
    result = normalize_query_understanding(
        {"confidence_threshold": 5, "history_turns": 999, "enabled": False}
    )
    assert result["confidence_threshold"] == 1.0
    assert result["history_turns"] == 12
    assert result["enabled"] is False


def test_normalize_blank_model_becomes_none():
    result = normalize_query_understanding({"model": "   "})
    assert result["model"] is None
