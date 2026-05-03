# vLLM serving on AMD MI300X via ROCm.
#
# Build:
#   docker build -t document-intelligence-vllm:latest -f infra/vllm/Dockerfile .
#
# Run on the AMD Developer Cloud MI300X instance:
#   docker run --rm --device=/dev/kfd --device=/dev/dri --group-add video \
#     -p 8000:8000 \
#     -e VLLM_MODEL=Qwen/Qwen2.5-14B-Instruct \
#     -e HF_TOKEN=<your-hf-token-if-gated> \
#     document-intelligence-vllm:latest
#
# The base image (rocm/vllm) bundles ROCm + vLLM + PyTorch ROCm wheels.
# Qwen 2.5 weights are NOT preloaded — vLLM downloads on first run (~28 GB).
# To preload at build time, uncomment the snapshot_download block below.

FROM rocm/vllm:latest

ENV PYTHONUNBUFFERED=1

# Optional: preload Qwen 2.5 14B Instruct weights (~28 GB) at build time.
# This bloats the image but eliminates first-run download latency.
# RUN python -c "from huggingface_hub import snapshot_download; \
#     snapshot_download('Qwen/Qwen2.5-14B-Instruct')"

EXPOSE 8000

# vLLM serve via shell so $VLLM_MODEL expands at runtime.
# --tensor-parallel-size 1: single MI300X has 192 GB HBM, fits 14B easily.
# --gpu-memory-utilization 0.9: leave 10% headroom for KV cache.
# --max-model-len 32768: Qwen 2.5 native context is 128K, but 32K is plenty
#                       for document workloads and saves KV memory.
CMD ["sh", "-c", "vllm serve $VLLM_MODEL \
    --host 0.0.0.0 \
    --port 8000 \
    --tensor-parallel-size 1 \
    --dtype auto \
    --gpu-memory-utilization 0.9 \
    --max-model-len 32768"]
