FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    flask==3.0.0 \
    gunicorn==21.2.0 \
    requests==2.31.0 \
    prometheus-client==0.19.0 \
    numpy==1.26.0

COPY app.py .

EXPOSE 8081

CMD ["gunicorn", "--workers=4", "--threads=8", "--bind=0.0.0.0:8081", "--timeout=30", "app:app"]
