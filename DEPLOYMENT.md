# AEGLOS Analytics Pro — Deployment Guide

## Prerequisites

- Python 3.10+
- 4 GB RAM minimum (8 GB recommended)
- 10 GB disk space
- Linux/macOS (Windows via WSL2)

## Development

```bash
git clone <repo>
cd aeglos-analytics
./start-dev.sh
./stop.sh
```

## Production (systemd + nginx)

### 1. Create system user
```bash
sudo useradd -r -s /bin/false -d /opt/aeglos-analytics aeglos
```

### 2. Install application
```bash
sudo cp -r . /opt/aeglos-analytics
sudo chown -R aeglos:aeglos /opt/aeglos-analytics
cd /opt/aeglos-analytics
sudo -u aeglos python3 -m venv venv
sudo -u aeglos venv/bin/pip install -r requirements.txt
```

### 3. Install systemd services
```bash
sudo cp deployment/aeglos-api.service /etc/systemd/system/
sudo cp deployment/aeglos-web.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now aeglos-api aeglos-web
```

### 4. Check status
```bash
sudo systemctl status aeglos-api
sudo systemctl status aeglos-web
journalctl -u aeglos-api -f
```

## Docker

```bash
docker-compose up -d
docker-compose logs -f aeglos-api
docker-compose ps
```

## SSL/TLS with Let's Encrypt

```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com
# Certbot auto-renews; nginx config handles HTTPS redirect
```

Self-signed (development HTTPS):
```bash
mkdir -p deployment/certs
openssl req -x509 -nodes -days 365 -newkey rsa:4096 \
  -keyout deployment/certs/key.pem \
  -out deployment/certs/cert.pem \
  -subj "/CN=aeglos-analytics"
```

## Monitoring

```bash
# API health
curl http://localhost:8000/health

# Pipeline metrics
curl http://localhost:8000/metrics

# GeoThreat statistics
curl http://localhost:8000/api/v1/geothreat/statistics

# Logs
tail -f logs/api.log
tail -f logs/web.log
journalctl -u aeglos-api --since "1 hour ago"
```

## Performance Tuning

For high-throughput production:

```bash
# Increase uvicorn workers (CPU cores × 2 + 1)
# Edit aeglos-api.service: --workers 9

# Tune OS network stack
echo 'net.core.somaxconn = 65535' >> /etc/sysctl.conf
echo 'net.ipv4.tcp_max_syn_backlog = 65535' >> /etc/sysctl.conf
sysctl -p
```
