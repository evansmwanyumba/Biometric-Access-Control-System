import os
from cryptography.fernet import Fernet
from dotenv import load_dotenv

load_dotenv()

ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")

if not ENCRYPTION_KEY:
    raise RuntimeError(
        "ENCRYPTION_KEY not set. Check your .env file. "
        "Generate one with: python3 -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
    )

_fernet = Fernet(ENCRYPTION_KEY.encode())


def encrypt_bytes(data: bytes) -> bytes:
    """Encrypts raw bytes (e.g. a face embedding) for storage."""
    return _fernet.encrypt(data)


def decrypt_bytes(token: bytes) -> bytes:
    """Decrypts bytes previously encrypted with encrypt_bytes()."""
    return _fernet.decrypt(token)
