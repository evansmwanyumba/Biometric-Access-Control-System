import sys
from app.database import SessionLocal, engine, Base
from app.models import AdminUser
from app.auth import hash_password, SUPER_ADMIN

Base.metadata.create_all(bind=engine)

def seed():
    db = SessionLocal()
    username = input("Super admin username: ").strip()
    password = input("Super admin password: ").strip()

    if db.query(AdminUser).filter(AdminUser.username == username).first():
        print(f"User '{username}' already exists.")
        sys.exit(1)

    user = AdminUser(
        username=username,
        hashed_password=hash_password(password),
        role=SUPER_ADMIN,
        is_active=1
    )
    db.add(user)
    db.commit()
    print(f"Super admin '{username}' created.")

if __name__ == "__main__":
    seed()
