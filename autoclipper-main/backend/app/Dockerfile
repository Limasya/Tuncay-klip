    #### `backend/Dockerfile`
    ```dockerfile
    # backend/Dockerfile
    
    # 1. Base image with Python
    FROM python:3.10-slim
    
    # 2. Install OS-level deps (FFmpeg for clipping)
    RUN apt-get update \
        && apt-get install --no-install-recommends -y \
           ffmpeg \
        && rm -rf /var/lib/apt/lists/*
    
    # 3. Set workdir
    WORKDIR /app
    
    # 4. Copy & install Python deps
    COPY requirements.txt .
    RUN pip install --no-cache-dir -r requirements.txt
    
    # 5. Copy application code
    COPY ./app ./app
    COPY celery_app.py ./
    
    # 6. Expose port for FastAPI
    EXPOSE 8000
    
    # 7. Entrypoint script that starts Celery + Uvicorn
    COPY docker-entrypoint.sh /usr/local/bin/
    RUN chmod +x /usr/local/bin/docker-entrypoint.sh
    ENTRYPOINT ["docker-entrypoint.sh"]