# Auto-Clipper

This project automatically clips highlights from predefined YouTube channels or live Twitch/Kick streams, generates subtitles, and uploads them to a target YouTube channel. It consists of:

- **backend/**: FastAPI service, Celery workers, and clipping/subtitling/upload logic.  
- **frontend/**: React dashboard to configure source and target channels.  
- **docker-compose.yml**: Orchestrates Redis, backend, and frontend.

---

## Deployment & Hosting (Google Cloud Run)

### 1. Enable billing & APIs  
```bash
gcloud config set project YOUR_PROJECT_ID  
gcloud beta billing projects link YOUR_PROJECT_ID --billing-account=YOUR_BILLING_ACCOUNT_ID  
gcloud services enable run.googleapis.com cloudbuild.googleapis.com redis.googleapis.com  

gcloud redis instances create auto-clipper-redis \
  --size=1 --tier=basic \
  --region=us-central1 \
  --redis-version=redis_6_x

# Backend  
docker build -f backend/Dockerfile -t gcr.io/$GOOGLE_CLOUD_PROJECT/auto-clipper-backend:latest .  
docker push     gcr.io/$GOOGLE_CLOUD_PROJECT/auto-clipper-backend:latest  

# Frontend  
docker build -f frontend/Dockerfile -t gcr.io/$GOOGLE_CLOUD_PROJECT/auto-clipper-frontend:latest .  
docker push     gcr.io/$GOOGLE_CLOUD_PROJECT/auto-clipper-frontend:latest  

gcloud run deploy auto-clipper-backend \
  --image gcr.io/$GOOGLE_CLOUD_PROJECT/auto-clipper-backend:latest \
  --region us-central1 \
  --platform managed \
  --allow-unauthenticated \
  --set-env-vars REDIS_URL=redis://<REDIS_IP>:6379,\
YOUTUBE_API_KEY=<YT_KEY>,OPENAI_API_KEY=<OPENAI_KEY>

gcloud run deploy auto-clipper-frontend \
  --image gcr.io/$GOOGLE_CLOUD_PROJECT/auto-clipper-frontend:latest \
  --region us-central1 \
  --platform managed \
  --allow-unauthenticated
