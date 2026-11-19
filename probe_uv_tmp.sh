#!/bin/sh
uv venv /tmp/testv >/dev/null 2>&1
echo "=== uv install torch from cu128 (no proxy) ==="
env UV_INDEX_URL=https://download.pytorch.org/whl/cu128 UV_TIMEOUT=60 UV_RETRIES=1 \
  uv pip install --python /tmp/testv/bin/python --dry-run 'torch==2.11.0+cu128' 2>&1 | tail -12
echo "=== uv with SSL_CERT_FILE unset + native TLS ==="
env -u SSL_CERT_FILE -u REQUESTS_CA_BUNDLE \
  UV_INDEX_URL=https://download.pytorch.org/whl/cu128 UV_TIMEOUT=60 UV_RETRIES=1 \
  UV_NATIVE_TLS=true \
  uv pip install --python /tmp/testv/bin/python --dry-run 'torch==2.11.0+cu128' 2>&1 | tail -8
