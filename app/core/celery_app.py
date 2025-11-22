import os
import ssl
from celery import Celery
from app.core.config import settings
from celery.schedules import crontab

# Configurazione SSL per Redis
def get_redis_ssl_config():
    """Configurazione SSL per connessioni Redis"""
    if hasattr(settings, 'redis_url') and settings.redis_url.startswith('rediss://'):
        return {
            'ssl_cert_reqs': ssl.CERT_REQUIRED,
            'ssl_ca_certs': os.getenv('SSL_CA_PATH', '/app/certs/ca.crt'),
            'ssl_certfile': os.getenv('SSL_CERT_PATH', '/app/certs/client.crt'),
            'ssl_keyfile': os.getenv('SSL_KEY_PATH', '/app/certs/client.key'),
            'ssl_check_hostname': False,  # Disabilita per certificati self-signed
        }
    return {}

# URL Redis con parametri SSL per Celery
def get_redis_url_with_ssl(url):
    """Costruisce URL Redis con parametri SSL richiesti da Celery"""
    if not url:
        return url
        
    # Aggiungi password se non presente
    password = os.getenv('REDIS_PASSWORD', 'clearify_redis_2024')
    
    if url.startswith('rediss://'):
        # Per TLS, aggiungi parametri SSL
        ssl_params = "?ssl_cert_reqs=required&ssl_check_hostname=false"
        if "?" in url:
            return f"{url}&ssl_cert_reqs=required&ssl_check_hostname=false"
        else:
            return f"{url}{ssl_params}"
    elif url.startswith('redis://'):
        # Per Redis standard, aggiungi password se non presente
        if '@' not in url and password:
            # Estrai host:port dalla URL
            host_port = url.replace('redis://', '')
            return f"redis://:{password}@{host_port}"
    
    return url

# Ottieni URLs con supporto SSL e password
broker_url = get_redis_url_with_ssl(settings.celery_broker_url)
result_backend_url = get_redis_url_with_ssl(settings.celery_result_backend)

# Create Celery instance
celery_app = Celery(
    "clearify",
    broker=broker_url,
    backend=result_backend_url,
    include=["app.workers.tasks"]
)

# Configurazione SSL per broker e backend
ssl_config = get_redis_ssl_config()

# Celery configuration
celery_app.conf.update(
    # URLs con SSL
    broker_url=broker_url,
    result_backend=result_backend_url,
    
    # Configurazioni SSL se necessarie
    broker_use_ssl=ssl_config if ssl_config else None,
    redis_backend_use_ssl=ssl_config if ssl_config else None,
    
    # Serialization
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    
    # Results
    result_expires=3600,  # 1 hour
    result_backend_transport_options={
        "master_name": "mymaster",
        "visibility_timeout": 3600,
        # Aggiungi SSL config se necessario
        **ssl_config
    } if ssl_config else {
        "master_name": "mymaster", 
        "visibility_timeout": 3600,
    },
    
    # Task routing
    task_routes={
        "app.workers.tasks.process_text": {"queue": "text_processing"},
        "app.workers.tasks.process_text_task": {"queue": "text_processing"},
        "app.workers.tasks.humanize_text": {"queue": "text_processing"},
        "app.workers.tasks.handle_webhook_event_task": {"queue": "webhooks"},
        "app.workers.tasks.send_email_task": {"queue": "emails"},
        "app.workers.tasks.process_payment_task": {"queue": "payments"},
        "send_daily_report_task": {"queue": "reports"},
        "process_expiring_subscriptions": {"queue": "subscriptions"},
        "process_expired_subscriptions": {"queue": "subscriptions"},
        "process_free_user_deletions": {"queue": "subscriptions"},
        #"cleanup-old-payment-intents-task": {"queue": "cleanup"},
        "cleanup_tables_task": {"queue": "cleanup"},
    },
    
    # Task execution
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=1000,
    
    # Retry configuration
    task_default_retry_delay=60,
    task_max_retries=3,
    
    # Timezone
    timezone=os.getenv('CELERY_TIMEZONE', 'Europe/Rome'),
    enable_utc=True,
    
    # Connection reliability
    broker_connection_retry_on_startup=True,
    broker_connection_retry=True,
    
    # Health check
    worker_send_task_events=True,
    task_send_sent_event=True,
)

# Configure Celery beat schedule (for periodic tasks)
celery_app.conf.beat_schedule = {
    # Cleanup Task
    "cleanup-old-records-task": {
        "task": "cleanup_tables_task",
        "schedule": crontab(minute='*/3')
    },
    # Analytics Task
    "send-daily-report-task": {
        "task": "send_daily_report_task",
        "schedule": crontab(minute=0, hour=2) #crontab()
    },
    # Payments Tasks
    "process-expiring-subscriptions": {
        "task": "process_expiring_subscriptions",
        "schedule": crontab()
    },
    "process-expired-subscriptions": {
            "task": "process_expired_subscriptions",
            "schedule": crontab(minute='*/2')
    },
    "process-free-user-deletions": {
            "task": "process_free_user_deletions",
            "schedule": crontab(minute='*/2')
    },
}

# Log della configurazione per debug
import logging
logger = logging.getLogger("clearify_analytics")

logger.info(f"Celery broker URL: {broker_url}")
logger.info(f"Celery result backend: {result_backend_url}")
logger.info(f"SSL configuration enabled: {bool(ssl_config)}")
if ssl_config:
    logger.info(f"SSL CA certs: {ssl_config.get('ssl_ca_certs', 'Not set')}")
    logger.info(f"SSL cert file: {ssl_config.get('ssl_certfile', 'Not set')}")
    logger.info(f"SSL key file: {ssl_config.get('ssl_keyfile', 'Not set')}")