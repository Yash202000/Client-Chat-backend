from sqlalchemy import Column, Integer, String, Text, JSON, ForeignKey, Table
from sqlalchemy.orm import relationship
from app.core.database import Base

agent_tools = Table(
    'agent_tools',
    Base.metadata,
    Column('agent_id', Integer, ForeignKey('agents.id'), primary_key=True),
    Column('tool_id', Integer, ForeignKey('tools.id'), primary_key=True)
)

class Tool(Base):
    __tablename__ = "tools"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    description = Column(String, nullable=True)
    parameters = Column(JSON) # Stores JSON schema for parameters
    code = Column(Text) # Stores the Python code for the tool
    company_id = Column(Integer, ForeignKey("companies.id"))
    configuration = Column(JSON, nullable=True) # Stores tool configuration

    company = relationship("Company", back_populates="tools")
    agents = relationship("Agent", secondary=agent_tools, back_populates="tools")
