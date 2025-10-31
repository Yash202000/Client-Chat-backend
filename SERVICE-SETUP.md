# AgentConnect Backend Systemd Service Setup

This guide explains how to set up and manage the AgentConnect backend as a systemd service.

## Service File

The service file `agentconnect-backend.service` is configured to:
- Automatically start Docker Compose services (ChromaDB, PostgreSQL, MinIO) before starting the backend
- Run the backend using uvicorn with the virtual environment
- Load environment variables from the `.env` file
- Start automatically on system boot
- Restart automatically if it crashes (on-failure)
- Log output to `/var/log/agentconnect-backend.log` and errors to `/var/log/agentconnect-backend-error.log`

## Prerequisites

Before setting up the service, ensure:
1. Docker and Docker Compose are installed and running
2. Your user (`developer`) has permission to run Docker commands without sudo
3. The `.env` file is properly configured in the backend directory
4. All required services are defined in `docker-compose.yml`

## Installation Steps

### 1. Ensure Docker Permissions (one-time setup)

Make sure your user can run Docker without sudo:
```bash
# Check if you're in the docker group
groups | grep docker

# If not, add yourself to the docker group
sudo usermod -aG docker $USER

# Log out and back in, or run:
newgrp docker
```

### 2. Create Log Files (one-time setup)

```bash
sudo touch /var/log/agentconnect-backend.log
sudo touch /var/log/agentconnect-backend-error.log
sudo chown developer:developer /var/log/agentconnect-backend.log
sudo chown developer:developer /var/log/agentconnect-backend-error.log
```

### 3. Test Docker Compose Services

Before setting up the service, ensure Docker Compose works:
```bash
cd /home/developer/personal/AgentConnect/backend
docker compose up -d
docker compose ps  # Verify all services are running
```

### 4. Copy Service File to Systemd

```bash
sudo cp agentconnect-backend.service /etc/systemd/system/
```

### 5. Reload Systemd Daemon

```bash
sudo systemctl daemon-reload
```

### 6. Enable Service (start on boot)

```bash
sudo systemctl enable agentconnect-backend.service
```

### 7. Start the Service

```bash
sudo systemctl start agentconnect-backend.service
```

## Managing the Service

### Check Service Status
```bash
sudo systemctl status agentconnect-backend.service
```

### Stop the Service
```bash
sudo systemctl stop agentconnect-backend.service
```

### Restart the Service
```bash
sudo systemctl restart agentconnect-backend.service
```

### View Logs
```bash
# View all logs
sudo journalctl -u agentconnect-backend.service

# View recent logs
sudo journalctl -u agentconnect-backend.service -n 100

# Follow logs in real-time
sudo journalctl -u agentconnect-backend.service -f

# View application logs
tail -f /var/log/agentconnect-backend.log

# View error logs
tail -f /var/log/agentconnect-backend-error.log
```

### Disable Service (prevent start on boot)
```bash
sudo systemctl disable agentconnect-backend.service
```

## Important Notes

1. **Docker Services**: The systemd service automatically starts Docker Compose services (ChromaDB, PostgreSQL, MinIO) before starting the backend. It waits 15 seconds for services to be ready.

2. **No --reload flag**: The service runs without `--reload` for production stability. For development, continue using `uvicorn app.main:app --reload --port 8000` manually.

3. **Environment Variables**: The service loads environment variables from `/home/developer/personal/AgentConnect/backend/.env`. Make sure this file exists and has the correct permissions.

4. **Port**: The service runs on port 8000 and binds to all interfaces (0.0.0.0). Make sure this port is available and not blocked by firewall.

5. **ChromaDB Connection**: The service expects ChromaDB to be accessible at the host/port specified in your `.env` file (`CHROMA_DB_HOST` and `CHROMA_DB_PORT`). If ChromaDB is at `192.168.1.11:8001`, ensure it's reachable.

6. **Updates**: After modifying the service file, always run:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl restart agentconnect-backend.service
   ```

## Troubleshooting

### Service won't start
1. Check the status: `sudo systemctl status agentconnect-backend.service`
2. Check logs: `sudo journalctl -u agentconnect-backend.service -n 50`
3. Check application error logs: `tail -n 100 /var/log/agentconnect-backend-error.log`
4. Verify Docker services are running: `cd /home/developer/personal/AgentConnect/backend && docker compose ps`
5. Verify virtual environment exists: `ls -la /home/developer/personal/AgentConnect/backend/venv/bin/uvicorn`
6. Test manually: `cd /home/developer/personal/AgentConnect/backend && ./venv/bin/uvicorn app.main:app --port 8000`

### Docker permission issues
If you see "permission denied" errors with Docker:
```bash
# Add user to docker group
sudo usermod -aG docker developer

# Apply group changes (or log out and back in)
newgrp docker

# Test docker access
docker ps
```

### ChromaDB connection timeout
If you see "Connection timed out" errors for ChromaDB:
1. Check if ChromaDB service is running: `docker compose ps chroma`
2. Verify ChromaDB is accessible: `curl http://192.168.1.11:8001/api/v1/heartbeat`
3. Check `.env` file has correct `CHROMA_DB_HOST` and `CHROMA_DB_PORT`
4. If using local ChromaDB, update `.env` to use `localhost` or `127.0.0.1` instead of `192.168.1.11`

### PostgreSQL connection issues
Check if PostgreSQL is running:
```bash
docker compose ps db
docker compose logs db
```

### Permission issues with logs
Make sure the log files have correct permissions:
```bash
sudo chown developer:developer /var/log/agentconnect-backend*.log
sudo chmod 644 /var/log/agentconnect-backend*.log
```

### Service keeps restarting
Check error logs for application issues:
```bash
tail -n 100 /var/log/agentconnect-backend-error.log
# Or use journalctl
sudo journalctl -u agentconnect-backend.service -f
```

### Increase startup wait time
If services need more time to start, edit the service file and increase the sleep time:
```bash
sudo nano /etc/systemd/system/agentconnect-backend.service
# Change: ExecStartPre=/bin/sleep 15
# To: ExecStartPre=/bin/sleep 30

sudo systemctl daemon-reload
sudo systemctl restart agentconnect-backend.service
```
