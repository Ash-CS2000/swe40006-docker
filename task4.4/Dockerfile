# ---- StayEasy Report: command-line booking analytics (SWE40006 Task 4.4) ----
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependencies first (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# The tool itself plus a built-in sample dataset
COPY report.py .
COPY sample/ sample/

# Run as an unprivileged user
RUN useradd --create-home appuser
USER appuser

# Mount point for the user's own CSV files and exported reports
VOLUME ["/data"]

# ENTRYPOINT = the program that always runs.
# CMD = default arguments, replaced by whatever you type after the image name.
ENTRYPOINT ["python", "/app/report.py"]
CMD ["/app/sample/bookings.csv"]
