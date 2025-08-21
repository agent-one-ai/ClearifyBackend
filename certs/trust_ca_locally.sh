#!/bin/bash
# Script per aggiungere la CA ai certificati trusted localmente

echo "Adding Clearify CA to local trusted certificates..."

# Rileva OS e aggiungi CA appropriatamente
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    # Linux
    sudo cp ./certs/ca.crt /usr/local/share/ca-certificates/clearify-ca.crt
    sudo update-ca-certificates
    echo "✅ CA added to Linux trusted certificates"
elif [[ "$OSTYPE" == "darwin"* ]]; then
    # macOS
    sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain ./certs/ca.crt
    echo "✅ CA added to macOS trusted certificates"
else
    echo "⚠️  Manual CA trust required for your OS"
    echo "   Import ./certs/ca.crt to your system's trusted certificate store"
fi

# Aggiungi clearify.local a /etc/hosts se non presente
if ! grep -q "clearify.local" /etc/hosts; then
    echo "127.0.0.1 clearify.local" | sudo tee -a /etc/hosts
    echo "✅ Added clearify.local to /etc/hosts"
fi

echo "🎉 Local trust setup complete!"
