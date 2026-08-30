"""Restaurant FAQ schemas."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class FAQCreate(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    answer: str = Field(min_length=1)
    category: Optional[str] = Field(default=None, max_length=100)
    is_active: bool = True


class FAQUpdate(BaseModel):
    question: Optional[str] = Field(default=None, min_length=1, max_length=500)
    answer: Optional[str] = Field(default=None, min_length=1)
    category: Optional[str] = Field(default=None, max_length=100)
    is_active: Optional[bool] = None


class FAQRead(BaseModel):
    id: str
    restaurant_id: str
    question: str
    answer: str
    category: Optional[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
