FROM python:3.11-slim

WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps (CPU-only torch to keep image small)
RUN pip install --no-cache-dir \
    torch==2.5.1 torchvision==0.20.1 --index-url https://download.pytorch.org/whl/cpu

RUN pip install --no-cache-dir \
    flask==3.0.0 \
    gunicorn==21.2.0 \
    prometheus-client==0.19.0 \
    Pillow==10.0.0 \
    numpy==1.26.0

# Pre-download model weights so they're baked into the image
RUN python -c "from torchvision.models import resnet18, ResNet18_Weights; resnet18(weights=ResNet18_Weights.DEFAULT)"

COPY app.py .

EXPOSE 8080

# Use gunicorn for production; 2 workers per CPU core is a good starting point
CMD ["gunicorn", "--workers=2", "--threads=4", "--bind=0.0.0.0:8080", "--timeout=30", "app:app"]
