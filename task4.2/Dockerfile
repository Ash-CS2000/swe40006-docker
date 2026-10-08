# 1. Start from an official image that already has Python installed
FROM python:3.12-slim

# 2. Work inside /app in the container
WORKDIR /app

# 3. Copy requirements first and install them (cached unless requirements change)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. Copy the app code
COPY app.py .

# 5. Document the port the app listens on
EXPOSE 5000

# 6. Command to run when the container starts
CMD ["python", "app.py"]