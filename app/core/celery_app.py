from celery import Celery
from app.core.config import settings

# Create Celery instance
celery_app = Celery(
    "clearify",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.workers.tasks"]
)

# Celery configuration
celery_app.conf.update(
    # Serialization
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    
    # Results
    result_expires=3600,  # 1 hour
    result_backend_transport_options={
        "master_name": "mymaster",
        "visibility_timeout": 3600,
    },
    
    # Task routing
    task_routes={
        "app.workers.tasks.process_text": {"queue": "text_processing"},
        "app.workers.tasks.humanize_text": {"queue": "text_processing"},
    },
    
    # Task execution
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    
    # Timezone
    timezone="UTC",
    enable_utc=True,
)

# Optional: Configure Celery beat schedule (for periodic tasks)
celery_app.conf.beat_schedule = {
    "cleanup-expired-tasks": {
        "task": "app.workers.tasks.cleanup_expired_tasks",
        "schedule": 3600.0,  # Every hour
    },
}