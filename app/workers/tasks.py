from celery import current_task
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Any

from app.core.celery_app import celery_app
from app.services.openai_service import openai_service
from app.schemas.text_schemas import TextProcessingType, TaskStatus

logger = logging.getLogger(__name__)

@celery_app.task(bind=True, name="process_text")
def process_text_task(self, text: str, processing_type: str, user_id: str, options: Dict[str, Any] = None):
    """
    Background task to process text using OpenAI
    """
    task_id = self.request.id
    
    try:
        # Update task status
        logger.info(f"Starting text processing task {task_id} for user {user_id}")
        
        # Update progress
        self.update_state(
            state="PROCESSING",
            meta={
                "status": "processing", 
                "progress": 80,
                "message": "Processing complete, finalizing..."
            }
        )
        
        # Calculate metrics
        original_word_count = len(text.split())
        processed_word_count = len(processed_text.split())
        
        # Final result
        result = {
            "status": "completed",
            "progress": 100,
            "result": {
                "original_text": text,
                "processed_text": processed_text,
                "processing_type": processing_type,
                "word_count_original": original_word_count,
                "word_count_processed": processed_word_count,
                "processing_time": (datetime.utcnow() - datetime.fromisoformat(self.request.eta or datetime.utcnow().isoformat())).total_seconds() if self.request.eta else 0,
            },
            "message": "Text processing completed successfully"
        }
        
        logger.info(f"Task {task_id} completed successfully")
        return result
        
    except Exception as exc:
        logger.error(f"Task {task_id} failed: {str(exc)}")
        
        # Update task state with error
        self.update_state(
            state="FAILURE",
            meta={
                "status": "failed",
                "progress": 0,
                "error": str(exc),
                "message": "Text processing failed"
            }
        )
        
        # Re-raise the exception so Celery marks it as failed
        raise exc

@celery_app.task(name="cleanup_expired_tasks")
def cleanup_expired_tasks():
    """
    Periodic task to clean up expired results from Redis
    """
    try:
        # This would typically involve cleaning up old results from Redis
        # For now, just log that the cleanup ran
        logger.info("Cleanup task executed")
        return {"message": "Cleanup completed", "timestamp": datetime.utcnow().isoformat()}
    
    except Exception as exc:
        logger.error(f"Cleanup task failed: {str(exc)}")
        raise exc

@celery_app.task(name="health_check")
def health_check_task():
    """
    Simple health check task for monitoring
    """
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "message": "Worker is running"
    }
    self.update_state(
        state="PROCESSING",
        meta={
            "status": "processing", 
            "progress": 10,
            "message": "Initializing text processing..."
        }
    )
    
    # Convert string back to enum
    processing_type_enum = TextProcessingType(processing_type)
    
    # Simulate progress updates
    self.update_state(
        state="PROCESSING",
        meta={
            "status": "processing", 
            "progress": 30,
            "message": "Sending to AI service..."
        }
    )
    
    # Process text (we need to run async function in sync context)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        processed_text = loop.run_until_complete(
            openai_service.process_text(text, processing_type_enum, options or {})
        )
    finally:
        loop.close()
    
    # Update progress