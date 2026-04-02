from sqlalchemy.orm import Session
from app.models.email_verification import EmailVerification


def create_email_verification(
    db: Session,
    verification: EmailVerification,
) -> EmailVerification:
    db.add(verification)
    db.commit()
    db.refresh(verification)
    return verification


def get_latest_pending_verification(
    db: Session,
    email: str,
    purpose: str = "SIGNUP",
) -> EmailVerification | None:
    return (
        db.query(EmailVerification)
        .filter(
            EmailVerification.email == email,
            EmailVerification.purpose == purpose,
            EmailVerification.verified_at.is_(None),
        )
        .order_by(EmailVerification.id.desc())
        .first()
    )


def update_email_verification(
    db: Session,
    verification: EmailVerification,
) -> EmailVerification:
    db.add(verification)
    db.commit()
    db.refresh(verification)
    return verification