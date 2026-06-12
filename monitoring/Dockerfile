FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    flask==3.0.0 \
    requests==2.31.0 \
    kubernetes==28.1.0 \
    numpy==1.26.0

COPY app.py .

EXPOSE 8082

CMD ["python", "app.py"]
