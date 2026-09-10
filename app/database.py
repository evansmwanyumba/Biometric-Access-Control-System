from sqlalchemy import create_engine, event
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

SQLITE_URL = "sqlite:///./local_gate.db"

engine = create_engine(SQLITE_URL, connect_args={"check_same_thread": False})

# SQLite does NOT enforce foreign key constraints by default — it accepts
# the ForeignKey() declarations at the SQLAlchemy/ORM level but silently
# allows orphaned rows and ignores ON DELETE behavior unless this pragma
# is set on every connection. This must run per-connection, not once
# globally, since SQLite's FK enforcement is a per-connection setting.
@event.listens_for(engine, "connect")
def _enable_sqlite_fk_enforcement(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
