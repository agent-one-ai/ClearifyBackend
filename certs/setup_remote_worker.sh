#!/bin/bash
# Script per configurare worker remoto con certificati

# Copia questo script e i certificati necessari sul worker remoto
# Certificati necessari: ca.crt, client.key, client.crt

echo "Setting up remote worker with SSL certificates..."

# Crea directory certificati
sudo mkdir -p /opt/clearify/certs

# Copia certificati (assumendo che siano nella directory corrente)
sudo cp ca.crt /opt/clearify/certs/
sudo cp client.key /opt/clearify/certs/
sudo cp client.crt /opt/clearify/certs/

# Imposta permessi
sudo chmod 600 /opt/clearify/certs/client.key
sudo chmod 644 /opt/clearify/certs/ca.crt
sudo chmod 644 /opt/clearify/certs/client.crt

# Configura variabili ambiente per Docker
cat > /opt/clearify/.env <<EOL
REDIS_URL=rediss://192.168.1.109:6380
REDIS_PASSWORD=clearify_redis_2024
SSL_CERT_PATH=/app/certs/client.crt
SSL_KEY_PATH=/app/certs/client.key
SSL_CA_PATH=/app/certs/ca.crt
CELERY_BROKER_URL=rediss://192.168.1.109:6380
CELERY_RESULT_BACKEND=rediss://192.168.1.109:6380
EOL

echo "✅ Remote worker SSL setup complete!"
echo "📝 Make sure Redis TLS is configured on 192.168.1.109:6380"
