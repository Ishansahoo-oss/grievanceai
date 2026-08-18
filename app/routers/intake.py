"""
Intake endpoints: where new grievances enter the system (web form,
WhatsApp webhook — the latter added in a later step).
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import ai_client
from app.db import get_db
from app.models import (
    OPEN_STATUSES,
    Category,
    ComplaintVector,
    Department,
    Grievance,
    GrievanceStatus,
    Priority,
    ProcessedMessage,
    StatusHistory,
    User,
    new_tracking_id,
)
from app.schemas import IntakeResponse, WebIntakeRequest

logger = logging.getLogger("grievanceai.intake")

router = APIRouter(tags=["intake"])

# Simple category -> department-name mapping. Kept as a plain dict per the
# spec ("simple dict in code") rather than a DB-driven routing table for now.
CATEGORY_TO_DEPARTMENT = {
    Category.water_supply: "Water Board",
    Category.roads: "Roads",
    Category.sanitation: "Sanitation",
    Category.electricity: "Electricity",
    Category.streetlights: "Electricity",
    Category.drainage: "Sanitation",
    Category.garbage: "Sanitation",
    Category.parks: "Parks",
    Category.other: "Roads",  # fallback bucket for uncategorized complaints
}

# Cosine distance threshold for treating two complaints as duplicates.
# distance < 0.15  <=>  cosine similarity > 0.85
DUPLICATE_DISTANCE_THRESHOLD = 0.15

# Classification confidence below this means: don't auto-route to a
# department. Instead the ticket is created with department_id=None and
# needs_human_review=True, so it shows up in a human triage queue
# (GET /admin/queue with department_id omitted + needs_human_review filter).
ROUTING_CONFIDENCE_THRESHOLD = 0.6


def _safe_classify(text: str) -> dict:
    """
    Wraps ai_client.classify_complaint with the fallback behavior required
    by the spec: if the AI call fails for any reason, intake must still
    succeed with category="other", priority="medium", confidence=0, and
    needs_human_review=True.
    """
    try:
        result = ai_client.classify_complaint(text)
        # Guard against an AI response with confidence below threshold —
        # caller decides needs_human_review from this, not us.
        return {"ok": True, "data": result}
    except Exception:
        logger.exception("classify_complaint failed; falling back to defaults")
        return {"ok": False, "data": None}


def _safe_embed(text: str) -> Optional[list]:
    try:
        result = ai_client.embed_text(text)
        return result["vector"]
    except Exception:
        logger.exception("embed_text failed; skipping duplicate-detection for this intake")
        return None


def _find_duplicate(db: Session, embedding: list) -> Optional[Grievance]:
    """
    Search complaint_vectors for the closest OPEN grievance by cosine
    distance. Returns the matching Grievance if distance < threshold,
    else None.
    """
    distance_col = ComplaintVector.embedding.cosine_distance(embedding).label("distance")
    row = (
        db.query(Grievance, distance_col)
        .join(ComplaintVector, ComplaintVector.grievance_id == Grievance.id)
        .filter(Grievance.status.in_(OPEN_STATUSES))
        .order_by(distance_col)
        .first()
    )
    if row is None:
        return None

    grievance, distance = row
    if distance is not None and distance < DUPLICATE_DISTANCE_THRESHOLD:
        return grievance
    return None


def _department_for_category(db: Session, category: Category) -> Optional[Department]:
    name = CATEGORY_TO_DEPARTMENT.get(category)
    if not name:
        return None
    return db.query(Department).filter(Department.name == name).first()


def _create_grievance(
    db: Session,
    *,
    description: str,
    original_text: str,
    language: Optional[str],
    address: Optional[str],
    lat: Optional[float],
    lng: Optional[float],
    user_id: Optional[int] = None,
) -> Grievance:
    """
    Shared creation flow used by both /intake/web and the WhatsApp webhook:
    classify -> embed -> dedupe-check -> route-or-triage -> create-or-merge.
    Returns the Grievance that should be reported back to the caller
    (either a brand-new one, or the existing one it was merged into).
    The caller can distinguish "merged" by checking whether the returned
    grievance was already persisted before this call (see `merged` flag
    set on the returned object as a transient attribute).
    """
    classification = _safe_classify(description)

    if classification["ok"]:
        data = classification["data"]
        category = Category(data["category"]) if data["category"] in Category._value2member_map_ else Category.other
        priority = Priority(data["priority"]) if data["priority"] in Priority._value2member_map_ else Priority.medium
        confidence = float(data.get("confidence", 0.0))
        subcategory = data.get("subcategory")
        summary = data.get("summary") or description[:140]
        needs_human_review = confidence < ROUTING_CONFIDENCE_THRESHOLD
    else:
        category = Category.other
        priority = Priority.medium
        confidence = 0.0
        subcategory = None
        summary = description[:140]
        needs_human_review = True

    embedding = _safe_embed(description)

    if embedding is not None:
        duplicate = _find_duplicate(db, embedding)
        if duplicate is not None:
            duplicate._merged = True  # transient flag, not persisted
            return duplicate

    # Below the confidence threshold: don't auto-route. The ticket is
    # created with no department assigned and needs_human_review=True,
    # so an officer/admin can triage and assign it manually via
    # PATCH /admin/grievance/{id}.
    department = None if needs_human_review else _department_for_category(db, category)

    grievance = Grievance(
        tracking_id=new_tracking_id(),
        user_id=user_id,
        category=category,
        subcategory=subcategory,
        description=description,
        original_text=original_text,
        language=language,
        priority=priority,
        status=GrievanceStatus.new,
        confidence=confidence,
        needs_human_review=needs_human_review,
        lat=lat,
        lng=lng,
        address=address,
        department_id=department.id if department else None,
    )

    if department is not None:
        grievance.sla_due_at = datetime.now(timezone.utc) + timedelta(hours=department.sla_hours)

    # Retry once on tracking_id collision (astronomically unlikely, but cheap to handle).
    for attempt in range(2):
        try:
            db.add(grievance)
            db.flush()
            break
        except IntegrityError:
            db.rollback()
            if attempt == 1:
                raise
            grievance.tracking_id = new_tracking_id()

    db.add(
        StatusHistory(
            grievance_id=grievance.id,
            status=GrievanceStatus.new,
            changed_by="system",
            note="Grievance created via intake",
        )
    )

    if embedding is not None:
        db.add(ComplaintVector(grievance_id=grievance.id, embedding=embedding))

    db.commit()
    db.refresh(grievance)
    grievance._merged = False  # transient flag, not persisted
    return grievance


def _to_intake_response(grievance: Grievance, db: Session) -> IntakeResponse:
    department_name = None
    if grievance.department_id:
        dept = db.get(Department, grievance.department_id)
        department_name = dept.name if dept else None

    return IntakeResponse(
        tracking_id=grievance.tracking_id,
        status=grievance.status,
        category=grievance.category,
        priority=grievance.priority,
        department=department_name,
        summary=grievance.description[:140],
        merged=getattr(grievance, "_merged", False),
    )


@router.post("/intake/web", response_model=IntakeResponse)
def intake_web(payload: WebIntakeRequest, db: Session = Depends(get_db)):
    if not payload.description.strip():
        raise HTTPException(status_code=422, detail="description must not be empty")

    grievance = _create_grievance(
        db,
        description=payload.description,
        original_text=payload.description,
        language=payload.language,
        address=payload.address,
        lat=payload.lat,
        lng=payload.lng,
    )
    return _to_intake_response(grievance, db)


def _extract_whatsapp_message(payload: dict) -> Optional[dict]:
    """
    Defensively parses a WhatsApp Business API webhook payload and pulls
    out the message id, sender id, and text body. Returns None if this
    payload isn't a text message we can handle yet (e.g. a status/delivery
    callback, or an audio/image message — those come in a later step).

    Phase 1 assumes text messages only, per the spec.
    """
    try:
        entry = payload.get("entry", [])[0]
        change = entry.get("changes", [])[0]
        value = change.get("value", {})
        messages = value.get("messages")
        if not messages:
            return None  # e.g. a delivery/read status callback, not a message

        message = messages[0]
        if message.get("type") != "text":
            return None  # audio/image handled in a later phase

        message_id = message.get("id")
        whatsapp_id = message.get("from")
        text = (message.get("text") or {}).get("body")

        if not message_id or not text:
            return None

        return {"message_id": message_id, "whatsapp_id": whatsapp_id, "text": text}
    except (AttributeError, IndexError, TypeError):
        return None


@router.post("/intake/whatsapp/webhook")
def intake_whatsapp_webhook(payload: dict = Body(...), db: Session = Depends(get_db)):
    parsed = _extract_whatsapp_message(payload)
    if parsed is None:
        # Not a text message we handle yet (status callback, unsupported
        # media type, malformed payload, ...). Ack with 200 and do nothing,
        # same as WhatsApp expects for any webhook it doesn't need retried.
        return {"ok": True}

    message_id = parsed["message_id"]

    # Idempotency: atomically claim this message_id. If it's already been
    # processed, INSERT will violate the unique constraint and we return
    # 200 having done nothing else, per the spec. Doing this as an
    # insert-and-catch (rather than check-then-insert) avoids a race
    # condition between two nearly-simultaneous deliveries of the same
    # webhook, which WhatsApp does occasionally send.
    try:
        db.add(ProcessedMessage(message_id=message_id))
        db.flush()
    except IntegrityError:
        db.rollback()
        return {"ok": True}

    whatsapp_id = parsed["whatsapp_id"]
    user = None
    if whatsapp_id:
        user = db.query(User).filter(User.whatsapp_id == whatsapp_id).first()
        if user is None:
            user = User(whatsapp_id=whatsapp_id)
            db.add(user)
            db.flush()

    try:
        grievance = _create_grievance(
            db,
            description=parsed["text"],
            original_text=parsed["text"],
            language=None,
            address=None,
            lat=None,
            lng=None,
            user_id=user.id if user else None,
        )
    except Exception:
        db.rollback()
        raise
    return _to_intake_response(grievance, db)
