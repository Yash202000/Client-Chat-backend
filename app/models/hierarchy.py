from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from app.core.database import Base


class HierarchyType(Base):
    """Defines a dimension like 'Location', 'Classification', 'Department Category'."""
    __tablename__ = "hierarchy_types"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    is_active = Column(Boolean, nullable=False, server_default="true")
    position = Column(Integer, nullable=False, server_default="0")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    nodes = relationship("HierarchyNode", back_populates="type", cascade="all, delete-orphan")


class HierarchyNode(Base):
    """A node in a hierarchy tree (e.g. Country > State > City > Ward)."""
    __tablename__ = "hierarchy_nodes"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    type_id = Column(Integer, ForeignKey("hierarchy_types.id", ondelete="CASCADE"), nullable=False)
    parent_id = Column(Integer, ForeignKey("hierarchy_nodes.id", ondelete="CASCADE"), nullable=True)

    name = Column(String, nullable=False)
    # Stable slug used in custom_field values and routing conditions
    code = Column(String, nullable=False)
    # Materialized path: dot-joined ancestor IDs + self, e.g. "1.5.12.47"
    # Enables ancestor matching with a simple LIKE query
    path = Column(String, nullable=False)

    metadata_ = Column("metadata", JSONB, nullable=True)
    position = Column(Integer, nullable=False, server_default="0")
    is_active = Column(Boolean, nullable=False, server_default="true")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    type = relationship("HierarchyType", back_populates="nodes")
    # Self-referential tree: remote_side tells SQLAlchemy which side is the "one"
    parent = relationship(
        "HierarchyNode",
        remote_side="HierarchyNode.id",
        foreign_keys=[parent_id],
        back_populates="children",
    )
    children = relationship(
        "HierarchyNode",
        foreign_keys=[parent_id],
        back_populates="parent",
    )
    user_assignments = relationship("UserNodeAssignment", back_populates="node", cascade="all, delete-orphan")
    team_assignments = relationship("TeamNodeAssignment", back_populates="node", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("company_id", "type_id", "code", name="uq_hierarchy_node_code"),
    )


class UserNodeAssignment(Base):
    """Assigns a hierarchy node (jurisdiction) to a user."""
    __tablename__ = "user_node_assignments"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    node_id = Column(Integer, ForeignKey("hierarchy_nodes.id", ondelete="CASCADE"), nullable=False)
    team_id = Column(Integer, ForeignKey("teams.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    node = relationship("HierarchyNode", back_populates="user_assignments")

    __table_args__ = (
        UniqueConstraint("user_id", "node_id", name="uq_user_node"),
    )


class TeamNodeAssignment(Base):
    """Assigns a hierarchy node (jurisdiction) to a team/department."""
    __tablename__ = "team_node_assignments"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    team_id = Column(Integer, ForeignKey("teams.id", ondelete="CASCADE"), nullable=False)
    node_id = Column(Integer, ForeignKey("hierarchy_nodes.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    node = relationship("HierarchyNode", back_populates="team_assignments")

    __table_args__ = (
        UniqueConstraint("team_id", "node_id", name="uq_team_node"),
    )
