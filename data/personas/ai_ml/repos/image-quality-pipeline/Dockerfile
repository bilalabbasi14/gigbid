FROM python:3.9-slim

# Install system dependencies for OpenCV
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 libsm6 libxext6 libxrender1 && \
    rm -rf /var/lib/apt/lists/*

# Set workdir
WORKDIR /app

# Copy requirements and install
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY image_quality.py ./

# Entry point – expects a mounted folder with images
ENTRYPOINT ["python", "image_quality.py"]
