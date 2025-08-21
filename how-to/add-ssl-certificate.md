# 🔐 Setup Certificati SSL per Sviluppo Clearify

Questa guida spiega come configurare certificati SSL trusted per lo sviluppo locale di Clearify, eliminando tutti gli errori di certificato nel browser.

## 📋 Prerequisiti

- Docker e Docker Compose installati
- OpenSSL installato (pre-installato su macOS/Linux)
- Accesso amministratore al sistema

## 🚀 Setup Automatico

### 1. Generazione Certificati

Esegui questi comandi nella cartella `ClearifyBackend`:

```bash
# Elimina certificati esistenti
rm -rf certs && mkdir certs

# 1. Genera Certificate Authority (CA)
openssl genrsa -out certs/ca.key 2048
openssl req -new -x509 -days 365 -key certs/ca.key -out certs/ca.crt \
  -subj "/C=IT/ST=Lombardy/L=Milan/O=Clearify/OU=CA/CN=Clearify Development CA"

# 2. Genera chiave privata del server
openssl genrsa -out certs/server.key 2048

# 3. Genera Certificate Signing Request (CSR)
openssl req -new -key certs/server.key -out certs/server.csr \
  -subj "/C=IT/ST=Lombardy/L=Milan/O=Clearify/OU=Dev/CN=localhost"

# 4. Crea file di estensioni per Subject Alternative Names
cat > certs/server.ext << EOF
basicConstraints = CA:FALSE
nsCertType = server
nsComment = "OpenSSL Generated Server Certificate"
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid,issuer:always
keyUsage = critical, digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth
subjectAltName = @alt_names

[alt_names]
DNS.1 = localhost
DNS.2 = *.localhost
DNS.3 = clearify.local
IP.1 = 127.0.0.1
IP.2 = ::1
EOF

# 5. Firma il certificato server con la CA
openssl x509 -req -in certs/server.csr -CA certs/ca.crt -CAkey certs/ca.key \
  -CAcreateserial -out certs/server.crt -days 365 \
  -extfile certs/server.ext

# 6. Genera parametri Diffie-Hellman per sicurezza avanzata
openssl dhparam -out certs/dhparam.pem 2048

# 7. Cleanup file temporanei
rm certs/server.csr certs/server.ext

echo "✅ Certificati generati con successo!"
```

### 2. Verifica Certificati Generati

```bash
# Verifica che tutti i file siano presenti
ls -la certs/

# Output atteso:
# ca.crt       - Certificato Certificate Authority
# ca.key       - Chiave privata CA
# server.crt   - Certificato server firmato
# server.key   - Chiave privata server
# dhparam.pem  - Parametri Diffie-Hellman

# Verifica Subject Alternative Names
openssl x509 -in certs/server.crt -text -noout | grep -A 5 "Subject Alternative Name"
```

## 🔧 Installazione Certificati nel Sistema

### macOS

```bash
# Installa la CA nel keychain di sistema (richiede password admin)
sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain certs/ca.crt

# Verifica installazione
security find-certificate -c "Clearify Development CA" /Library/Keychains/System.keychain
```

### Linux (Ubuntu/Debian)

```bash
# Copia CA nella cartella certificati di sistema
sudo cp certs/ca.crt /usr/local/share/ca-certificates/clearify-dev-ca.crt

# Aggiorna certificati di sistema
sudo update-ca-certificates

# Verifica installazione
ls /etc/ssl/certs/ | grep clearify
```

### Windows (PowerShell come Amministratore)

```powershell
# Importa CA nel Trusted Root Certification Authorities
Import-Certificate -FilePath "certs\ca.crt" -CertStoreLocation Cert:\LocalMachine\Root

# Verifica installazione
Get-ChildItem -Path Cert:\LocalMachine\Root | Where-Object {$_.Subject -like "*Clearify*"}
```

## 🐳 Configurazione Docker

### 1. Riavvia i Container

```bash
# Riavvia nginx con i nuovi certificati
docker-compose restart nginx

# Verifica che nginx parta correttamente
docker-compose logs nginx

# Verifica che non ci siano errori SSL
docker-compose logs nginx | grep -i ssl
```

### 2. Test Configurazione

```bash
# Test certificato trusted (senza -k)
curl https://localhost/health

# Se non ci sono errori SSL, il setup è corretto!

# Test CORS
curl -X OPTIONS https://localhost/api/v1/auth/me \
  -H "Origin: https://localhost:3000" \
  -H "Access-Control-Request-Method: GET" \
  -v
```

## 🌐 Test Browser

### 1. Riavvia Browser Completamente

```bash
# Chrome (macOS)
killall "Google Chrome"

# Chrome (Linux)
killall chrome

# Safari (macOS)
killall Safari
```

### 2. Verifica Certificati

1. **Apri browser** e vai a `https://localhost/health`
2. **Verifica il lucchetto verde** nella barra degli indirizzi
3. **Clicca sul lucchetto** → "Certificate is valid"
4. **Controlla issuer**: dovrebbe essere "Clearify Development CA"

### 3. Test Frontend

1. **Avvia frontend**: `npm run dev` (dovrebbe essere su `https://localhost:3000`)
2. **Apri DevTools** → **Console**
3. **Prova login** - non dovrebbero esserci errori `ERR_CERT_AUTHORITY_INVALID`
4. **Network tab** - tutte le chiamate a `https://localhost/api/` dovrebbero essere verdi

## 🔧 Configurazione Server di Produzione

Per server Linux remoti, modifica il processo:

### 1. Adatta i Subject Alternative Names

```bash
# Nel file server.ext, aggiungi i domini reali:
[alt_names]
DNS.1 = your-api-domain.com
DNS.2 = api.your-domain.com
DNS.3 = localhost  # Mantieni per accesso locale
IP.1 = YOUR_SERVER_IP
IP.2 = 127.0.0.1
```

### 2. Usa Let's Encrypt per Produzione

```bash
# Installa Certbot
sudo apt-get install certbot

# Genera certificati Let's Encrypt
sudo certbot certonly --standalone -d your-api-domain.com

# Copia certificati nella cartella Docker
sudo cp /etc/letsencrypt/live/your-api-domain.com/fullchain.pem certs/server.crt
sudo cp /etc/letsencrypt/live/your-api-domain.com/privkey.pem certs/server.key
sudo cp /etc/letsencrypt/live/your-api-domain.com/chain.pem certs/ca.crt
```

## 🛠️ Troubleshooting

### Errore: "Certificate Authority Invalid"

```bash
# Rimuovi e reinstalla CA
sudo security delete-certificate -c "Clearify Development CA" /Library/Keychains/System.keychain
sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain certs/ca.crt

# Riavvia browser completamente
```

### Errore: "Multiple CORS Headers"

Nel `main.py`, assicurati di aver **disabilitato** il middleware CORS di FastAPI:

```python
# COMMENTA QUESTO BLOCCO - nginx gestisce CORS
# app.add_middleware(
#     CORSMiddleware,
#     ...
# )
print("🔗 CORS managed by nginx proxy - FastAPI CORS disabled")
```

### Errore: "X-API-Key not allowed"

In `nginx.conf`, verifica che `X-API-Key` sia negli headers permessi:

```nginx
add_header 'Access-Control-Allow-Headers' '...,X-API-Key' always;
```

### Errore: "Failed to fetch"

1. **Verifica** che nginx sia attivo: `docker-compose ps`
2. **Controlla logs**: `docker-compose logs nginx`
3. **Test diretto**: `curl https://localhost/health`
4. **Verifica certificati**: certificato installato nel sistema?

## 📋 Checklist Setup Completo

- [ ] Certificati generati in `./certs/`
- [ ] CA installata nel sistema operativo
- [ ] Docker container riavviati
- [ ] `curl https://localhost/health` funziona senza `-k`
- [ ] Browser mostra lucchetto verde
- [ ] Frontend si connette senza errori certificato
- [ ] Login Google OAuth funziona
- [ ] DevTools Network tab senza errori CORS

## 🔄 Aggiornamento Certificati

I certificati durano **365 giorni**. Per rinnovare:

```bash
# Rigenerazione automatica
cd ClearifyBackend
rm -rf certs
# Ripeti Step 1 della guida

# Reinstalla CA aggiornata
sudo security delete-certificate -c "Clearify Development CA" /Library/Keychains/System.keychain
sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain certs/ca.crt

# Riavvia container
docker-compose restart nginx
```

---

## 🎯 Risultato Finale

Dopo aver completato questa guida:

- ✅ **HTTPS completo**: Frontend (3000) ↔ Backend (443) ↔ FastAPI (8000)
- ✅ **Nessun errore certificato** nel browser
- ✅ **Cookie sicuri** funzionanti
- ✅ **CORS configurato** correttamente
- ✅ **Autenticazione Google OAuth** funzionante
- ✅ **Pronto per produzione** con certificati reali

Il setup di sviluppo è ora **identico alla produzione** in termini di sicurezza! 🚀