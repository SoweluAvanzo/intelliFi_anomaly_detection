# Minimal, reproducible image for the Polymarket v2 tape crawler (outbound-only).
FROM python:3.11-slim AS base
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
# Non-root user; the container also runs with no-new-privileges + cap_drop ALL.
RUN useradd -m -u 10001 crawler
WORKDIR /app
# Deps first for layer caching. Crawl-only subset (no notebook/analysis extras).
# (No README.md at repo root; pyproject doesn't reference one.)
COPY pyproject.toml ./
COPY src ./src
# eth-hash (keccak, used by intellifi.fills/ctf/resolutions) + its pycryptodome
# backend are required at import time but missing from pyproject deps — pin to the
# lockfile versions. (Flag to repo owner: add eth-hash to pyproject dependencies.)
RUN pip install --upgrade pip && pip install -e . && pip install duckdb 'eth-hash[pycryptodome]==0.8.0'
COPY scripts ./scripts
COPY deploy/remote_crawler/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh && mkdir -p /data && chown -R crawler:crawler /app /data
USER crawler
ENV INTELLIFI_DATA_DIR=/data
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
