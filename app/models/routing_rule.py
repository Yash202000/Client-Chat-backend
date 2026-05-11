from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from datetime import datetime
from app.core.database import Base


class RoutingRule(Base):
    """
    Rule-based auto-assignment for tickets, leads, and deals.
    Rules are evaluated in priority order; first match wins.
    """
    __tablename__ = "routing_rules"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)

    entity_type = Column(String, nullable=False, index=True)  # ticket|lead|deal
    name = Column(String, nullable=False)
    priority = Column(Integer, nullable=False, default=0)  # lower = evaluated first

    # When to fire: on_create | on_transition | both
    trigger = Column(String, nullable=False, default="on_create")
    # Optional: only fire when this specific transition is executed
    trigger_transition_id = Column(Integer, ForeignKey("ticket_transitions.id"), nullable=True)

    # Conditions: list of {field, operator, value}
    # field examples: "priority", "source", "tags", "custom_fields.tier", "issue_type_id"
    # operator: eq|neq|in|not_in|contains|gte|lte|exists
    conditions = Column(JSONB, nullable=True)  # [] means "match all"

    # What to do when conditions match
    # assign_to_user | assign_round_robin | assign_by_skill | assign_to_queue | no_action
    action_type = Column(String, nullable=False, default="assign_to_user")
    # For assign_to_user:      {user_id: int}
    # For assign_round_robin:  {team_id: int}
    # For assign_by_skill:     {skill: str, team_id: int, fallback_user_id?: int}
    # For assign_to_queue:     {queue_name: str}
    action_config = Column(JSONB, nullable=True)

    is_active = Column(Boolean, default=True, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    company = relationship("Company", backref="routing_rules")
    trigger_transition = relationship("TicketTransition", foreign_keys=[trigger_transition_id])


class RoutingRoundRobinState(Base):
    """
    Tracks which agent was last assigned per routing rule so round-robin stays fair.
    """
    __tablename__ = "routing_round_robin_state"

    id = Column(Integer, primary_key=True, index=True)
    rule_id = Column(Integer, ForeignKey("routing_rules.id"), nullable=False, unique=True, index=True)
    last_assigned_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    last_assigned_at = Column(DateTime, nullable=True)

    rule = relationship("RoutingRule", backref="round_robin_state")
    last_assigned_user = relationship("User", foreign_keys=[last_assigned_user_id])
