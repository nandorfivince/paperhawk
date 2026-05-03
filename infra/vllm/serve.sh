#!/bin/bash
# Run vLLM with Qwen 2.5 Instruct on AMD MI300X.
#
# Usage:
#   ./infra/vllm/serve.sh
#
# Required env vars:
#   VLLM_MODEL — e.g. "Qwen/Qwen2.5-14B-Instruct" (default if unset)
#   HF_TOKEN   — Hugging Face token if you use gated models (Qwen 2.5 is open)
#   VLLM_API_KEY — optional API key for client auth
#
# Run on the AMD Developer Cloud MI300X instance after `docker pull rocm/vllm:latest`.
# Or directly if vLLM is pip-installed in a ROCm-enabled environment.

set -euo pipefail

VLLM_MODEL="${VLLM_MODEL:-Qwen/Qwen2.5-14B-Instruct}"
VLLM_PORT="${VLLM_PORT:-8000}"
VLLM_API_KEY_ARG=""

if [ -n "${VLLM_API_KEY:-}" ]; then
    VLLM_API_KEY_ARG="--api-key ${VLLM_API_KEY}"
fi

echo "Starting vLLM server"
echo "  model: ${VLLM_MODEL}"
echo "  port:  ${VLLM_PORT}"
echo "  api-key auth: $([ -n "${VLLM_API_KEY:-}" ] && echo enabled || echo disabled)"
echo ""

vllm serve "${VLLM_MODEL}" \
    --host 0.0.0.0 \
    --port "${VLLM_PORT}" \
    --tensor-parallel-size 1 \
    --dtype auto \
    --gpu-memory-utilization 0.9 \
    --max-model-len 32768 \
    ${VLLM_API_KEY_ARG}
