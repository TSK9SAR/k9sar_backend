# ==============================================================
# ✅ K9SAR Backend — Corrected Dockerfile
# ==============================================================

FROM python:3.11-slim

# Prevent .pyc files and ensure real-time logging
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set working directory
WORKDIR /app

# Copy requirements and install dependencies cleanly
COPY requirements.txt /app/

RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc python3-dev libffi-dev libssl-dev make && \
    pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip uninstall -y bcrypt py-bcrypt || true && \
    pip install --no-cache-dir bcrypt==4.1.2 passlib==1.7.4 && \
    pip install --no-cache-dir -r requirements.txt && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy entire project into container
COPY . /app/

# Expose FastAPI port
EXPOSE 8000

# ✅ Start using correct import path
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

