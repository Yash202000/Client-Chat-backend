"""
Custom DOCX Document Loader for LangChain

This loader extracts text from Microsoft Word (.docx) files and creates
LangChain Document objects for use in knowledge base processing.
"""

from typing import List
import docx2txt
from langchain.schema import Document
from langchain.document_loaders.base import BaseLoader


class DOCXLoader(BaseLoader):
    """
    Load and parse DOCX files.

    Uses docx2txt to extract plain text from Word documents.
    Compatible with LangChain's document processing pipeline.
    """

    def __init__(self, file_path: str):
        """
        Initialize the DOCX loader.

        Args:
            file_path: Path to the .docx file to load
        """
        self.file_path = file_path

    def load(self) -> List[Document]:
        """
        Load and parse the DOCX file.

        Returns:
            List containing a single Document with extracted text

        Raises:
            Exception: If the file cannot be read or parsed
        """
        try:
            # Extract text from DOCX file
            text = docx2txt.process(self.file_path)

            if not text or not text.strip():
                raise ValueError(f"No text content found in DOCX file: {self.file_path}")

            # Create metadata
            metadata = {
                "source": self.file_path,
                "file_type": "docx"
            }

            # Return as LangChain Document
            return [Document(page_content=text, metadata=metadata)]

        except Exception as e:
            raise Exception(f"Error loading DOCX file {self.file_path}: {str(e)}")
