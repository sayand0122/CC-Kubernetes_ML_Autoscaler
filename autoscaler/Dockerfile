FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    requests==2.31.0 \
    kubernetes==28.1.0

COPY autoscaler.py .

CMD ["python", "autoscaler.py"]
