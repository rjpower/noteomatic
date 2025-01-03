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
sudo apt update
sudo apt install -y nginx certbot python3-certbot-nginx netcat

# Get SSL certificate from Let's Encrypt
sudo certbot --nginx -d memento.labs.ephlabio.com

# Configure Nginx
sudo cp nginx-ssl.conf /etc/nginx/sites-available/noteomatic
sudo ln -s /etc/nginx/sites-available/noteomatic /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx

echo "SSL setup complete! Check https://memento.labs.ephlabio.com:8000"
