from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum

class TaskStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

class TextProcessingType(str, Enum):
    HUMANIZER = "humanizer"
    PROFESSIONAL = "professional"
    STYLE = "style"
    GRAMMAR = "grammar"

class TextProcessingRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=10000, description="Text to process")
    processing_type: TextProcessingType = Field(default=TextProcessingType.HUMANIZER)
    options: Optional[Dict[str, Any]] = Field(default={}, description="Additional processing options")
    
    @validator('text')
    def text_must_not_be_empty(cls, v):
        if not v or not v.strip():
            raise ValueError('Text cannot be empty')
        return v.strip()

class TextProcessingResponse(BaseModel):
    task_id: str
    status: TaskStatus
    message: str
    estimated_completion: Optional[datetime] = None

class TaskStatusResponse(BaseModel):
    task_id: str
    status: TaskStatus
    progress: Optional[int] = Field(default=0, ge=0, le=100)
    result: Optional[str] = None
    error: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    estimated_completion: Optional[datetime] = None

class ProcessedTextResult(BaseModel):
    original_text: str
    processed_text: str
    processing_type: TextProcessingType
    word_count_original: int
    word_count_processed: int
    processing_time: float
    improvements: Optional[List[str]] = None

class TaskListResponse(BaseModel):
    tasks: List[TaskStatusResponse]
    total: int
    page: int
    page_size: int