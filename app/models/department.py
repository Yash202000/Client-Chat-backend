from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import relationship
from app.core.database import Base


class Department(Base):
    __tablename__ = "departments"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    is_active = Column(Boolean, nullable=False, server_default="true")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    node_assignments = relationship("DepartmentNodeAssignment", back_populates="department", cascade="all, delete-orphan")
    user_memberships = relationship("DepartmentUserMembership", back_populates="department", cascade="all, delete-orphan")


class DepartmentNodeAssignment(Base):
    """Which hierarchy nodes (locations, classifications) this department covers."""
    __tablename__ = "department_node_assignments"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    department_id = Column(Integer, ForeignKey("departments.id", ondelete="CASCADE"), nullable=False)
    node_id = Column(Integer, ForeignKey("hierarchy_nodes.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    department = relationship("Department", back_populates="node_assignments")

    __table_args__ = (
        UniqueConstraint("department_id", "node_id", name="uq_dept_node"),
    )


class DepartmentUserMembership(Base):
    """Users inside a department with a role (agent/supervisor/approver/manager)."""
    __tablename__ = "department_user_memberships"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    department_id = Column(Integer, ForeignKey("departments.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role = Column(String, nullable=False, server_default="agent")
    created_at = Column(DateTime, server_default=func.now())

    department = relationship("Department", back_populates="user_memberships")

    __table_args__ = (
        UniqueConstraint("department_id", "user_id", "role", name="uq_dept_user_role"),
    )
