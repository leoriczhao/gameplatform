# ---- frontend build stage (React + Vite + shadcn/ui + Tailwind) ----
FROM node:22-alpine AS webbuild
WORKDIR /build
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund --fetch-retries=5
COPY web/ ./
RUN npm run build

# ---- runtime stage ----
# GamePlatform — multi-game RL platform
# Serves the lobby + per-game frontends and a small JSON API, with pure-numpy
# inference where a game ships a model (no torch on purpose: the image stays
# small, fits a machine with ~8GB free disk).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends libseccomp2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/backend

COPY backend/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt

COPY backend/ /app/backend/
COPY static-docs/ /app/static-docs/
COPY packaged-games/ /app/packaged-games/
COPY --from=webbuild /build/dist /app/web/dist
# Normalize permissions regardless of the build machine's umask.
RUN chmod -R a+rX /app/backend /app/static-docs /app/web /app/packaged-games

# Non-root runtime user; /data holds the SQLite leaderboard.
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /data \
    && chown appuser:appuser /data
USER appuser

EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=4s --start-period=10s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/api/ready', timeout=3).status == 200 else 1)"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
