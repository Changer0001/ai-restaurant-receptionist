"""Restaurant knowledge-base (RAG document) schemas."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class KnowledgeDocumentRead(BaseModel):
    id: str
    restaurant_id: str
    title: str
    content: str
    document_type: str
    source: Optional[str]
    is_active: bool
    chunk_count: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class KnowledgeSearchResult(BaseModel):
    """One retrieved chunk, returned by the internal search/verification endpoint."""

    document_id: str
    content: str
    similarity: float = Field(ge=0.0, le=1.0)
    document_type: str
    source: Optional[str]
