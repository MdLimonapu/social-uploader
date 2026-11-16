FROM python:3.11-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
RUN mkdir -p /data /shared/openshorts-output

# Render sets $PORT and RENDER_EXTERNAL_URL; the app then listens on 0.0.0.0:$PORT.
EXPOSE 8000
CMD ["python", "-m", "app"]
