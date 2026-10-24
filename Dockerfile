FROM node:22-slim AS web
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ backend/
COPY --from=web /app/frontend/dist frontend/dist
# Trust X-Forwarded-For only from the platform's own proxy (Railway / Render reach the container from
# private addresses). uvicorn then takes the rightmost address that proxy appended, not whatever the
# client wrote in front of it. Set FORWARDED_ALLOW_IPS if another proxy (a CDN) sits in front.
ENV PORT=8000 DATA_DIR=/data \
    FORWARDED_ALLOW_IPS=127.0.0.1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,100.64.0.0/10,fc00::/7
RUN mkdir -p /data
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips=\"${FORWARDED_ALLOW_IPS}\""]
