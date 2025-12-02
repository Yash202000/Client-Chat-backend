from sqlalchemy.orm import Session, joinedload
from app.models import team_membership as models_team_membership, user as models_user, team as models_team
from app.schemas import team_membership as schemas_team_membership

def add_member_to_team(db: Session, team_id: int, user_id: int, company_id: int, role: str = "member"):
    # Check if user and team exist and belong to the same company
    user = db.query(models_user.User).filter(models_user.User.id == user_id, models_user.User.company_id == company_id).first()
    team = db.query(models_team.Team).filter(models_team.Team.id == team_id, models_team.Team.company_id == company_id).first()

    if not user or not team:
        return None # Or raise an exception

    db_membership = models_team_membership.TeamMembership(
        user_id=user_id,
        team_id=team_id,
        company_id=company_id,
        role=role
    )
    db.add(db_membership)
    db.commit()
    db.refresh(db_membership)
    return db_membership

def remove_member_from_team(db: Session, team_id: int, user_id: int, company_id: int):
    db_membership = db.query(models_team_membership.TeamMembership).options(
        joinedload(models_team_membership.TeamMembership.user)
    ).filter(
        models_team_membership.TeamMembership.team_id == team_id,
        models_team_membership.TeamMembership.user_id == user_id,
        models_team_membership.TeamMembership.company_id == company_id
    ).first()

    if db_membership:
        # Eagerly access the user relationship before deleting
        _ = db_membership.user
        db.delete(db_membership)
        db.commit()

    return db_membership

def get_team_members(db: Session, team_id: int, company_id: int):
    return db.query(models_user.User).join(models_team_membership.TeamMembership).filter(
        models_team_membership.TeamMembership.team_id == team_id,
        models_team_membership.TeamMembership.company_id == company_id
    ).all()

def update_member_role(db: Session, team_id: int, user_id: int, role: str, company_id: int):
    db_membership = db.query(models_team_membership.TeamMembership).filter(
        models_team_membership.TeamMembership.team_id == team_id,
        models_team_membership.TeamMembership.user_id == user_id,
        models_team_membership.TeamMembership.company_id == company_id
    ).first()

    if db_membership:
        db_membership.role = role
        db.commit()
        db.refresh(db_membership)
        
    return db_membership

def get_team_membership(db: Session, membership_id: int, company_id: int):
    return db.query(models_team_membership.TeamMembership).filter(models_team_membership.TeamMembership.id == membership_id, models_team_membership.TeamMembership.company_id == company_id).first()

def get_team_memberships_by_team(db: Session, team_id: int, company_id: int):
    return db.query(models_team_membership.TeamMembership).filter(models_team_membership.TeamMembership.team_id == team_id, models_team_membership.TeamMembership.company_id == company_id).all()

def get_team_memberships_by_user(db: Session, user_id: int, company_id: int):
    return db.query(models_team_membership.TeamMembership).filter(models_team_membership.TeamMembership.user_id == user_id, models_team_membership.TeamMembership.company_id == company_id).all()

def create_team_membership(db: Session, membership: schemas_team_membership.TeamMembershipCreate, company_id: int):
    db_membership = models_team_membership.TeamMembership(**membership.dict(), company_id=company_id)
    db.add(db_membership)
    db.commit()
    db.refresh(db_membership)
    return db_membership

def update_team_membership(db: Session, membership_id: int, membership: schemas_team_membership.TeamMembershipUpdate, company_id: int):
    db_membership = get_team_membership(db, membership_id, company_id)
    if db_membership:
        for key, value in membership.model_dump(exclude_unset=True).items():
            setattr(db_membership, key, value)
        db.commit()
        db.refresh(db_membership)
    return db_membership

def delete_team_membership(db: Session, membership_id: int, company_id: int):
    db_membership = get_team_membership(db, membership_id, company_id)
    if db_membership:
        db.delete(db_membership)
        db.commit()
    return db_membership

def is_user_in_team(db: Session, user_id: int, team_id: int) -> bool:
    return db.query(models_team_membership.TeamMembership).filter(
        models_team_membership.TeamMembership.user_id == user_id,
        models_team_membership.TeamMembership.team_id == team_id
    ).first() is not None


# Agent pool management methods for handoff functionality

def get_available_team_members(db: Session, team_id: int, company_id: int):
    """Get all available team members (is_available=True and not overloaded)"""
    return db.query(models_team_membership.TeamMembership).join(models_user.User).filter(
        models_team_membership.TeamMembership.team_id == team_id,
        models_team_membership.TeamMembership.company_id == company_id,
        models_team_membership.TeamMembership.is_available == True,
        models_user.User.presence_status.in_(['online', 'available']),
        models_team_membership.TeamMembership.current_session_count < models_team_membership.TeamMembership.max_concurrent_sessions
    ).all()


def update_member_availability(db: Session, membership_id: int, is_available: bool, company_id: int):
    """Update agent availability status"""
    db_membership = get_team_membership(db, membership_id, company_id)
    if db_membership:
        db_membership.is_available = is_available
        db.commit()
        db.refresh(db_membership)
    return db_membership


def increment_session_count(db: Session, membership_id: int, company_id: int):
    """Increment the current session count for a team member"""
    db_membership = get_team_membership(db, membership_id, company_id)
    if db_membership:
        db_membership.current_session_count += 1
        db.commit()
        db.refresh(db_membership)
    return db_membership


def decrement_session_count(db: Session, membership_id: int, company_id: int):
    """Decrement the current session count for a team member"""
    db_membership = get_team_membership(db, membership_id, company_id)
    if db_membership and db_membership.current_session_count > 0:
        db_membership.current_session_count -= 1
        db.commit()
        db.refresh(db_membership)
    return db_membership


def update_member_priority(db: Session, membership_id: int, priority: int, company_id: int):
    """Update agent priority for assignment"""
    db_membership = get_team_membership(db, membership_id, company_id)
    if db_membership:
        db_membership.priority = priority
        db.commit()
        db.refresh(db_membership)
    return db_membership


def update_member_workload_limits(db: Session, membership_id: int, max_concurrent_sessions: int, company_id: int):
    """Update maximum concurrent sessions for a team member"""
    db_membership = get_team_membership(db, membership_id, company_id)
    if db_membership:
        db_membership.max_concurrent_sessions = max_concurrent_sessions
        db.commit()
        db.refresh(db_membership)
    return db_membership