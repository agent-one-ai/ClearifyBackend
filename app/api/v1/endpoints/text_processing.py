from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from typing import Dict, Any
import uuid
import logging
from datetime import datetime

from app.schemas.text_schemas import (
    TextProcessingRequest, 
    TextProcessingResponse, 
    TaskStatusResponse,
    TaskStatus,
    ProcessedTextResult
)
from app.workers.tasks import process_text_task
from app.core.celery_app import celery_app
from app.services.openai_service import openai_service

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/process", response_model=TextProcessingResponse)
async def process_text(
    request: TextProcessingRequest,
    background_tasks: BackgroundTasks,
    # current_user = Depends(get_current_user),  # Add auth later
):
    """
    Start text processing task
    """
    try:
        # Generate task ID
        task_id = str(uuid.uuid4())
        
        # Get text analysis for estimated completion time
        analysis = await openai_service.get_text_analysis(request.text)
        estimated_completion = datetime.utcnow().replace(microsecond=0) + \
                             timedelta(seconds=analysis["estimated_processing_time"])
        
        # Start Celery task
        task = process_text_task.apply_async(
            args=[
                request.text,
                request.processing_type.value,
                "anonymous",  # Replace with current_user.id when auth is added
                request.options
            ],
            task_id=task_id
        )
        
        logger.info(f"Started text processing task {task_id}")
        
        return TextProcessingResponse(
            task_id=task_id,
            status=TaskStatus.PENDING,
            message=f"Text processing started. Estimated completion in {analysis['estimated_processing_time']} seconds.",
            estimated_completion=estimated_completion
        )
        
    except Exception as e:
        logger.error(f"Failed to start text processing task: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to start text processing: {str(e)}"
        )

@router.get("/task/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(task_id: str):
    """
    Get status of a text processing task
    """
    try:
        # Get task result from Celery
        result = celery_app.AsyncResult(task_id)
        
        if not result:
            raise HTTPException(
                status_code=404,
                detail="Task not found"
            )
        
        # Map Celery states to our TaskStatus
        status_mapping = {
            "PENDING": TaskStatus.PENDING,
            "PROCESSING": TaskStatus.PROCESSING,
            "SUCCESS": TaskStatus.COMPLETED,
            "FAILURE": TaskStatus.FAILED,
            "RETRY": TaskStatus.PROCESSING,
            "REVOKED": TaskStatus.FAILED
        }
        
        status = status_mapping.get(result.state, TaskStatus.PENDING)
        
        # Get additional info from task meta
        task_info = result.info or {}
        
        response_data = {
            "task_id": task_id,
            "status": status,
            "created_at": datetime.utcnow(),  # You might want to store this when creating tasks
            "updated_at": datetime.utcnow(),
            "progress": task_info.get("progress", 0 if status == TaskStatus.PENDING else 100),
        }
        
        # Add result if completed
        if status == TaskStatus.COMPLETED and "result" in task_info:
            response_data["result"] = task_info["result"]["processed_text"]
        
        # Add error if failed
        if status == TaskStatus.FAILED:
            response_data["error"] = task_info.get("error", str(result.info) if result.info else "Unknown error")
        
        return TaskStatusResponse(**response_data)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get task status for {task_id}: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get task status: {str(e)}"
        )

@router.get("/task/{task_id}/result", response_model=ProcessedTextResult)
async def get_task_result(task_id: str):
    """
    Get detailed result of a completed text processing task
    """
    try:
        result = celery_app.AsyncResult(task_id)
        
        if not result:
            raise HTTPException(status_code=404, detail="Task not found")
        
        if result.state != "SUCCESS":
            raise HTTPException(
                status_code=400,
                detail=f"Task is not completed yet. Current status: {result.state}"
            )
        
        task_result = result.info.get("result")
        if not task_result:
            raise HTTPException(status_code=404, detail="Task result not found")
        
        return ProcessedTextResult(**task_result)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get task result for {task_id}: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get task result: {str(e)}"
        )

@router.delete("/task/{task_id}")
async def cancel_task(task_id: str):
    """
    Cancel a pending or running task
    """
    try:
        celery_app.control.revoke(task_id, terminate=True)
        
        return {
            "message": f"Task {task_id} has been cancelled",
            "task_id": task_id,
            "status": "cancelled"
        }
        
    except Exception as e:
        logger.error(f"Failed to cancel task {task_id}: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to cancel task: {str(e)}"
        )

@router.get("/health")
async def health_check():
    """
    Health check endpoint for text processing service
    """
    try:
        # Test Celery connection
        inspector = celery_app.control.inspect()
        active_tasks = inspector.active()
        
        # Test OpenAI service
        openai_status = "ok" if openai_service else "not configured"
        
        return {
            "status": "healthy",
            "celery_workers": len(active_tasks) if active_tasks else 0,
            "openai_service": openai_status,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }