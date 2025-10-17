from pydantic import BaseModel

class TemporaryDocument(BaseModel):
    document_id: str
    text_content: str

    class Config:
        orm_mode = True
