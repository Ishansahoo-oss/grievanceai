"""
Admin/officer-facing endpoints: dashboard queue, status updates.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Category, Department, Escalation, Grievance, GrievanceStatus, Priority, StatusHistory
from app.notifications import send_notification
from app.schemas import AdminUpdateRequest, EscalateRequest, EscalateResponse, QueueItem

router = APIRouter(tags=["admin"])


@router.get("/admin/queue", response_model=List[QueueItem])
def get_queue(
    department_id: Optional[int] = Query(default=None),
    status: Optional[GrievanceStatus] = Query(default=None),
    priority: Optional[Priority] = Query(default=None),
    db: Session = Depends(get_db),
):
    query = db.query(Grievance)

    if department_id is not None:
        query = query.filter(Grievance.department_id == department_id)
    if status is not None:
        query = query.filter(Grievance.status == status)
    if priority is not None:
        query = query.filter(Grievance.priority == priority)

    grievances = query.order_by(Grievance.created_at.desc()).all()

    # Batch-load department names instead of one query per row.
    department_ids = {g.department_id for g in grievances if g.department_id}
    departments = {}
    if department_ids:
        for dept in db.query(Department).filter(Department.id.in_(department_ids)).all():
            departments[dept.id] = dept.name

    return [
        QueueItem(
            tracking_id=g.tracking_id,
            status=g.status,
            category=g.category,
            priority=g.priority,
            department=departments.get(g.department_id),
            summary=g.description[:140],
            needs_human_review=g.needs_human_review,
            created_at=g.created_at,
            sla_due_at=g.sla_due_at,
        )
        for g in grievances
    ]


@router.patch("/admin/grievance/{id}", response_model=QueueItem)
def update_grievance(id: int, payload: AdminUpdateRequest, db: Session = Depends(get_db)):
    grievance = db.get(Grievance, id)
    if grievance is None:
        raise HTTPException(status_code=404, detail="Grievance not found")

    grievance.status = payload.status
    db.add(
        StatusHistory(
            grievance_id=grievance.id,
            status=payload.status,
            changed_by=payload.changed_by or "admin",
            note=payload.note,
        )
    )
    db.commit()
    db.refresh(grievance)

    department_name = None
    if grievance.department_id:
        dept = db.get(Department, grievance.department_id)
        department_name = dept.name if dept else None

    return QueueItem(
        tracking_id=grievance.tracking_id,
        status=grievance.status,
        category=grievance.category,
        priority=grievance.priority,
        department=department_name,
        summary=grievance.description[:140],
        needs_human_review=grievance.needs_human_review,
        created_at=grievance.created_at,
        sla_due_at=grievance.sla_due_at,
    )


@router.post("/admin/grievance/{id}/escalate", response_model=EscalateResponse)
def escalate_grievance(id: int, payload: EscalateRequest, db: Session = Depends(get_db)):
    """
    Manual escalation, triggered by an officer regardless of whether the
    SLA has actually been breached (e.g. a citizen is threatening legal
    action, a VIP complaint, media attention, etc.) — distinct from the
    automatic SLA-breach escalation the scheduler runs periodically.
    """
    grievance = db.get(Grievance, id)
    if grievance is None:
        raise HTTPException(status_code=404, detail="Grievance not found")

    department_name = None
    department_contact = None
    if grievance.department_id:
        dept = db.get(Department, grievance.department_id)
        if dept:
            department_name = dept.name
            department_contact = dept.escalation_contact

    escalated_to = payload.escalated_to or department_contact or "unassigned_escalation_contact"
    reason = payload.reason or "Manual escalation by officer"

    db.add(
        Escalation(
            grievance_id=grievance.id,
            escalated_from=department_name,
            escalated_to=escalated_to,
            reason=reason,
        )
    )
    grievance.status = GrievanceStatus.escalated
    db.add(
        StatusHistory(
            grievance_id=grievance.id,
            status=GrievanceStatus.escalated,
            changed_by=payload.changed_by or "admin",
            note=reason,
        )
    )
    send_notification(
        db,
        grievance=grievance,
        channel="internal",
        message=f"Grievance {grievance.tracking_id} manually escalated: {reason} (to {escalated_to}).",
    )
    db.commit()
    db.refresh(grievance)

    return EscalateResponse(
        tracking_id=grievance.tracking_id,
        status=grievance.status,
        escalated_to=escalated_to,
        reason=reason,
    )
