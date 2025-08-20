# 🚀 Clearify Workers Distribuiti - Guida Setup Completa

## 📋 Panoramica

Questa guida spiega come configurare worker Clearify distribuiti su dispositivi separati (Raspberry Pi, server cloud, ecc.) per scalare orizzontalmente il processing dei task.

### 🏗️ Architettura

```
🌐 Frontend (Next.js)
     ↓
🔄 Backend API (FastAPI) 
     ↓
📨 Redis Queue (Centrale)
     ↓ ↓ ↓
🤖 Worker 1   🤖 Worker 2   🤖 Worker N
(Server)      (Raspberry)    (Cloud)
```

---

## 🎯 Cosa abbiamo implementato

✅ **Worker distribuiti** - Processano task da una queue Redis centrale  
✅ **Multi-worker paralleli** - Più container worker per device  
✅ **Auto-restart** - Avvio automatico al boot  
✅ **Monitoring** - Logs colorati e status in tempo reale  
✅ **Load balancing** - Redis distribuisce automaticamente i task  
✅ **Specializzazione** - Worker dedicati per tipi di task specifici  

---

## 🔧 Setup Nuovo Worker - Quick Start

### 1️⃣ Prerequisiti

**Hardware supportato:**
- Raspberry Pi 4 (4GB+ RAM consigliato)
- Server Linux (Ubuntu/Debian)
- Container Cloud (AWS/GCP/Azure)

**Software richiesto:**
- Docker
- SSH access
- Connessione di rete al server Redis

### 2️⃣ Preparazione Files (Server Principale)

```bash
# Nel server principale dove gira il backend
cd /path/to/ClearifyBackend

# Crea pacchetto per nuovo worker
tar -czf clearify-worker-package.tar.gz \
  --exclude=__pycache__ \
  --exclude=.git \
  --exclude=node_modules \
  --exclude='*.pyc' \
  app/ requirements.txt .env

# Trasferisci al nuovo device
scp clearify-worker-package.tar.gz user@NEW_DEVICE_IP:/home/user/
```

### 3️⃣ Setup Device Nuovo Worker

```bash
# Sul nuovo device
# 1. Installa Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER
newgrp docker

# 2. Estrai files
cd ~
tar -xzf clearify-worker-package.tar.gz
mkdir -p clearify-worker
mv app requirements.txt .env clearify-worker/
cd clearify-worker

# 3. Crea Dockerfile
cat > Dockerfile << 'EOF'
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY . .

RUN adduser --disabled-password --gecos '' appuser \
    && chown -R appuser:appuser /app
USER appuser

CMD ["celery", "-A", "app.core.celery_app", "worker", "--loglevel=info", "--queues=text_processing,webhooks,payments,emails", "--concurrency=2"]
EOF
```

### 4️⃣ Configurazione Redis

```bash
# Modifica .env per puntare al server Redis principale
nano .env

# Trova e modifica queste righe:
# REDIS_URL=redis://MAIN_SERVER_IP:6379/0
# CELERY_BROKER_URL=redis://MAIN_SERVER_IP:6379/0  
# CELERY_RESULT_BACKEND=redis://MAIN_SERVER_IP:6379/0

# Sostituisci MAIN_SERVER_IP con l'IP del tuo server principale
sed -i 's/redis:\/\/redis:6379/redis:\/\/MAIN_SERVER_IP:6379\/0/g' .env
```

### 5️⃣ Script di Gestione Worker

```bash
# Scarica lo script di gestione multi-worker
curl -o multi-worker.sh https://gist.githubusercontent.com/YOUR_GIST_URL/multi-worker.sh

# OPPURE crea manualmente (vedi sezione Script)
nano multi-worker.sh

# Rendi eseguibile
chmod +x multi-worker.sh

# Configura IP Redis nello script
nano multi-worker.sh
# Modifica: REDIS_HOST="MAIN_SERVER_IP"
```

### 6️⃣ Build e Avvio

```bash
# Build immagine nativa
./multi-worker.sh start

# Verifica status
./multi-worker.sh status

# Controlla logs
./multi-worker.sh logs
```

### 7️⃣ Auto-Start al Boot

```bash
# Metodo 1: Systemd (consigliato)
sudo nano /etc/systemd/system/clearify-multi-worker.service

# Copia configurazione systemd (vedi sezione dedicata)

sudo systemctl daemon-reload
sudo systemctl enable clearify-multi-worker.service

# Metodo 2: Cron (alternativo)
crontab -e
# Aggiungi: @reboot sleep 60 && cd /home/user/clearify-worker && ./multi-worker.sh start
```

---

## 📄 File di Configurazione

### Script Multi-Worker (multi-worker.sh)

```bash
#!/bin/bash
# 🤖 Clearify Multi-Worker Manager

set -e

# ⚙️ CONFIGURAZIONI - MODIFICA QUESTI VALORI
BASE_WORKER_NAME="clearify-worker-device"
IMAGE_NAME="clearify-worker:local"
REDIS_HOST="192.168.1.109"  # 🔧 IP SERVER PRINCIPALE
NUM_WORKERS=3

# Configurazione worker specializzati
WORKER_CONFIGS=(
    "worker-1:text_processing:2"        # Text processing, 2 core
    "worker-2:payments,webhooks:1"      # Payments + webhooks, 1 core
    "worker-3:emails:1"                 # Email, 1 core
)

# [RESTO DELLO SCRIPT - vedi implementazione completa]
```

### Servizio Systemd

```ini
[Unit]
Description=Clearify Multi-Worker Container Service
Documentation=https://docs.docker.com/
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
User=USERNAME
Group=USERNAME
WorkingDirectory=/home/USERNAME/clearify-worker

ExecStartPre=/bin/bash -c 'until docker info; do sleep 1; done'
ExecStartPre=/bin/bash -c 'until ping -c1 REDIS_SERVER_IP; do sleep 5; done'
ExecStart=/home/USERNAME/clearify-worker/multi-worker.sh start
ExecStop=/home/USERNAME/clearify-worker/multi-worker.sh stop
ExecReload=/home/USERNAME/clearify-worker/multi-worker.sh restart

TimeoutStartSec=300
TimeoutStopSec=60
Restart=on-failure
RestartSec=30

[Install]
WantedBy=multi-user.target
```

---

## 🧪 Testing e Monitoring

### Test Funzionalità

```bash
# Test connessione Redis
./multi-worker.sh test

# Invio task di test (dal server principale)
redis-cli LPUSH text_processing '{
  "id": "test-'$(date +%s)'",
  "text": "Test worker distribuito",
  "template": "email",
  "userId": "test"
}'

# Monitoring worker
./multi-worker.sh logs
./multi-worker.sh status
```

### Monitoring Avanzato

```bash
# Status real-time
watch -n 2 './multi-worker.sh status'

# Logs specifici per worker
./multi-worker.sh logs 1  # Worker 1
./multi-worker.sh logs 2  # Worker 2

# Performance di sistema
docker stats
htop
```

---

## ⚙️ Configurazioni Avanzate

### Ottimizzazione per Hardware

**Raspberry Pi 4 (4GB):**
```bash
WORKER_CONFIGS=(
    "worker-1:text_processing:2"
    "worker-2:payments,emails:1"
)
```

**Raspberry Pi 4 (8GB):**
```bash
WORKER_CONFIGS=(
    "worker-1:text_processing:3"
    "worker-2:text_processing:2"
    "worker-3:payments,webhooks:1"
    "worker-4:emails:1"
)
```

**Server Cloud (2-4 vCPU):**
```bash
WORKER_CONFIGS=(
    "worker-1:text_processing:4"
    "worker-2:text_processing:3"
    "worker-3:payments,webhooks:2"
    "worker-4:emails:2"
)
```

### Specializzazione Queue

```bash
# Worker dedicato solo al text processing
WORKER_CONFIGS=(
    "text-worker:text_processing:4"
)

# Worker dedicato ai pagamenti
WORKER_CONFIGS=(
    "payment-worker:payments:2"
)

# Worker generico
WORKER_CONFIGS=(
    "general-worker:text_processing,emails,webhooks:3"
)
```

---

## 🚨 Troubleshooting

### Problemi Comuni

**1. Errore connessione Redis**
```bash
# Verifica IP e porta
ping REDIS_SERVER_IP
telnet REDIS_SERVER_IP 6379

# Controlla firewall
sudo ufw status
sudo ufw allow 6379  # Sul server Redis
```

**2. Worker non si avvia**
```bash
# Controlla logs Docker
docker logs clearify-worker-device-1

# Verifica risorse
free -h
docker system df
```

**3. Architettura incompatibile (ARM64 vs AMD64)**
```bash
# Força build nativo
docker build --platform linux/arm64 -t clearify-worker:local .
```

**4. Variabili ambiente non caricate**
```bash
# Verifica file .env
cat .env | grep -E "(REDIS|SUPABASE|OPENAI)"

# Test caricamento
source .env && echo "OK" || echo "ERROR"
```

### Recovery Commands

```bash
# Reset completo
./multi-worker.sh stop
docker system prune -f
./multi-worker.sh start

# Restart singolo worker
docker restart clearify-worker-device-1

# Rebuild da zero
docker rmi clearify-worker:local
./multi-worker.sh restart
```

---

## 📈 Scalabilità

### Aggiunta Nuovi Worker

1. **Replica la configurazione** su nuovo device
2. **Modifica WORKER_ID** per evitare conflitti
3. **Specializza le queue** in base alle necessità
4. **Monitora load balancing** con Redis

### Load Testing

```bash
# Dal server principale, invia burst di task
for i in {1..50}; do
  redis-cli LPUSH text_processing "{\"id\":\"load-test-$i\",\"text\":\"Test $i\",\"template\":\"email\"}"
done

# Monitora distribuzione del carico
redis-cli MONITOR | grep "text_processing"
```

---

## 🔐 Sicurezza

### Best Practices

- ✅ **Firewall configurato** - Solo porte necessarie aperte
- ✅ **SSH key-based auth** - No password authentication  
- ✅ **Docker rootless** - Container non privilegiati
- ✅ **Secrets in .env** - Mai hardcodare credenziali
- ✅ **Network isolato** - VPN o network privato per Redis
- ✅ **Monitoring logs** - Alert su errori critici

### Network Security

```bash
# Solo traffic interno alla rete
sudo ufw deny 6379  # Redis non esposto pubblicamente
sudo ufw allow from 192.168.1.0/24 to any port 6379

# VPN setup (consigliato per production)
# [Configurazione specifica del provider VPN]
```

---

## 📚 Risorse Aggiuntive

### Comandi Utili

```bash
# Status sistema completo
./multi-worker.sh status
docker stats --no-stream
free -h
df -h

# Backup configurazione
tar -czf worker-config-backup.tar.gz .env multi-worker.sh Dockerfile

# Update worker (pull nuove modifiche)
git pull  # Se usi git
./multi-worker.sh restart
```

### File Structure

```
~/clearify-worker/
├── multi-worker.sh          # Script principale
├── .env                     # Configurazioni
├── Dockerfile              # Build container
├── app/                     # Codice applicazione
├── requirements.txt         # Dipendenze Python
└── logs/                    # Logs (opzionale)
```

---

*Documento aggiornato: $(date)*  
*Versione: 1.0*  
*Team: Clearify Development*