#!/bin/bash
# generate_certificates.sh - Script per generare certificati SSL/TLS per sviluppo e produzione

set -e

# Colori per output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configurazione
CERT_DIR="./certs"
CA_KEY="${CERT_DIR}/ca.key"
CA_CERT="${CERT_DIR}/ca.crt"
SERVER_KEY="${CERT_DIR}/server.key"
SERVER_CERT="${CERT_DIR}/server.crt"
CLIENT_KEY="${CERT_DIR}/client.key"
CLIENT_CERT="${CERT_DIR}/client.crt"
REDIS_KEY="${CERT_DIR}/redis.key"
REDIS_CERT="${CERT_DIR}/redis.crt"
DHPARAM="${CERT_DIR}/dhparam.pem"

# Informazioni certificato
COUNTRY="IT"
STATE="Lombardy"
CITY="Milan"
ORG="Clearify"
ORG_UNIT="IT Department"
COMMON_NAME="clearify.local"
EMAIL="admin@clearify.local"

echo -e "${GREEN}🔐 Generating SSL/TLS certificates for Clearify...${NC}"

# Crea directory certificati
mkdir -p ${CERT_DIR}

echo -e "${YELLOW}📁 Created certificates directory: ${CERT_DIR}${NC}"

# 1. Genera Certificate Authority (CA)
echo -e "${YELLOW}🏛️  Generating Certificate Authority (CA)...${NC}"
openssl genrsa -out ${CA_KEY} 4096

openssl req -new -x509 -days 365 -key ${CA_KEY} -out ${CA_CERT} \
    -subj "/C=${COUNTRY}/ST=${STATE}/L=${CITY}/O=${ORG}/OU=${ORG_UNIT} CA/CN=Clearify CA/emailAddress=${EMAIL}"

echo -e "${GREEN}✅ CA certificate generated${NC}"

# 2. Genera Server Certificate (per Nginx/Backend)
echo -e "${YELLOW}🖥️  Generating Server certificate...${NC}"
openssl genrsa -out ${SERVER_KEY} 2048

# Crea CSR per server
openssl req -new -key ${SERVER_KEY} -out ${CERT_DIR}/server.csr \
    -subj "/C=${COUNTRY}/ST=${STATE}/L=${CITY}/O=${ORG}/OU=${ORG_UNIT}/CN=${COMMON_NAME}/emailAddress=${EMAIL}"

# Crea file di configurazione per SAN (Subject Alternative Names)
cat > ${CERT_DIR}/server.conf <<EOF
[req]
distinguished_name = req_distinguished_name
req_extensions = v3_req
prompt = no

[req_distinguished_name]
C=${COUNTRY}
ST=${STATE}
L=${CITY}
O=${ORG}
OU=${ORG_UNIT}
CN=localhost
emailAddress=${EMAIL}

[v3_req]
basicConstraints = CA:FALSE
keyUsage = nonRepudiation, digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth
subjectAltName = @alt_names

[alt_names]
DNS.1 = localhost
DNS.2 = *.localhost
DNS.3 = clearify.local
DNS.4 = *.clearify.local
DNS.5 = clearify-backend
DNS.6 = clearify-redis
DNS.7 = redis
DNS.8 = nginx
IP.1 = 127.0.0.1
IP.2 = ::1
IP.3 = 192.168.1.108
EOF

# Firma il certificato server con la CA
openssl x509 -req -in ${CERT_DIR}/server.csr -CA ${CA_CERT} -CAkey ${CA_KEY} \
    -CAcreateserial -out ${SERVER_CERT} -days 365 \
    -extensions v3_req -extfile ${CERT_DIR}/server.conf

echo -e "${GREEN}✅ Server certificate generated${NC}"

# 3. Genera Client Certificate (per worker remoti)
echo -e "${YELLOW}👤 Generating Client certificate for workers...${NC}"
openssl genrsa -out ${CLIENT_KEY} 2048

openssl req -new -key ${CLIENT_KEY} -out ${CERT_DIR}/client.csr \
    -subj "/C=${COUNTRY}/ST=${STATE}/L=${CITY}/O=${ORG}/OU=${ORG_UNIT}/CN=clearify-worker/emailAddress=${EMAIL}"

# Firma il certificato client con la CA
openssl x509 -req -in ${CERT_DIR}/client.csr -CA ${CA_CERT} -CAkey ${CA_KEY} \
    -CAcreateserial -out ${CLIENT_CERT} -days 365

echo -e "${GREEN}✅ Client certificate generated${NC}"

# 4. Copia certificati per Redis
echo -e "${YELLOW}🗄️  Preparing Redis certificates...${NC}"
cp ${SERVER_KEY} ${REDIS_KEY}
cp ${SERVER_CERT} ${REDIS_CERT}

echo -e "${GREEN}✅ Redis certificates prepared${NC}"

# 5. Genera DH Parameters per Perfect Forward Secrecy
echo -e "${YELLOW}🔑 Generating DH parameters (this may take a while)...${NC}"
openssl dhparam -out ${DHPARAM} 2048

echo -e "${GREEN}✅ DH parameters generated${NC}"

# 6. Imposta permessi corretti
echo -e "${YELLOW}🔒 Setting correct permissions...${NC}"
chmod 600 ${CERT_DIR}/*.key
chmod 644 ${CERT_DIR}/*.crt
chmod 644 ${CERT_DIR}/*.pem

# 7. Crea script per worker remoto
cat > ${CERT_DIR}/setup_remote_worker.sh <<EOF
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
EOF

chmod +x ${CERT_DIR}/setup_remote_worker.sh

# 8. Crea configurazione Redis TLS
cat > ${CERT_DIR}/redis_tls.conf <<EOF
# Redis TLS Configuration
# Copy this to your Redis server (192.168.1.109)

port 0
tls-port 6380
tls-cert-file /etc/redis/tls/server.crt
tls-key-file /etc/redis/tls/server.key
tls-ca-cert-file /etc/redis/tls/ca.crt
tls-protocols "TLSv1.2 TLSv1.3"
tls-ciphersuites TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256:TLS_AES_128_GCM_SHA256
requirepass clearify_redis_2024

# Security
protected-mode yes
bind 0.0.0.0
maxmemory-policy allkeys-lru
EOF

# 9. Crea script per configurare Redis TLS sul server remoto
cat > ${CERT_DIR}/setup_redis_tls.sh <<EOF
#!/bin/bash
# Script per configurare Redis TLS sul server 192.168.1.109

echo "🔐 Setting up Redis TLS on remote server..."

# Crea directory per certificati Redis
sudo mkdir -p /etc/redis/tls

# Copia certificati (esegui questo script sul server Redis)
echo "📋 Copy these files to /etc/redis/tls/ on your Redis server:"
echo "   - ca.crt"
echo "   - server.crt" 
echo "   - server.key"

# Esempio di comandi per copiare i file
echo ""
echo "🔧 On your Redis server (192.168.1.109), run:"
echo "sudo mkdir -p /etc/redis/tls"
echo "sudo cp ca.crt /etc/redis/tls/"
echo "sudo cp server.crt /etc/redis/tls/"
echo "sudo cp server.key /etc/redis/tls/"
echo "sudo chmod 600 /etc/redis/tls/server.key"
echo "sudo chmod 644 /etc/redis/tls/ca.crt"
echo "sudo chmod 644 /etc/redis/tls/server.crt"
echo "sudo chown redis:redis /etc/redis/tls/*"

echo ""
echo "📝 Then update your Redis configuration with:"
echo "sudo cp redis_tls.conf /etc/redis/redis.conf"
echo "sudo systemctl restart redis"

# Test connessione
echo ""
echo "🧪 Test TLS connection with:"
echo "redis-cli --tls --cert /etc/redis/tls/server.crt --key /etc/redis/tls/server.key --cacert /etc/redis/tls/ca.crt -h 192.168.1.109 -p 6380 -a clearify_redis_2024 ping"

EOF

chmod +x ${CERT_DIR}/setup_redis_tls.sh

# 10. Riassunto
echo -e "${GREEN}"
echo "🎉 Certificate generation complete!"
echo "📋 Generated certificates:"
echo "   • CA Certificate: ${CA_CERT}"
echo "   • Server Certificate: ${SERVER_CERT}"
echo "   • Client Certificate: ${CLIENT_CERT}"
echo "   • Redis Certificates: ${REDIS_CERT}"
echo "   • DH Parameters: ${DHPARAM}"
echo ""
echo "📝 Next steps:"
echo "   1. Configure Redis TLS on 192.168.1.109:"
echo "      ${CERT_DIR}/setup_redis_tls.sh"
echo ""
echo "   2. Create nginx configuration files in nginx/ directory"
echo ""
echo "   3. Update your docker-compose.yml with the new configuration"
echo ""
echo "   4. For remote workers, use:"
echo "      ${CERT_DIR}/setup_remote_worker.sh"
echo ""
echo "   5. Trust the CA certificate locally:"
echo "      ${CERT_DIR}/trust_ca_locally.sh"
echo ""
echo "🔍 Test your setup:"
echo "   curl -k https://clearify.local/health"
echo "   or"
echo "   curl --cacert ${CA_CERT} https://clearify.local/health"
echo -e "${NC}"

# 11. Crea trust script per sviluppo locale
cat > ${CERT_DIR}/trust_ca_locally.sh <<EOF
#!/bin/bash
# Script per aggiungere la CA ai certificati trusted localmente

echo "Adding Clearify CA to local trusted certificates..."

# Rileva OS e aggiungi CA appropriatamente
if [[ "\$OSTYPE" == "linux-gnu"* ]]; then
    # Linux
    sudo cp ${CA_CERT} /usr/local/share/ca-certificates/clearify-ca.crt
    sudo update-ca-certificates
    echo "✅ CA added to Linux trusted certificates"
elif [[ "\$OSTYPE" == "darwin"* ]]; then
    # macOS
    sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain ${CA_CERT}
    echo "✅ CA added to macOS trusted certificates"
else
    echo "⚠️  Manual CA trust required for your OS"
    echo "   Import ${CA_CERT} to your system's trusted certificate store"
fi

# Aggiungi clearify.local a /etc/hosts se non presente
if ! grep -q "clearify.local" /etc/hosts; then
    echo "127.0.0.1 clearify.local" | sudo tee -a /etc/hosts
    echo "✅ Added clearify.local to /etc/hosts"
fi

echo "🎉 Local trust setup complete!"
EOF

chmod +x ${CERT_DIR}/trust_ca_locally.sh

echo -e "${YELLOW}💡 Run ${CERT_DIR}/trust_ca_locally.sh to trust certificates locally${NC}"