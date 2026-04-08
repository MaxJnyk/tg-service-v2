"""Retry constants for bot posting operations.

Used by PostingService for exponential backoff when switching bots.
"""

MAX_RETRIES = 3
BACKOFF_SECONDS = [1, 2, 4]  # exponential backoff: 1s, 2s, 4s
