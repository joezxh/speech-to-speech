#!/bin/sh
for u in \
  "https://download-r2.pytorch.org/whl/cu128/torch-2.11.0%2Bcu128-cp312-cp312-manylinux_2_28_x86_64.whl.metadata" \
  "https://download-r2.pytorch.org/whl/triton-3.9.0-cp312-abi3-manylinux_2_27_aarch64.manylinux_2_28_aarch64.whl.metadata" \
  "https://download-r2.pytorch.org/whl/cu130/torch-2.14.1%2Bcu130-cp312-cp312-manylinux_2_28_x86_64.whl.metadata"; do
  echo "--- $u"
  curl -sS -o /dev/null -w 'HTTP %{http_code} in %{time_total}s\n' --max-time 20 "$u" 2>&1
done
