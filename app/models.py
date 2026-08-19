"""
SQLAlchemy models for GrievanceAI.

The status/category/priority enums are defined here as plain Python
enums and reused by schemas.py to build matching Pydantic enums, so
the two layers can never drift apart.
"""
import enum
import uuid
from datetime import datetime, timezone

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_tracking_id() -> str:
    """GRV-XXXXX style tracking id. Uniqueness enforced by the DB constraint;
    on the rare collision the caller should retry."""
    return f"GRV-{uuid.uuid4().int % 100000:05d}"


class GrievanceStatus(str, enum.Enum):
    new = "new"
    assigned = "assigned"
    in_progress = "in_progress"
    escalated = "escalated"
    resolved = "resolved"
    closed = "closed"
    reopened = "reopened"


# Statuses considered "still open" for duplicate-merge search in /intake/web.
OPEN_STATUSES = (
    GrievanceStatus.new,
    GrievanceStatus.assigned,
    GrievanceStatus.in_progress,
    GrievanceStatus.escalated,
)

# Statuses eligible for SLA-breach auto-escalation. Deliberately excludes
# `escalated` itself — otherwise an overdue ticket that's already been
# escalated would get re-escalated (and re-logged) on every scheduler
# tick forever, since it stays overdue by definition once breached.
ESCALATABLE_STATUSES = (
    GrievanceStatus.new,
    GrievanceStatus.assigned,
    GrievanceStatus.in_progress,
)


class Priority(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class Category(str, enum.Enum):
    water_supply = "water_supply"
    roads = "roads"
    sanitation = "sanitation"
    electricity = "electricity"
    streetlights = "streetlights"
    drainage = "drainage"
    garbage = "garbage"
    parks = "parks"
    other = "other"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    whatsapp_id = Column(String, nullable=True, index=True)
    language_pref = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    grievances = relationship("Grievance", back_populates="user")


class Department(Base):
    __tablename__ = "departments"

    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    sla_hours = Column(Integer, nullable=False)
    escalation_contact = Column(String, nullable=True)

    grievances = relationship("Grievance", back_populates="department")


class Grievance(Base):
    __tablename__ = "grievances"

    id = Column(Integer, primary_key=True)
    tracking_id = Column(String, unique=True, nullable=False, index=True, default=new_tracking_id)
    parent_id = Column(Integer, ForeignKey("grievances.id"), nullable=True)

    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    category = Column(SAEnum(Category, name="category_enum"), nullable=False)
    subcategory = Column(String, nullable=True)
    description = Column(Text, nullable=False)
    original_text = Column(Text, nullable=True)
    language = Column(String, nullable=True)

    priority = Column(SAEnum(Priority, name="priority_enum"), nullable=False, default=Priority.medium)
    status = Column(SAEnum(GrievanceStatus, name="status_enum"), nullable=False, default=GrievanceStatus.new)

    confidence = Column(Float, nullable=False, default=0.0)
    needs_human_review = Column(Boolean, nullable=False, default=False)

    lat = Column(Float, nullable=True)
    lng = Column(Float, nullable=True)
    address = Column(String, nullable=True)

    department_id = Column(Integer, ForeignKey("departments.id"), nullable=True)

    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    sla_due_at = Column(DateTime(timezone=True), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="grievances")
    department = relationship("Department", back_populates="grievances")
    parent = relationship("Grievance", remote_side=[id], backref="subtasks")
    media = relationship("GrievanceMedia", back_populates="grievance", cascade="all, delete-orphan")
    status_history = relationship(
        "StatusHistory", back_populates="grievance", cascade="all, delete-orphan",
        order_by="StatusHistory.changed_at",
    )
    escalations = relationship("Escalation", back_populates="grievance", cascade="all, delete-orphan")
    vector = relationship(
        "ComplaintVector", back_populates="grievance", uselist=False, cascade="all, delete-orphan"
    )


class GrievanceMedia(Base):
    __tablename__ = "grievance_media"

    id = Column(Integer, primary_key=True)
    grievance_id = Column(Integer, ForeignKey("grievances.id"), nullable=False)
    type = Column(String, nullable=False)  # e.g. "image", "audio", "video"
    storage_url = Column(String, nullable=False)

    grievance = relationship("Grievance", back_populates="media")


class StatusHistory(Base):
    __tablename__ = "status_history"

    id = Column(Integer, primary_key=True)
    grievance_id = Column(Integer, ForeignKey("grievances.id"), nullable=False)
    status = Column(SAEnum(GrievanceStatus, name="status_history_status_enum"), nullable=False)
    changed_by = Column(String, nullable=True)
    note = Column(String, nullable=True)
    changed_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    grievance = relationship("Grievance", back_populates="status_history")


class Escalation(Base):
    __tablename__ = "escalations"

    id = Column(Integer, primary_key=True)
    grievance_id = Column(Integer, ForeignKey("grievances.id"), nullable=False)
    escalated_from = Column(String, nullable=True)
    escalated_to = Column(String, nullable=True)
    reason = Column(String, nullable=True)
    escalated_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    grievance = relationship("Grievance", back_populates="escalations")


class ComplaintVector(Base):
    __tablename__ = "complaint_vectors"

    grievance_id = Column(Integer, ForeignKey("grievances.id"), primary_key=True)
    embedding = Column(Vector(768), nullable=False)

    grievance = relationship("Grievance", back_populates="vector")


class ProcessedMessage(Base):
    """Idempotency ledger for WhatsApp webhook messages."""
    __tablename__ = "processed_messages"

    message_id = Column(String, primary_key=True)
    processed_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    __table_args__ = (UniqueConstraint("message_id", name="uq_processed_messages_message_id"),)
