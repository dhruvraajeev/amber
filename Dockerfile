# Amber in one image: the API and the built UI on one origin (plan §15.1).
#   docker build -t amber .
#   docker run -p 8000:8000 amber        → http://localhost:8000

# Stage 1: build the UI. Only frontend/dist leaves this stage; node is not in the final image.
# The output is plain JS/CSS, so it builds once on the build machine's own platform, never emulated.
FROM --platform=$BUILDPLATFORM node:24-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY shared/ /app/shared/
COPY frontend/ ./
RUN npm run build

# Stage 2: the Python app. The layout under /app mirrors the repo, which is how the code finds
# shared/ and frontend/dist.
FROM python:3.12-slim
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app/backend
# Dependencies first, in their own layer, so a code change doesn't reinstall them. uv is mounted only
# while installing, never copied in: at runtime it would be 43 MB of dead weight.
COPY backend/pyproject.toml backend/uv.lock ./
RUN --mount=from=ghcr.io/astral-sh/uv:0.11,source=/uv,target=/bin/uv \
    uv sync --frozen --no-dev --no-install-project
COPY backend/amber/ ./amber/
RUN --mount=from=ghcr.io/astral-sh/uv:0.11,source=/uv,target=/bin/uv \
    uv sync --frozen --no-dev
COPY shared/ /app/shared/
COPY --from=frontend /app/frontend/dist/ /app/frontend/dist/

RUN useradd --system --no-create-home amber
USER amber

ENV PATH="/app/backend/.venv/bin:$PATH"
# Take the client IP from X-Forwarded-For only when the hop in front is on a private network (Azure's
# ingress), never "*": with "*" uvicorn believes the client's own first entry, so anyone could dodge the
# per-IP rate limit. Overridable at deploy time without a rebuild.
ENV FORWARDED_ALLOW_IPS="10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,100.64.0.0/10,127.0.0.1"
# The commit this image was built from (publish.yml passes it); /healthz reports it. Last, so it never
# invalidates the layers above.
ARG AMBER_SHA=dev
ENV AMBER_SHA=$AMBER_SHA
EXPOSE 8000
# The slim image has no curl, so the check is Python's own urllib.
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"]
CMD ["uvicorn", "amber.api.app:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
