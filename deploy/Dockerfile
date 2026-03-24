# ---- Stage 1: Build ----
FROM python:3.12-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl git ca-certificates && rm -rf /var/lib/apt/lists/*

# Install Node.js 20
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    rm -rf /var/lib/apt/lists/*

# Install poetry
RUN pip install --no-cache-dir poetry

WORKDIR /app

# Install Python deps first (cached layer)
COPY pyproject.toml poetry.lock ./
RUN poetry config virtualenvs.in-project true && \
    poetry install --only main --no-root --no-interaction

# Copy full repo (lens package + datasets + UI source)
COPY . .

# Install the lens package itself
RUN poetry install --only main --no-interaction

# Build frontend
RUN cd lens/server/ui && npm install --no-package-lock && npm run build

# ---- Stage 2: Runtime ----
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    git openssh-client ca-certificates curl gnupg && \
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
        | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg && \
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
        | tee /etc/apt/sources.list.d/caddy-stable.list && \
    apt-get update && apt-get install -y --no-install-recommends caddy && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy full app tree from builder (venv + lens package + datasets + built UI)
COPY --from=builder /app /app

# Deploy support files
COPY deploy/Caddyfile /etc/caddy/Caddyfile
COPY deploy/start.sh /app/deploy/start.sh
RUN chmod +x /app/deploy/start.sh

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

EXPOSE 8080

ENTRYPOINT ["/app/deploy/start.sh"]
