# Flower Configuration File
# https://flower.readthedocs.io/en/latest/config.html

import os

# ================================
# Broker Configuration
# ================================
broker_api = os.getenv('CELERY_BROKER_URL', 'redis://:clearify_redis_2024@redis:6379')

# ================================
# Server Configuration
# ================================
port = int(os.getenv('FLOWER_PORT', '5555'))
address = os.getenv('FLOWER_ADDRESS', '0.0.0.0')

# URL prefix (se dietro reverse proxy con path /flower)
url_prefix = os.getenv('FLOWER_URL_PREFIX', 'flower')

# ================================
# Authentication
# ================================
# Basic authentication (formato: user:password)
basic_auth = [os.getenv('FLOWER_BASIC_AUTH', 'admin:admin123')]

# Alternative: OAuth2 con Google
# oauth2_key = os.getenv('GOOGLE_OAUTH2_CLIENT_ID', '')
# oauth2_secret = os.getenv('GOOGLE_OAUTH2_CLIENT_SECRET', '')
# oauth2_redirect_uri = os.getenv('GOOGLE_OAUTH2_REDIRECT_URI', 'https://localhost/flower/login')

# ================================
# Persistence
# ================================
# Abilita modalità persistent per salvare task history
persistent = os.getenv('FLOWER_PERSISTENT', 'True').lower() == 'true'
db = os.getenv('FLOWER_DB', '/data/flower.db')

# ================================
# Task Configuration
# ================================
# Numero massimo di task da mantenere in memoria
max_tasks = int(os.getenv('FLOWER_MAX_TASKS', '10000'))

# Purge offline workers dopo N secondi (default: 86400 = 24 ore)
purge_offline_workers = int(os.getenv('FLOWER_PURGE_OFFLINE_WORKERS', '3600'))

# ================================
# UI Configuration
# ================================
# Auto-refresh interval (in millisecondi)
auto_refresh = os.getenv('FLOWER_AUTO_REFRESH', 'True').lower() == 'true'

# Natural time display
natural_time = True

# Task columns da mostrare
tasks_columns = 'name,uuid,state,args,kwargs,result,received,started,runtime,worker'

# ================================
# Security
# ================================
# Certificate files (se SSL è gestito direttamente da Flower)
# certfile = os.getenv('FLOWER_CERTFILE', '')
# keyfile = os.getenv('FLOWER_KEYFILE', '')

# ================================
# Logging
# ================================
logging = 'INFO'

# ================================
# API Configuration
# ================================
# Abilita API endpoint (/api/workers, /api/tasks, etc.)
enable_events = True

# ================================
# Performance
# ================================
# Inspection timeout (secondi)
inspect_timeout = float(os.getenv('FLOWER_INSPECT_TIMEOUT', '10.0'))

# ================================
# Broker Options
# ================================
# Transport options per il broker
broker_options = {
    'visibility_timeout': 3600,
}

# ================================
# Custom Configuration
# ================================
# Timezone
timezone = os.getenv('CELERY_TIMEZONE', 'Europe/Rome')

# Configurazione specifica per Redis con password
if 'redis' in broker_api and '@' not in broker_api:
    redis_password = os.getenv('REDIS_PASSWORD', 'clearify_redis_2024')
    if redis_password:
        # Assicurati che la password sia nel formato corretto
        if broker_api.startswith('redis://'):
            host_port = broker_api.replace('redis://', '')
            broker_api = f"redis://:{redis_password}@{host_port}"

# ================================
# Development vs Production
# ================================
if os.getenv('ENVIRONMENT', 'development') == 'production':
    # In produzione, aumenta i limiti e abilita features di sicurezza
    max_tasks = 50000
    purge_offline_workers = 7200  # 2 ore

    # Disabilita debug mode
    debug = False
else:
    # In development, mantieni configurazione più permissiva
    debug = True
