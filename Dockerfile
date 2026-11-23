FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md /app/
COPY src /app/src

# A hash of the shipped source, exposed in the UI and /healthz. If the top bar
# shows a different value from `make build-id`, the container is stale.
RUN find src -type f ! -path '*/__pycache__/*' ! -name '*.pyc' -print0 \
    | LC_ALL=C sort -z | xargs -0 sha256sum | sha256sum | cut -c1-12 > /app/BUILD_ID

RUN pip install --upgrade pip && pip install .

ENV KB_ADDONS_PATH=/app/src/kberp/addons

EXPOSE 8069

CMD ["kberp", "run", "--host", "0.0.0.0", "--port", "8069"]
