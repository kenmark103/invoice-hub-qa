"""Reset = drop, recreate, reseed. Usage: python scripts/reset.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import models  # noqa: F401
from app.db import Base, SessionLocal, engine
from app.seed_data import seed_db

if __name__ == "__main__":
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_db(db)
        print("Reset complete.")
    finally:
        db.close()
