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

