"""
One-time migration: encrypts any FaceEmbedding rows that are still stored
as plaintext (from before encryption was added). Safe to re-run — it
detects already-encrypted rows and skips them.
"""
from app.database import SessionLocal
from app.models import FaceEmbedding
from app.crypto_utils import encrypt_bytes, decrypt_bytes
from cryptography.fernet import InvalidToken

def migrate():
    db = SessionLocal()
    records = db.query(FaceEmbedding).all()
    migrated = 0
    already_encrypted = 0

    for record in records:
        try:
            # If this succeeds, it's already encrypted — skip it
            decrypt_bytes(record.embedding_blob)
            already_encrypted += 1
        except InvalidToken:
            # Genuinely plaintext — encrypt it now
            record.embedding_blob = encrypt_bytes(record.embedding_blob)
            migrated += 1

    db.commit()
    db.close()
    print(f"Encrypted {migrated} plaintext embedding(s).")
    print(f"Skipped {already_encrypted} already-encrypted embedding(s).")

if __name__ == "__main__":
    migrate()
