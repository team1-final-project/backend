from sqlalchemy.orm import Session
from app.models.member import Member


def get_member_by_email(db: Session, email: str) -> Member | None:
    return db.query(Member).filter(Member.email == email).first()


def get_member_by_social(db: Session, social_type: str, social_id: str) -> Member | None:
    return (
        db.query(Member)
        .filter(
            Member.social_type == social_type,
            Member.social_id == social_id,
        )
        .first()
    )


def create_member(db: Session, member: Member) -> Member:
    db.add(member)
    db.commit()
    db.refresh(member)
    return member


def update_member(db: Session, member: Member) -> Member:
    db.add(member)
    db.commit()
    db.refresh(member)
    return member