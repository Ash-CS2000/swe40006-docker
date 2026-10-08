# ---- StayEasy hotel booking app (SWE40006 Task 4.3) ----
FROM python:3.12-slim

# No .pyc files, unbuffered logs, database lives on the /data volume
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DB_PATH=/data/stayeasy.db

WORKDIR /app

# Install dependencies first so this layer is cached between code changes
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code
COPY app.py .
COPY templates/ templates/
COPY static/ static/

# Run as an unprivileged user that owns the data folder
RUN useradd --create-home appuser \
    && mkdir -p /data \
    && chown appuser:appuser /data
USER appuser

# Persistent data (SQLite database) lives here
VOLUME ["/data"]

EXPOSE 5000

# Docker checks /health every 30s and marks the container healthy/unhealthy
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/health')" || exit 1

# Production WSGI server with 2 worker processes
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--access-logfile", "-", "app:app"]
