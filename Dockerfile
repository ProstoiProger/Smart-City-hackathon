FROM node:22-alpine AS ui
WORKDIR /ui
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
COPY requirements-lock.txt ./
RUN pip install --no-cache-dir -r requirements-lock.txt
COPY backend/ ./backend/
COPY data/ ./data/
COPY run.py ./
COPY --from=ui /ui/dist ./frontend/dist/
EXPOSE 8000
CMD ["python","run.py","--host","0.0.0.0"]
