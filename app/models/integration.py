from sqlalchemy import Column, Integer, String, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from app.core.database import Base

class Integration(Base):
    __tablename__ = "integrations"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    type = Column(String, nullable=False, index=True)  # e.g., "whatsapp"
    enabled = Column(Boolean, default=True)
    
    # This will store the encrypted credentials as a single string/text block.
    # The vault_service will handle the encryption/decryption.
    credentials = Column(String, nullable=False)

    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    company = relationship("Company", back_populates="integrations")

# To make this relationship work, I also need to add the inverse to the Company model.
# I will do that in a subsequent step.
