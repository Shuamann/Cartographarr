FROM node:22-slim AS ui

WORKDIR /ui
# Lockfile first so a source edit doesn't re-resolve every package.
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci
COPY frontend/ ./
RUN npm run build


FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DATA_DIR=/data

WORKDIR /srv

# Source first, then one install. A dep-caching layer is possible by copying
# pyproject alone and faking a package dir, but that leaves an empty `app` in
# site-packages shadowing the real one, a bad trade for ~40s of rebuild.
COPY backend/pyproject.toml ./
COPY backend/app ./app
COPY backend/scripts ./scripts
RUN pip install --no-cache-dir .

# main.py looks here for the built UI and serves API-only if it's absent.
COPY --from=ui /ui/dist /srv/static

VOLUME ["/data"]
EXPOSE 6277

# No curl in slim, and adding it for one healthcheck isn't worth a layer.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:6277/health', timeout=4).status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "6277"]
