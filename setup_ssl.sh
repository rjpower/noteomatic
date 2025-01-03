#!/bin/bash

# Function to check if a port is available
check_port() {
    if nc -z localhost $1 >/dev/null 2>&1; then
        echo "Error: Port $1 is already in use"
        exit 1
    fi
}

# Check required ports
echo "Checking required ports..."
check_port 80
check_port 443
check_port 8000

# Update package list and install required packages
echo "Installing required packages..."
sudo apt update
sudo apt install -y nginx certbot python3-certbot-nginx netcat-traditional

# Configure Nginx first without SSL
echo "Configuring initial nginx setup..."
sudo cp nginx-nossl.conf /etc/nginx/sites-available/noteomatic
sudo ln -sf /etc/nginx/sites-available/noteomatic /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl restart nginx

# Get SSL certificate
echo "Obtaining SSL certificate..."
sudo certbot --nginx -d memento.labs.ephlabio.com

# Check if certificate was obtained successfully
if [ -f "/etc/letsencrypt/live/memento.labs.ephlabio.com/fullchain.pem" ]; then
    echo "SSL certificate obtained successfully. Configuring SSL..."
    sudo cp nginx-ssl.conf /etc/nginx/sites-available/noteomatic
    sudo nginx -t && sudo systemctl restart nginx
    echo "SSL setup complete! Check https://memento.labs.ephlabio.com:8000"
else
    echo "Failed to obtain SSL certificate. Please check the certbot output above."
    exit 1
fi
