"""
Тесты для констант ретраев PostingService — стиль Димы (flat functions).
"""

from src.modules.posting.retry import MAX_RETRIES, BACKOFF_SECONDS


def test_backoff_values():
    """Значения бэкофа должны быть [1, 2, 4]."""
    assert BACKOFF_SECONDS == [1, 2, 4]


def test_max_retries():
    """Максимальное количество ретраев должно быть 3."""
    assert MAX_RETRIES == 3


def test_backoff_length_matches_retries():
    """BACKOFF_SECONDS должен иметь достаточно значений для MAX_RETRIES-1 слипов."""
    assert len(BACKOFF_SECONDS) >= MAX_RETRIES - 1
