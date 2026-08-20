"""
Citizen-facing endpoints: check status, confirm/reopen resolution.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Department, Grievance, GrievanceStatus, StatusHistory
from app.schemas import (
    GrievanceStatusResponse,
    SubtaskEntry,
    TimelineEntry,
    VerifyRequest,
    VerifyResponse,
)

router = APIRouter(tags=["citizen"])


def _get_grievance_or_404(db: Session, tracking_id: str) -> Grievance:
    grievance = db.query(Grievance).filter(Grievance.tracking_id == tracking_id).first()
    if grievance is None:
        raise HTTPException(status_code=404, detail="Grievance not found")
    return grievance


@router.get("/grievance/{tracking_id}/status", response_model=GrievanceStatusResponse)
def get_status(tracking_id: str, db: Session = Depends(get_db)):
    grievance = _get_grievance_or_404(db, tracking_id)

    department_name = None
    if grievance.department_id:
        dept = db.get(Department, grievance.department_id)
        department_name = dept.name if dept else None

    timeline = [
        TimelineEntry(status=h.status, note=h.note, at=h.changed_at)
        for h in grievance.status_history
    ]

    subtasks = []
    for child in grievance.subtasks:  # backref from Grievance.parent (self-referencing FK)
        child_dept_name = None
        if child.department_id:
            child_dept = db.get(Department, child.department_id)
            child_dept_name = child_dept.name if child_dept else None
        subtasks.append(
            SubtaskEntry(tracking_id=child.tracking_id, department=child_dept_name, status=child.status)
        )

    return GrievanceStatusResponse(
        tracking_id=grievance.tracking_id,
        status=grievance.status,
        category=grievance.category,
        priority=grievance.priority,
        department=department_name,
        summary=grievance.description[:140],
        address=grievance.address,
        created_at=grievance.created_at,
        sla_due_at=grievance.sla_due_at,
        timeline=timeline,
        subtasks=subtasks,
    )


@router.post("/grievance/{tracking_id}/verify", response_model=VerifyResponse)
def verify_grievance(tracking_id: str, payload: VerifyRequest, db: Session = Depends(get_db)):
    grievance = _get_grievance_or_404(db, tracking_id)

    if payload.confirmed:
        grievance.status = GrievanceStatus.closed
        note = "Citizen confirmed resolution"
        if payload.rating is not None:
            note += f" (rating: {payload.rating})"
    else:
        grievance.status = GrievanceStatus.reopened
        note = "Citizen rejected resolution; grievance reopened"

    db.add(
        StatusHistory(
            grievance_id=grievance.id,
            status=grievance.status,
            changed_by="citizen",
            note=note,
        )
    )
    db.commit()
    db.refresh(grievance)

    return VerifyResponse(tracking_id=grievance.tracking_id, status=grievance.status)
