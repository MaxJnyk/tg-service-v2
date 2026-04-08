"""
Tests for retry constants used by PostingService.
"""

from src.modules.posting.retry import MAX_RETRIES, BACKOFF_SECONDS


class TestRetryConstants:
    def test_backoff_values(self):
        assert BACKOFF_SECONDS == [1, 2, 4]

    def test_max_retries(self):
        assert MAX_RETRIES == 3

    def test_backoff_length_matches_retries(self):
        """BACKOFF_SECONDS must have enough entries for MAX_RETRIES-1 sleeps."""
        assert len(BACKOFF_SECONDS) >= MAX_RETRIES - 1
