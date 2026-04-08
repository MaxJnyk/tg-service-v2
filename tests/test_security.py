"""
Tests for Fernet encryption/decryption.
"""

import pytest
from unittest.mock import patch
from cryptography.fernet import Fernet


class TestSecurity:
    @patch("src.core.security.settings")
    def test_encrypt_decrypt_roundtrip(self, mock_settings):
        key = Fernet.generate_key().decode()
        mock_settings.ENCRYPTION_KEY = key

        # Reset cached fernet
        import src.core.security as sec
        sec._fernet = None

        from src.core.security import encrypt, decrypt

        original = "1234567890:ABCdefGHIjklMNOpqrSTUvwxyz"
        encrypted = encrypt(original)
        assert encrypted != original
        assert decrypt(encrypted) == original

    @patch("src.core.security.settings")
    def test_different_encryptions(self, mock_settings):
        key = Fernet.generate_key().decode()
        mock_settings.ENCRYPTION_KEY = key

        import src.core.security as sec
        sec._fernet = None

        from src.core.security import encrypt

        e1 = encrypt("same_value")
        e2 = encrypt("same_value")
        # Fernet uses time-based tokens, so different encryptions differ
        assert e1 != e2
