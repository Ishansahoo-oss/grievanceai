"""
Pydantic request/response schemas for GrievanceAI.

Enums are re-exported from models.py so the DB layer and the API layer
can never define the allowed values differently.
"""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from app.models import Category, GrievanceStatus, Priority

# Re-export for convenient `from app.schemas import Category` imports elsewhere.
__all__ = [
    "Category",
    "GrievanceStatus",
    "Priority",
    "WebIntakeRequest",
    "IntakeResponse",
    "TimelineEntry",
    "SubtaskEntry",
    "GrievanceStatusResponse",
    "VerifyRequest",
    "VerifyResponse",
    "QueueItem",
    "AdminUpdateRequest",
    "EscalateRequest",
    "EscalateResponse",
]


# ---------------------------------------------------------------------------
# Intake
# ---------------------------------------------------------------------------
class WebIntakeRequest(BaseModel):
    description: str = Field(..., min_length=1)
    address: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    language: Optional[str] = None
    media_url: Optional[str] = None


class IntakeResponse(BaseModel):
    tracking_id: str
    status: GrievanceStatus
    category: Category
    priority: Priority
    department: Optional[str] = None
    summary: Optional[str] = None
    merged: bool = False


# ---------------------------------------------------------------------------
# Citizen-facing status lookup
# ---------------------------------------------------------------------------
class TimelineEntry(BaseModel):
    status: GrievanceStatus
    note: Optional[str] = None
    at: datetime


class SubtaskEntry(BaseModel):
    tracking_id: str
    department: Optional[str] = None
    status: GrievanceStatus


class GrievanceStatusResponse(BaseModel):
    tracking_id: str
    status: GrievanceStatus
    category: Category
    priority: Priority
    department: Optional[str] = None
    summary: Optional[str] = None
    created_at: datetime
    sla_due_at: Optional[datetime] = None
    timeline: List[TimelineEntry] = []
    subtasks: List[SubtaskEntry] = []


class VerifyRequest(BaseModel):
    confirmed: bool
    rating: Optional[int] = Field(default=None, ge=1, le=5)


class VerifyResponse(BaseModel):
    tracking_id: str
    status: GrievanceStatus


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------
class QueueItem(BaseModel):
    tracking_id: str
    status: GrievanceStatus
    category: Category
    priority: Priority
    department: Optional[str] = None
    summary: Optional[str] = None
    needs_human_review: bool
    created_at: datetime
    sla_due_at: Optional[datetime] = None


class AdminUpdateRequest(BaseModel):
    status: GrievanceStatus
    note: Optional[str] = None
    changed_by: Optional[str] = None


class EscalateRequest(BaseModel):
    reason: Optional[str] = None
    escalated_to: Optional[str] = None
    changed_by: Optional[str] = None


class EscalateResponse(BaseModel):
    tracking_id: str
    status: GrievanceStatus
    escalated_to: Optional[str] = None
    reason: Optional[str] = None
