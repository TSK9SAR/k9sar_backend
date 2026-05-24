sudo rsync -a --delete ~/k9sar_frontend_backups/k9sar_frontend_YYYYMMDD-HHMMSS/ /var/www/k9sar_frontend/
sudo chown -R www-data:www-data /var/www/k9sar_frontend
sudo nginx -t
sudo systemctl reload nginx || sudo systemctl restart nginx

