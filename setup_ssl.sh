#!/bin/bash

# Update package list and install required packages
sudo apt update
sudo apt install -y nginx certbot python3-certbot-nginx

# Get SSL certificate from Let's Encrypt
sudo certbot --nginx -d memento.labs.ephlabio.com

# Configure Nginx
sudo cp nginx-ssl.conf /etc/nginx/sites-available/noteomatic
sudo ln -s /etc/nginx/sites-available/noteomatic /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx

echo "SSL setup complete! Check https://memento.labs.ephlabio.com:8000"
