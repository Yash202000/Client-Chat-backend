from sqlalchemy import Boolean, Column, Integer, String, Text, JSON, ForeignKey, Table
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
    name = Column(String, index=True)
    description = Column(String, nullable=True)
    
    # Tool type can be 'custom' or 'mcp'
    tool_type = Column(String, nullable=False, default="custom")
    
    # For custom tools
    parameters = Column(JSON, nullable=True)
    code = Column(Text, nullable=True)
    
    # For MCP connections
    mcp_server_url = Column(String, nullable=True)
    
    is_pre_built = Column(Boolean, default=False)
    company_id = Column(Integer, ForeignKey("companies.id"))
    configuration = Column(JSON, nullable=True)

    # Follow-up questions configuration for guided data collection
    follow_up_config = Column(JSON, nullable=True)

    company = relationship("Company", back_populates="tools")
    agents = relationship("Agent", secondary=agent_tools, back_populates="tools")
