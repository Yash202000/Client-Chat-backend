from sqlalchemy import Column, Integer, String, JSON, ForeignKey
from sqlalchemy.orm import relationship
from app.core.database import Base

class Contact(Base):
    __tablename__ = "contacts"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=True)
    name = Column(String, index=True, nullable=True)
    phone_number = Column(String, nullable=True)
    custom_attributes = Column(JSON, nullable=True)
    
    company_id = Column(Integer, ForeignKey("companies.id"))
    company = relationship("Company", back_populates="contacts")
    
    chat_messages = relationship("ChatMessage", back_populates="contact")

# Add back-population to Company model
from app.models.company import Company
Company.contacts = relationship("Contact", order_by=Contact.id, back_populates="company")
