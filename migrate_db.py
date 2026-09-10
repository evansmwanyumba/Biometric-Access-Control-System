import shutil
import sqlite3
import sys
from datetime import datetime

OLD_DB = "local_gate.db"
BACKUP_DB = f"local_gate_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
NEW_DB = "local_gate_new.db"

def migrate():
    # 1. Backup the current database — never touch data without a safety copy
    shutil.copy(OLD_DB, BACKUP_DB)
    print(f"Backed up existing database to {BACKUP_DB}")

    # 2. Remove the old file (already backed up) and create the new database
    #    with the updated schema from a clean slate.
    import os
    os.remove(OLD_DB)
    from app.database import Base, engine as new_engine
    import app.models  # noqa: ensures models are registered on Base
    Base.metadata.create_all(bind=new_engine)
    print("New schema created.")

    # 3. Copy data across, parents before children
    old_conn = sqlite3.connect(BACKUP_DB)
    old_conn.row_factory = sqlite3.Row
    new_conn = sqlite3.connect("local_gate.db")  # new engine already points here
    new_conn.execute("PRAGMA foreign_keys=ON")

    def copy_table(table, columns):
        rows = old_conn.execute(f"SELECT {', '.join(columns)} FROM {table}").fetchall()
        placeholders = ", ".join(["?"] * len(columns))
        col_list = ", ".join(columns)
        migrated = 0
        for row in rows:
            values = [row[c] for c in columns]
            try:
                new_conn.execute(
                    f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})", values
                )
                migrated += 1
            except sqlite3.IntegrityError as e:
                print(f"SKIPPED row in {table} — {dict(zip(columns, values))} — reason: {e}")
        new_conn.commit()
        print(f"{table}: migrated {migrated}/{len(rows)} rows")

    copy_table("students", ["student_id", "full_name", "course", "status", "created_at"])
    copy_table("admin_users", ["id", "username", "hashed_password", "role", "is_active", "created_at"])
    copy_table("face_embeddings", ["id", "student_id", "embedding_blob"])
    copy_table("access_logs", ["log_id", "student_id", "timestamp", "status_result", "confidence_distance"])

    old_conn.close()
    new_conn.close()
    print("\nMigration complete.")
    print(f"Backup of old DB preserved at: {BACKUP_DB}")

if __name__ == "__main__":
    migrate()
