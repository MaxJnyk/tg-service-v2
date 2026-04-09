"""
Тесты для Fernet шифрования/расшифровки и security-утили
"""

import pytest
from unittest.mock import patch, MagicMock
from cryptography.fernet import Fernet

import src.core.security as sec
from src.core.security import encrypt, decrypt, redact_sensitive, mask_phone, validate_encryption_key


# =============================================================================
# Fixtures
# =============================================================================
@pytest.fixture
def reset_fernet():
    """Сброс кешированного fernet перед тестом."""
    sec._fernet = None
    yield
    sec._fernet = None


@pytest.fixture
def mock_encryption_key(reset_fernet):
    """Фикстура с тестовым ключом шифрования."""
    key = Fernet.generate_key().decode()
    with patch.object(sec, 'settings') as mock:
        mock.ENCRYPTION_KEY = key
        mock.ENCRYPTION_KEY_OLD = ""
        yield key


# =============================================================================
# Encryption Tests
# =============================================================================
def test_encrypt_decrypt_roundtrip(mock_encryption_key):
    """Шифрование и расшифровка должны быть обратимы."""
    original = "1234567890:ABCdefGHIjklMNOpqrSTUvwxyz"
    encrypted = encrypt(original)
    
    assert encrypted != original
    assert decrypt(encrypted) == original


def test_different_encryptions_produce_different_tokens(mock_encryption_key):
    """Fernet использует time-based токены — разные шифрования отличаются."""
    e1 = encrypt("same_value")
    e2 = encrypt("same_value")
    
    assert e1 != e2
    # Но оба расшифровываются в одно и то же
    assert decrypt(e1) == decrypt(e2) == "same_value"


def test_key_rotation_decrypts_old_data(reset_fernet):
    """Данные, зашифрованные старым ключом, расшифровываются после ротации."""
    old_key = Fernet.generate_key().decode()
    new_key = Fernet.generate_key().decode()
    
    # Шифруем старым ключом
    with patch.object(sec, 'settings') as mock:
        mock.ENCRYPTION_KEY = old_key
        mock.ENCRYPTION_KEY_OLD = ""
        sec._fernet = None
        encrypted_old = encrypt("secret_data")
    
    # Ротация: новый ключ — primary, старый — fallback
    with patch.object(sec, 'settings') as mock:
        mock.ENCRYPTION_KEY = new_key
        mock.ENCRYPTION_KEY_OLD = old_key
        sec._fernet = None
        
        # Старые данные всё ещё расшифровываются
        assert decrypt(encrypted_old) == "secret_data"
        
        # Новое шифрование использует новый ключ
        encrypted_new = encrypt("new_data")
        assert decrypt(encrypted_new) == "new_data"


def test_validate_encryption_key_rejects_default(reset_fernet):
    """Валидация отклоняет дефолтный ключ."""
    with patch.object(sec, 'settings') as mock:
        mock.ENCRYPTION_KEY = "CHANGE_ME_32_BYTES_BASE64_KEY_HERE"
        sec._fernet = None
        
        with pytest.raises(RuntimeError, match="ENCRYPTION_KEY is not set"):
            validate_encryption_key()


def test_validate_encryption_key_rejects_empty(reset_fernet):
    """Валидация отклоняет пустой ключ."""
    with patch.object(sec, 'settings') as mock:
        mock.ENCRYPTION_KEY = ""
        sec._fernet = None
        
        with pytest.raises(RuntimeError, match="ENCRYPTION_KEY is not set"):
            validate_encryption_key()


# =============================================================================
# Redact Sensitive Data Tests
# =============================================================================
def test_redacts_bot_token():
    """Маскирование bot token в тексте."""
    text = "Error with bot 1234567890:ABCdefGHIjklMNOpqrSTUvwxyz123456"
    result = redact_sensitive(text)
    
    assert "1234567890" not in result
    assert "[REDACTED_BOT_TOKEN]" in result


def test_redacts_fernet_token():
    """Маскирование Fernet токена."""
    key = Fernet.generate_key().decode()
    f = Fernet(key)
    token = f.encrypt(b"secret").decode()
    
    text = f"Decryption failed for token {token}"
    result = redact_sensitive(text)
    
    assert token not in result


def test_truncates_long_messages():
    """Обрезка длинных сообщений."""
    text = "error: " + "something went wrong. " * 30  # ~660 chars
    result = redact_sensitive(text, max_length=100)
    
    assert len(result) <= 120  # 100 + ...[truncated]
    assert "...[truncated]" in result


def test_passes_short_safe_messages():
    """Короткие безопасные сообщения не изменяются."""
    text = "Simple error message"
    
    assert redact_sensitive(text) == text


# =============================================================================
# Mask Phone Tests
# =============================================================================
def test_masks_phone():
    """Маскирование телефона."""
    assert mask_phone("+14244371383") == "+142***1383"


def test_short_phone_masked():
    """Короткий телефон полностью маскируется."""
    assert mask_phone("123") == "***"


def test_empty_phone_masked():
    """Пустой телефон маскируется."""
    assert mask_phone("") == "***"
