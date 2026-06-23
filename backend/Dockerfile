FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies first (better layer caching), then the package.
COPY pyproject.toml README.md ./
COPY armarius ./armarius
RUN pip install --no-cache-dir ".[postgres]"

# Skill files served at /static — agents download SKILL.md from here. The invitation
# prompt advertises this URL, so it MUST be present in the image.
COPY static ./static

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/healthz').status==200 else 1)"

CMD ["uvicorn", "armarius.main:app", "--host", "0.0.0.0", "--port", "8000"]
