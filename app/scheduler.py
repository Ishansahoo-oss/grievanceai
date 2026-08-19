"""
APScheduler-based SLA breach checker.

Runs periodically in-process (no Celery/Redis needed at hackathon scale)
and auto-escalates any open grievance whose sla_due_at has passed:
  - status -> escalated
  - a row is written to `escalations`
  - a row is written to `status_history`
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler

from app.db import SessionLocal
from app.models import ESCALATABLE_STATUSES, Department, Escalation, Grievance, GrievanceStatus, StatusHistory

logger = logging.getLogger("grievanceai.scheduler")

_scheduler: Optional[BackgroundScheduler] = None


def check_overdue_grievances() -> int:
    """
    Finds every OPEN grievance whose SLA has been breached and auto-
    escalates it. Returns the number of grievances escalated.

    Runs its own DB session since it executes outside of any HTTP request.
    """
    db = SessionLocal()
    escalated_count = 0
    try:
        now = datetime.now(timezone.utc)
        overdue = (
            db.query(Grievance)
            .filter(
                Grievance.status.in_(ESCALATABLE_STATUSES),
                Grievance.sla_due_at.isnot(None),
                Grievance.sla_due_at < now,
            )
            .all()
        )

        for grievance in overdue:
            department_name = None
            escalation_contact = None
            if grievance.department_id:
                dept = db.get(Department, grievance.department_id)
                if dept:
                    department_name = dept.name
                    escalation_contact = dept.escalation_contact

            db.add(
                Escalation(
                    grievance_id=grievance.id,
                    escalated_from=department_name,
                    escalated_to=escalation_contact or "unassigned_escalation_contact",
                    reason=f"SLA breached: was due at {grievance.sla_due_at.isoformat()}",
                )
            )
            grievance.status = GrievanceStatus.escalated
            db.add(
                StatusHistory(
                    grievance_id=grievance.id,
                    status=GrievanceStatus.escalated,
                    changed_by="system",
                    note="Auto-escalated: SLA breached",
                )
            )
            escalated_count += 1

        db.commit()
        if escalated_count:
            logger.info("Auto-escalated %d overdue grievance(s)", escalated_count)
        return escalated_count
    except Exception:
        db.rollback()
        logger.exception("Error while checking overdue grievances")
        return 0
    finally:
        db.close()


def start_scheduler(interval_minutes: int = 5) -> BackgroundScheduler:
    """Idempotent: safe to call more than once (e.g. across --reload restarts)."""
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    _scheduler = BackgroundScheduler(timezone="UTC")
    _scheduler.add_job(
        check_overdue_grievances,
        "interval",
        minutes=interval_minutes,
        id="sla_breach_check",
        replace_existing=True,
    )
    _scheduler.start()
    logger.info("SLA breach scheduler started (checks every %d minute(s))", interval_minutes)
    return _scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
