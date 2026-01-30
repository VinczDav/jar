# JAR - Deployment Guide

## Overview

This guide covers deploying the JAR application to a VPS using Docker.

## Prerequisites

- Ubuntu 22.04+ server
- Docker and Docker Compose installed
- Domain pointing to your server
- Git installed

## Initial Server Setup

### 1. Install Docker

```bash
# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Add your user to docker group
sudo usermod -aG docker $USER
newgrp docker

# Install Docker Compose
sudo apt-get update
sudo apt-get install docker-compose-plugin
```

### 2. Clone the Repository

```bash
cd /opt
sudo mkdir jar
sudo chown $USER:$USER jar
git clone https://github.com/your-repo/jar.git
cd jar
```

### 3. Configure Environment

```bash
# Copy and edit production environment
cp .env.production.example .env.production

# Edit with your actual values
nano .env.production
```

Required environment variables:
- `SECRET_KEY` - Generate with: `python -c "import secrets; print(secrets.token_urlsafe(50))"`
- `DB_PASSWORD` - Strong database password
- `EMAIL_*` - SMTP server credentials
- `ALLOWED_HOSTS` - Your domain
- `SITE_URL` - Full URL with https

### 4. SSL Certificate Setup

```bash
# Create directories
mkdir -p certbot/www certbot/conf

# Initial certificate (replace domain)
docker compose -f docker-compose.prod.yml run --rm certbot certonly \
  --webroot \
  --webroot-path /var/www/certbot \
  -d jar.hunfloorball.hu \
  --email your-email@example.com \
  --agree-tos \
  --no-eff-email
```

### 5. First Deployment

```bash
# Build images
docker compose -f docker-compose.prod.yml build

# Run migrations
docker compose -f docker-compose.prod.yml run --rm web python manage.py migrate

# Create superuser
docker compose -f docker-compose.prod.yml run --rm web python manage.py createsuperuser

# Collect static files
docker compose -f docker-compose.prod.yml run --rm web python manage.py collectstatic --noinput

# Start services
docker compose -f docker-compose.prod.yml up -d
```

## Scheduled Tasks (Cron Jobs)

The scheduler container runs periodic tasks automatically:

| Task | Schedule | Description |
|------|----------|-------------|
| `send_match_reminders` | Every hour (XX:00) | Sends match reminder emails |

### Manual Execution

```bash
# Run match reminders manually
docker compose -f docker-compose.prod.yml exec web python manage.py send_match_reminders

# Dry run (see what would be sent)
docker compose -f docker-compose.prod.yml exec web python manage.py send_match_reminders --dry-run
```

## GitHub Actions Deployment

### Required Secrets

Add these secrets in GitHub repository settings:

| Secret | Description |
|--------|-------------|
| `VPS_HOST` | Server IP or hostname |
| `VPS_USER` | SSH username |
| `VPS_PATH` | Path to project (e.g., `/opt/jar`) |
| `VPS_SSH_KEY` | Private SSH key for deployment |

### SSH Key Setup

```bash
# On your local machine, generate a deploy key
ssh-keygen -t ed25519 -C "deploy@jar" -f ~/.ssh/jar_deploy

# Add public key to server
cat ~/.ssh/jar_deploy.pub | ssh user@server "cat >> ~/.ssh/authorized_keys"

# Copy private key content to GitHub secrets
cat ~/.ssh/jar_deploy
```

### Manual Trigger

You can trigger deployment manually from GitHub Actions with optional migration control.

## Useful Commands

### View Logs

```bash
# All services
docker compose -f docker-compose.prod.yml logs -f

# Specific service
docker compose -f docker-compose.prod.yml logs -f web
docker compose -f docker-compose.prod.yml logs -f scheduler
```

### Restart Services

```bash
docker compose -f docker-compose.prod.yml restart
```

### Database Backup

```bash
# Create backup
docker compose -f docker-compose.prod.yml exec db pg_dump -U jar_user jar_db > backups/backup_$(date +%Y%m%d).sql

# Restore backup
docker compose -f docker-compose.prod.yml exec -T db psql -U jar_user jar_db < backups/backup_YYYYMMDD.sql
```

### Shell Access

```bash
# Django shell
docker compose -f docker-compose.prod.yml exec web python manage.py shell

# Database shell
docker compose -f docker-compose.prod.yml exec db psql -U jar_user jar_db
```

## Local Development with Scheduler

To test the scheduler locally:

```bash
# Start with scheduler profile
docker compose --profile scheduler up

# Or start scheduler separately
docker compose up scheduler
```

## Health Check

The application exposes a health check endpoint at `/health/` that returns:

```json
{
  "status": "healthy",
  "database": "connected"
}
```

## Troubleshooting

### Container won't start

```bash
# Check logs
docker compose -f docker-compose.prod.yml logs web

# Check container status
docker ps -a
```

### Database connection issues

```bash
# Verify database is running
docker compose -f docker-compose.prod.yml ps db

# Check database logs
docker compose -f docker-compose.prod.yml logs db
```

### SSL certificate issues

```bash
# Renew certificate manually
docker compose -f docker-compose.prod.yml run --rm certbot renew

# Check certificate status
docker compose -f docker-compose.prod.yml run --rm certbot certificates
```
