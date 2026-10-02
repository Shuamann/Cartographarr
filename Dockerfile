# ffmpeg and ffprobe, for tidying a file's tracks: converting styled subtitles,
# dropping duplicates, adding an audio track everything can play, repackaging
# an old container. None of it re-encodes the picture.
#
# Two static binaries copied from a pinned image rather than apt, which pulls
# four hundred Debian packages and takes ten minutes on a home line. Pulled in
# parallel with the stage below, and the feature is simply off without them.
FROM mwader/static-ffmpeg:9.0.2 AS ffmpeg

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

# Above the source, so an ordinary code change never recopies them.
COPY --from=ffmpeg /ffmpeg /ffprobe /usr/local/bin/

# Source first, then one install. A dep-caching layer is possible by copying
# pyproject alone and faking a package dir, but that leaves an empty `app` in
# site-packages shadowing the real one, a bad trade for ~40s of rebuild.
COPY backend/pyproject.toml ./
COPY backend/app ./app
COPY backend/scripts ./scripts
# pip itself ships with advisories against it in the base image, and it is
# the one package here that installs other packages.
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir .

# main.py looks here for the built UI and serves API-only if it's absent.
COPY --from=ui /ui/dist /srv/static
COPY CHANGELOG.md ./

# The commit this was built from, for update checks. Optional: without it they
# compare version numbers. Last, so a new commit rebuilds nothing above.
ARG GIT_COMMIT=""
ENV GIT_COMMIT=${GIT_COMMIT}

VOLUME ["/data"]
EXPOSE 6277

# No curl in slim, and adding it for one healthcheck isn't worth a layer.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:6277/health', timeout=4).status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "6277"]
