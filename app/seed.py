"""
Seed script: inserts the standard set of departments with their SLA hours.
Run this once after the tables have been created (i.e. after the app has
started at least once, or after running init_db() directly).

Usage:
    python -m app.seed
"""
from app.db import SessionLocal, init_db
from app.models import Department

DEPARTMENTS = [
    {"name": "Water Board", "sla_hours": 24, "escalation_contact": None},
    {"name": "Roads", "sla_hours": 48, "escalation_contact": None},
    {"name": "Sanitation", "sla_hours": 24, "escalation_contact": None},
    {"name": "Electricity", "sla_hours": 12, "escalation_contact": None},
    {"name": "Parks", "sla_hours": 72, "escalation_contact": None},
]


def seed() -> None:
    init_db()
    db = SessionLocal()
    try:
        for dept in DEPARTMENTS:
            existing = db.query(Department).filter(Department.name == dept["name"]).first()
            if existing:
                print(f"  - {dept['name']} already exists, skipping")
                continue
            db.add(Department(**dept))
            print(f"  + created {dept['name']} (sla_hours={dept['sla_hours']})")
        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    seed()
    print("Seeding complete.")
