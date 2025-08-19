from typing import Optional
from datetime import datetime
from pydantic import BaseModel, EmailStr, validator

class Tone(BaseModel):
    id: str
    name: str
    description: str
    preview: str


class ContentTemplate(BaseModel):
    id: str
    title: str
    description: str
    preview: str
    category: str
    icon: str





