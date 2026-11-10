
FROM python:3.11-slim

WORKDIR /app

# Install FFmpeg and required system libraries
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    ffmpeg libgomp1 ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

ENV PYTHONUNBUFFERED=1

# Start FastAPI using Railway's port
CMD ["sh", "-c", "exec python -m uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]

