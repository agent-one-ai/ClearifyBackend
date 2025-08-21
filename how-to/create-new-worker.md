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

# 🚀 Clearify Multi-Worker Manager per Raspberry Pi - AGGIORNATO
# Gestisce multipli worker container in parallelo con Redis autenticato

set -e

# ⚙️ Configurazioni AGGIORNATE
BASE_WORKER_NAME="clearify-worker-raspi"
IMAGE_NAME="clearify-worker:raspberry"
REDIS_HOST="192.168.1.109"  # 🔧 IP del tuo server
REDIS_PASSWORD="clearify_redis_2024"  # 🔧 Password Redis
NUM_WORKERS=3               # 🔧 Numero di worker (adatta in base alla RAM)

# Configurazione per worker - AGGIORNATA
WORKER_CONFIGS=(
    "worker-1:text_processing:2"           # Worker 1: text processing, 2 core
    "worker-2:payments,webhooks:1"         # Worker 2: payments + webhooks, 1 core  
    "worker-3:emails:1"                    # Worker 3: emails, 1 core
)

# 🎨 Colori
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}ℹ️  $1${NC}"; }
log_success() { echo -e "${GREEN}✅ $1${NC}"; }
log_warning() { echo -e "${YELLOW}⚠️  $1${NC}"; }
log_error() { echo -e "${RED}❌ $1${NC}"; }

# 🔍 Check system resources
check_resources() {
    local total_ram=$(free -m | awk 'NR==2{printf "%.0f", $2}')
    local available_ram=$(free -m | awk 'NR==2{printf "%.0f", $7}')
    local cpu_cores=$(nproc)
    
    log_info "📊 Risorse sistema:"
    echo "   RAM totale: ${total_ram}MB"
    echo "   RAM disponibile: ${available_ram}MB"
    echo "   CPU cores: ${cpu_cores}"
    echo "   Worker configurati: ${#WORKER_CONFIGS[@]}"
    
    # Check se ci sono risorse sufficienti
    local estimated_ram=$((${#WORKER_CONFIGS[@]} * 350))  # ~350MB per worker (aumentato)
    
    if [ $available_ram -lt $estimated_ram ]; then
        log_warning "RAM potrebbe non essere sufficiente (stimato: ${estimated_ram}MB)"
        log_info "Considera di ridurre NUM_WORKERS o ottimizzare la configurazione"
    else
        log_success "Risorse sufficienti per ${#WORKER_CONFIGS[@]} worker"
    fi
}

# 🧪 Test connessione Redis AGGIORNATO
test_redis_connection() {
    log_info "🔍 Test connessione Redis..."
    
    # Test connessione TCP
    if timeout 5 bash -c "</dev/tcp/${REDIS_HOST}/6379"; then
        log_success "Connessione TCP a Redis OK"
    else
        log_error "Impossibile connettersi a Redis su ${REDIS_HOST}:6379"
        log_info "Verifica che:"
        echo "  • Il server principale sia in esecuzione"
        echo "  • Redis sia esposto sulla porta 6379"
        echo "  • Il firewall permetta le connessioni"
        exit 1
    fi
    
    # Test autenticazione Redis (se docker è disponibile)
    if command -v docker &> /dev/null; then
        log_info "Test autenticazione Redis..."
        if docker run --rm redis:7-alpine redis-cli -h $REDIS_HOST -p 6379 -a $REDIS_PASSWORD ping 2>/dev/null | grep -q "PONG"; then
            log_success "Autenticazione Redis OK"
        else
            log_error "Autenticazione Redis FAILED"
            log_info "Verifica la password Redis: $REDIS_PASSWORD"
            exit 1
        fi
    fi
}

# 🛑 Stop tutti i worker
stop_all_workers() {
    log_info "Fermando tutti i worker..."
    
    for i in $(seq 1 $NUM_WORKERS); do
        local worker_name="${BASE_WORKER_NAME}-${i}"
        
        if docker ps -q -f name=$worker_name >/dev/null 2>&1; then
            log_info "Fermando $worker_name..."
            docker stop $worker_name >/dev/null 2>&1 || true
            docker rm $worker_name >/dev/null 2>&1 || true
        fi
    done
    
    log_success "Tutti i worker fermati"
}

# 🚀 Start tutti i worker - AGGIORNATO
start_all_workers() {
    log_info "Avviando ${#WORKER_CONFIGS[@]} worker con autenticazione Redis..."
    
    if [ ! -f ".env" ]; then
        log_error "File .env non trovato!"
        exit 1
    fi
    
    # Test connessione Redis prima di avviare
    test_redis_connection
    
    local worker_num=1
    for config in "${WORKER_CONFIGS[@]}"; do
        # Parse configurazione: "name:queues:concurrency"
        local worker_id=$(echo $config | cut -d: -f1)
        local queues=$(echo $config | cut -d: -f2)
        local concurrency=$(echo $config | cut -d: -f3)
        local worker_name="${BASE_WORKER_NAME}-${worker_num}"
        
        log_info "Avviando $worker_name ($worker_id) - Queues: $queues, Concurrency: $concurrency"
        
        # Calcola limiti di memoria dinamici (aumentati)
        local memory_limit="450m"  # Aumentato per gestire rate limiting
        local cpu_limit="1.5"
        
        # URL Redis con autenticazione
        local redis_url="redis://:${REDIS_PASSWORD}@${REDIS_HOST}:6379"
        
        docker run -d \
            --name $worker_name \
            --restart always \
            --memory=$memory_limit \
            --cpus=$cpu_limit \
            --env-file .env \
            -e REDIS_HOST=$REDIS_HOST \
            -e REDIS_PASSWORD=$REDIS_PASSWORD \
            -e REDIS_URL="$redis_url" \
            -e CELERY_BROKER_URL="$redis_url" \
            -e CELERY_RESULT_BACKEND="$redis_url" \
            -e WORKER_ID="raspberry-pi-${worker_id}" \
            -e WORKER_LOCATION="raspberry-pi" \
            -e WORKER_TYPE="remote" \
            -e ENVIRONMENT="production" \
            -e PYTHONPATH="/app" \
            -e CELERY_TIMEZONE="Europe/Rome" \
            -e OPENAI_RPM_LIMIT="450" \
            -e OPENAI_TPM_LIMIT="80000" \
            -e STRIPE_RPM_LIMIT="100" \
            -e GLOBAL_RATE_LIMIT="300" \
            -e LOG_LEVEL="INFO" \
            $IMAGE_NAME \
            celery -A app.core.celery_app worker \
                --loglevel=info \
                --queues=$queues \
                --concurrency=$concurrency \
                --hostname=$worker_id@raspberry-pi \
                --time-limit=300 \
                --soft-time-limit=240
        
        worker_num=$((worker_num + 1))
        sleep 3  # Pausa più lunga per permettere connessione Redis
    done
    
    log_success "Tutti i worker avviati!"
    
    # Attendi che i worker si connettano
    log_info "Attendendo connessione worker a Redis..."
    sleep 10
}

# 📊 Status di tutti i worker - MIGLIORATO
show_status() {
    echo -e "\n${BLUE}📊 Status Multi-Worker Clearify${NC}"
    echo "=================================="
    
    echo -e "\n${BLUE}📋 Worker containers:${NC}"
    if docker ps -f name=clearify-worker-raspi --format "table {{.Names}}\t{{.Status}}\t{{.Image}}" | grep -q clearify-worker-raspi; then
        docker ps -f name=clearify-worker-raspi --format "table {{.Names}}\t{{.Status}}\t{{.Image}}"
    else
        log_warning "Nessun worker attivo"
    fi
    
    echo -e "\n${BLUE}💾 Uso risorse:${NC}"
    if docker ps -q -f name=clearify-worker-raspi | head -1 >/dev/null 2>&1; then
        docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}" $(docker ps -q -f name=clearify-worker-raspi) 2>/dev/null || log_warning "Impossibile ottenere statistiche"
    fi
    
    echo -e "\n${BLUE}🔗 Configurazione:${NC}"
    echo "Redis: $REDIS_HOST:6379 (con password)"
    echo "Worker attivi: $(docker ps -q -f name=clearify-worker-raspi | wc -l)"
    echo "Worker configurati: ${#WORKER_CONFIGS[@]}"
    
    echo -e "\n${BLUE}⚙️  Configurazione worker:${NC}"
    for i in "${!WORKER_CONFIGS[@]}"; do
        echo "  Worker $((i+1)): ${WORKER_CONFIGS[$i]}"
    done
    
    # Test salute worker
    echo -e "\n${BLUE}🏥 Health Check:${NC}"
    local healthy_workers=0
    for i in $(seq 1 ${#WORKER_CONFIGS[@]}); do
        local worker_name="${BASE_WORKER_NAME}-${i}"
        if docker ps -q -f name=$worker_name >/dev/null 2>&1; then
            if docker exec $worker_name celery -A app.core.celery_app inspect ping >/dev/null 2>&1; then
                echo "  ✅ $worker_name: Healthy"
                healthy_workers=$((healthy_workers + 1))
            else
                echo "  ❌ $worker_name: Unhealthy"
            fi
        else
            echo "  ⏹️  $worker_name: Stopped"
        fi
    done
    
    echo "Healthy workers: $healthy_workers/${#WORKER_CONFIGS[@]}"
}

# 📝 Logs aggregati - MIGLIORATO
show_logs() {
    if [ -z "$2" ]; then
        log_info "Logs aggregati di tutti i worker (Ctrl+C per uscire):"
        
        # Verifica che ci siano worker attivi
        local active_workers=$(docker ps -q -f name=clearify-worker-raspi)
        if [ -z "$active_workers" ]; then
            log_error "Nessun worker attivo"
            return 1
        fi
        
        docker logs -f --tail 20 $active_workers 2>&1 | \
        while read line; do
            timestamp=$(date '+%H:%M:%S')
            
            # Colora per tipo di log - AGGIORNATO
            if echo "$line" | grep -qi "celery.*ready\|worker.*ready\|connected"; then
                echo -e "${GREEN}[$timestamp] 🤖 $line${NC}"
            elif echo "$line" | grep -qi "received task\|task.*success\|processing"; then
                echo -e "${BLUE}[$timestamp] 📋 $line${NC}"
            elif echo "$line" | grep -qi "rate.limit\|limit.exceed"; then
                echo -e "${YELLOW}[$timestamp] 🚦 $line${NC}"
            elif echo "$line" | grep -qi "error\|exception\|failed\|refused"; then
                echo -e "${RED}[$timestamp] ❌ $line${NC}"
            elif echo "$line" | grep -qi "warning\|retry"; then
                echo -e "${YELLOW}[$timestamp] ⚠️  $line${NC}"
            else
                echo -e "[$timestamp] $line"
            fi
        done
    else
        # Logs di worker specifico
        local worker_num=$2
        local worker_name="${BASE_WORKER_NAME}-${worker_num}"
        
        if docker ps -q -f name=$worker_name >/dev/null 2>&1; then
            log_info "Logs di $worker_name:"
            docker logs -f --tail 50 $worker_name
        else
            log_error "Worker $worker_name non trovato"
        fi
    fi
}

# 🧪 Test performance - AGGIORNATO
test_performance() {
    log_info "Test di performance multi-worker..."
    
    local active_workers=$(docker ps -q -f name=clearify-worker-raspi | wc -l)
    log_info "Worker attivi: $active_workers"
    
    if [ $active_workers -eq 0 ]; then
        log_error "Nessun worker attivo"
        exit 1
    fi
    
    # Test connessione Redis per ogni worker
    log_info "Test connessioni Redis..."
    for i in $(seq 1 $active_workers); do
        local worker_name="${BASE_WORKER_NAME}-${i}"
        
        if docker ps -q -f name=$worker_name >/dev/null 2>&1; then
            log_info "Test $worker_name..."
            if docker exec $worker_name python -c "
import redis
r = redis.Redis(host='$REDIS_HOST', port=6379, password='$REDIS_PASSWORD')
try:
    result = r.ping()
    print(f'✅ Worker $i: Redis ping = {result}')
except Exception as e:
    print(f'❌ Worker $i: Redis error = {e}')
    exit(1)
" 2>/dev/null; then
                log_success "Worker $i: Connessione OK"
            else
                log_error "Worker $i: Connessione FAILED"
            fi
        fi
    done
    
    # Test Celery inspect
    log_info "Test Celery workers..."
    for i in $(seq 1 $active_workers); do
        local worker_name="${BASE_WORKER_NAME}-${i}"
        
        if docker ps -q -f name=$worker_name >/dev/null 2>&1; then
            if docker exec $worker_name celery -A app.core.celery_app inspect ping >/dev/null 2>&1; then
                log_success "Worker $i: Celery OK"
            else
                log_error "Worker $i: Celery FAILED"
            fi
        fi
    done
}

# 🧹 Cleanup risorse
cleanup() {
    log_info "Pulizia risorse Docker..."
    
    # Rimuovi container fermati
    docker container prune -f >/dev/null 2>&1 || true
    
    # Rimuovi immagini unused
    docker image prune -f >/dev/null 2>&1 || true
    
    log_success "Pulizia completata"
}

# 📖 Help - AGGIORNATO
show_help() {
    echo -e "${BLUE}🚀 Clearify Multi-Worker Manager${NC}"
    echo "================================="
    echo ""
    echo "Comandi:"
    echo "  start         - Avvia tutti i worker"
    echo "  stop          - Ferma tutti i worker"
    echo "  restart       - Restart completo"
    echo "  status        - Status di tutti i worker"
    echo "  logs [N]      - Logs aggregati (o worker specifico N)"
    echo "  test          - Test performance e connessioni"
    echo "  resources     - Mostra risorse sistema"
    echo "  cleanup       - Pulizia risorse Docker"
    echo ""
    echo "Configurazione attuale:"
    echo "  Worker: ${#WORKER_CONFIGS[@]}"
    echo "  Redis: $REDIS_HOST:6379 (password: ****)"
    echo "  Rate limiting: Abilitato"
    for i in "${!WORKER_CONFIGS[@]}"; do
        echo "    Worker $((i+1)): ${WORKER_CONFIGS[$i]}"
    done
    echo ""
    echo "Novità versione aggiornata:"
    echo "  ✅ Redis con autenticazione"
    echo "  ✅ Rate limiting OpenAI/Stripe"
    echo "  ✅ Health check migliorato"
    echo "  ✅ Logging potenziato"
    echo "  ✅ Gestione errori migliorata"
}

# 🎯 Main
main() {
    echo -e "${GREEN}🚀 Clearify Multi-Worker per Raspberry Pi - v2.0${NC}"
    echo "=================================================="
    
    case "${1:-help}" in
        "start")
            check_resources
            stop_all_workers
            start_all_workers
            sleep 8
            show_status
            ;;
        "stop")
            stop_all_workers
            ;;
        "restart")
            check_resources
            stop_all_workers
            start_all_workers
            sleep 8
            show_status
            ;;
        "status")
            show_status
            ;;
        "logs")
            show_logs "$@"
            ;;
        "test")
            test_performance
            ;;
        "resources")
            check_resources
            ;;
        "cleanup")
            cleanup
            ;;
        "help"|"-h"|"--help")
            show_help
            ;;
        *)
            log_error "Comando sconosciuto: $1"
            show_help
            exit 1
            ;;
    esac
}

main "$@"
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