"""Seed the database (deterministic). Usage: python scripts/seed.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import SessionLocal, init_db
from app.seed_data import PASSWORD, seed_db

if __name__ == "__main__":
    init_db()
    db = SessionLocal()
    try:
        seed_db(db)
        print(f"Seeded. All users share password: {PASSWORD}")
        print("Admins: admin@acme.test, admin@beta.test, admin@nuru.test")
    finally:
        db.close()
