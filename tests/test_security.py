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
        mock_settings.ENCRYPTION_KEY_OLD = ""

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
        mock_settings.ENCRYPTION_KEY_OLD = ""

        import src.core.security as sec
        sec._fernet = None

        from src.core.security import encrypt

        e1 = encrypt("same_value")
        e2 = encrypt("same_value")
        # Fernet uses time-based tokens, so different encryptions differ
        assert e1 != e2

    @patch("src.core.security.settings")
    def test_key_rotation_decrypts_old_data(self, mock_settings):
        """Data encrypted with old key should be decryptable after rotation."""
        old_key = Fernet.generate_key().decode()
        new_key = Fernet.generate_key().decode()

        import src.core.security as sec

        # Encrypt with old key
        mock_settings.ENCRYPTION_KEY = old_key
        mock_settings.ENCRYPTION_KEY_OLD = ""
        sec._fernet = None
        from src.core.security import encrypt, decrypt
        encrypted_old = encrypt("secret_data")

        # Rotate: new key is primary, old key is fallback
        mock_settings.ENCRYPTION_KEY = new_key
        mock_settings.ENCRYPTION_KEY_OLD = old_key
        sec._fernet = None

        # Old data is still decryptable
        assert decrypt(encrypted_old) == "secret_data"

        # New encryption uses new key
        encrypted_new = encrypt("new_data")
        assert decrypt(encrypted_new) == "new_data"
