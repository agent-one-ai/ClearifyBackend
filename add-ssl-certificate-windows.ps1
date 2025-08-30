# SSL Setup Script per Clearify - Windows PowerShell
# Eseguire come Amministratore nella cartella ClearifyBackend

Write-Host "Inizio setup certificati SSL per Clearify..." -ForegroundColor Green

# Verifica cartella corretta
if (!(Test-Path "docker-compose.yml")) {
    Write-Host "ERRORE: Eseguire dalla cartella ClearifyBackend" -ForegroundColor Red
    exit 1
}

# Verifica OpenSSL
Write-Host "Controllo OpenSSL..." -ForegroundColor Yellow
try {
    $version = openssl version
    Write-Host "OpenSSL trovato: $version" -ForegroundColor Green
} catch {
    Write-Host "OpenSSL non trovato. Installazione..." -ForegroundColor Yellow
    
    # Prova installazione automatica
    try {
        winget install --id=FireDaemon.OpenSSL -e --accept-source-agreements --accept-package-agreements
        Start-Sleep -Seconds 5
        $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("PATH","User")
        $version = openssl version
        Write-Host "OpenSSL installato: $version" -ForegroundColor Green
    } catch {
        Write-Host "Installazione fallita. Installa manualmente da:" -ForegroundColor Red
        Write-Host "https://slproweb.com/products/Win32OpenSSL.html" -ForegroundColor Yellow
        exit 1
    }
}

Write-Host "Generazione certificati SSL..." -ForegroundColor Cyan

# Pulizia e creazione cartella certs
if (Test-Path "certs") {
    Remove-Item -Recurse -Force certs
}
New-Item -ItemType Directory -Name "certs" | Out-Null

Write-Host "Creazione Certificate Authority..." -ForegroundColor Yellow

# 1. Genera Certificate Authority (CA)
openssl genrsa -out certs/ca.key 2048
openssl req -new -x509 -days 365 -key certs/ca.key -out certs/ca.crt -subj "/C=IT/ST=Lombardy/L=Milan/O=Clearify/OU=CA/CN=Clearify Development CA"

Write-Host "Creazione certificato server..." -ForegroundColor Yellow

# 2. Genera chiave privata del server
openssl genrsa -out certs/server.key 2048

# 3. Genera Certificate Signing Request (CSR)
openssl req -new -key certs/server.key -out certs/server.csr -subj "/C=IT/ST=Lombardy/L=Milan/O=Clearify/OU=Dev/CN=localhost"

# 4. Crea file di estensioni per Subject Alternative Names
$extensionsContent = @"
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
"@

$extensionsContent | Out-File -FilePath "certs/server.ext" -Encoding ASCII

# 5. Firma il certificato server con la CA
openssl x509 -req -in certs/server.csr -CA certs/ca.crt -CAkey certs/ca.key -CAcreateserial -out certs/server.crt -days 365 -extfile certs/server.ext

Write-Host "Creazione parametri Diffie-Hellman..." -ForegroundColor Yellow

# 6. Genera parametri Diffie-Hellman per sicurezza avanzata
openssl dhparam -out certs/dhparam.pem 2048

# 7. Cleanup file temporanei
Remove-Item -Force certs/server.csr, certs/server.ext -ErrorAction SilentlyContinue

Write-Host "Certificati generati con successo!" -ForegroundColor Green

# 8. Verifica certificati generati
Write-Host "Verifica certificati generati:" -ForegroundColor Cyan
Get-ChildItem -Path certs/ | Format-Table Name, Length, LastWriteTime

# 9. Installa CA nel Windows Certificate Store
Write-Host "Installazione CA nel Certificate Store..." -ForegroundColor Yellow
try {
    Import-Certificate -FilePath "certs\ca.crt" -CertStoreLocation Cert:\LocalMachine\Root | Out-Null
    Write-Host "CA installata con successo nel Certificate Store" -ForegroundColor Green
    
    # Verifica installazione CA
    $cert = Get-ChildItem -Path Cert:\LocalMachine\Root | Where-Object {$_.Subject -like "*Clearify*"}
    if ($cert) {
        Write-Host "CA verificata: $($cert.Subject)" -ForegroundColor Green
    }
} catch {
    Write-Host "ERRORE installazione CA. Assicurati di essere Amministratore" -ForegroundColor Red
    Write-Host "Errore: $($_.Exception.Message)" -ForegroundColor Red
}

# 10. Riavvia nginx con i nuovi certificati
Write-Host "Riavvio container nginx..." -ForegroundColor Yellow
try {
    docker-compose restart nginx
    Write-Host "Container nginx riavviato" -ForegroundColor Green
    
    # Aspetta che nginx si avvii
    Start-Sleep -Seconds 5
    
    # Verifica logs nginx
    Write-Host "Logs nginx:" -ForegroundColor Cyan
    docker-compose logs --tail=5 nginx
    
} catch {
    Write-Host "ERRORE riavvio Docker. Verifica che Docker sia in esecuzione" -ForegroundColor Red
}

# 11. Test configurazione
Write-Host "Test configurazione HTTPS..." -ForegroundColor Yellow
try {
    $response = Invoke-WebRequest -Uri "https://localhost/health" -UseBasicParsing -ErrorAction Stop
    Write-Host "Test HTTPS riuscito - Status: $($response.StatusCode)" -ForegroundColor Green
} catch {
    Write-Host "Test HTTPS fallito: $($_.Exception.Message)" -ForegroundColor Yellow
    Write-Host "Prova manualmente: curl -k https://localhost/health" -ForegroundColor Cyan
}

# 12. Test CORS
Write-Host "Test CORS..." -ForegroundColor Cyan
try {
    $headers = @{
        'Origin' = 'https://localhost:3000'
        'Access-Control-Request-Method' = 'GET'
    }
    $response = Invoke-WebRequest -Uri "https://localhost/api/v1/auth/me" -Method OPTIONS -Headers $headers -UseBasicParsing -ErrorAction Stop
    Write-Host "Test CORS riuscito - Status: $($response.StatusCode)" -ForegroundColor Green
} catch {
    Write-Host "Test CORS: $($_.Exception.Message)" -ForegroundColor Yellow
}

# 13. Checklist finale
Write-Host "" -ForegroundColor White
Write-Host "CHECKLIST FINALE:" -ForegroundColor Magenta
Write-Host "- Certificati generati in .\certs\" -ForegroundColor White
Write-Host "- CA installata nel Certificate Store di Windows" -ForegroundColor White
Write-Host "- Container Docker riavviati" -ForegroundColor White
Write-Host "- Test HTTPS: https://localhost/health" -ForegroundColor White

Write-Host "" -ForegroundColor White
Write-Host "PROSSIMI PASSI:" -ForegroundColor Magenta
Write-Host "1. Chiudi COMPLETAMENTE tutti i browser (Chrome, Edge, Firefox)" -ForegroundColor White
Write-Host "2. Riapri browser e vai a https://localhost/health" -ForegroundColor White
Write-Host "3. Verifica il LUCCHETTO VERDE nella barra degli indirizzi" -ForegroundColor White
Write-Host "4. Avvia frontend: npm run dev" -ForegroundColor White
Write-Host "5. Test login - non dovrebbero esserci errori certificato" -ForegroundColor White

Write-Host "" -ForegroundColor White
Write-Host "Per rimuovere la CA in futuro:" -ForegroundColor Yellow
Write-Host 'Get-ChildItem -Path Cert:\LocalMachine\Root | Where-Object {$_.Subject -like "*Clearify*"} | Remove-Item' -ForegroundColor Gray

Write-Host "" -ForegroundColor White
Write-Host "Setup completato! Il tuo ambiente di sviluppo ora ha HTTPS trusted come in produzione" -ForegroundColor Green