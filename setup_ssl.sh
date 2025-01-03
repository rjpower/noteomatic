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
echo "Configuring Nginx..."
sudo cp nginx-ssl.conf /etc/nginx/sites-available/noteomatic
sudo ln -sf /etc/nginx/sites-available/noteomatic /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl restart nginx

echo "Basic setup complete! Now run certbot manually:"
echo "sudo certbot --nginx -d memento.labs.ephlabio.com"
