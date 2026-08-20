"""
MOCK notification dispatch.

Writes an entry to `notifications_log` describing what *would* have
been sent, without actually calling any real provider (WhatsApp
Business API, SMS gateway, email service, etc.).

TODO: replace the body of send_notification with a real call into
whichever notification provider the team wires up, keeping the same
signature so callers (scheduler.py, routers/admin.py) don't need to
change.
"""
import logging

from sqlalchemy.orm import Session

from app.models import Grievance, NotificationLog

logger = logging.getLogger("grievanceai.notifications")


def send_notification(db: Session, *, grievance: Grievance, channel: str, message: str) -> NotificationLog:
    """
    MOCK: logs the notification instead of actually sending it, and marks
    it "sent" since there's no real provider yet. Does NOT call db.commit()
    — the caller controls the transaction boundary so this can be written
    atomically alongside the escalation/status_history rows it accompanies.
    """
    log_entry = NotificationLog(
        grievance_id=grievance.id,
        channel=channel,
        message=message,
        status="sent",  # mocked; a real integration would reflect the provider's response
    )
    db.add(log_entry)
    logger.info("MOCK notification [%s] for %s: %s", channel, grievance.tracking_id, message)
    return log_entry
