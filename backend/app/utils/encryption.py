"""
Encryption Utility - Fernet symmetric encryption for data at rest
"""
import logging

logger = logging.getLogger(__name__)

_fernet = None


def _get_fernet():
    global _fernet
    if _fernet is None:
        from cryptography.fernet import Fernet
        from app.config import get_settings
        settings = get_settings()
        key = settings.ENCRYPTION_KEY
        if not key:
            key = Fernet.generate_key().decode()
            logger.warning("Using auto-generated encryption key (not for production!)")
        _fernet = Fernet(key.encode() if isinstance(key, str) else key)
    return _fernet


class EncryptionService:
    """Encrypt/decrypt sensitive data using Fernet symmetric encryption."""

    def encrypt(self, data: str) -> str:
        return _get_fernet().encrypt(data.encode()).decode()

    def decrypt(self, encrypted_data: str) -> str:
        return _get_fernet().decrypt(encrypted_data.encode()).decode()

    def encrypt_bytes(self, data: bytes) -> bytes:
        return _get_fernet().encrypt(data)

    def decrypt_bytes(self, encrypted_data: bytes) -> bytes:
        return _get_fernet().decrypt(encrypted_data)


encryption_service = EncryptionService()
