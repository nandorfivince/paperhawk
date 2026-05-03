# vLLM serving on AMD MI300X

This directory contains the infrastructure to serve **Qwen 2.5 Instruct** via
[vLLM](https://github.com/vllm-project/vllm) on an **AMD Instinct MI300X**
GPU through the AMD Developer Cloud.

The Streamlit app (`app/main.py`) and the LangGraph pipeline call this
endpoint via the OpenAI-compatible REST API (`/v1/chat/completions`),
using `langchain-openai`'s `ChatOpenAI` adapter with a custom `base_url`.

---

## 1. Prerequisites

- **AMD AI Developer Program** approval (`$100` cloud credit per team member)
  - Sign up: https://www.amd.com/en/developer/ai-dev-program.html
  - Approval typically takes 2 business days, up to 1 week
- **AMD Developer Cloud** account, MI300X instance available
- **SSH access** to the MI300X instance
- (Optional) **Hugging Face token** if the model is gated (Qwen 2.5 is open,
  so this is **not required** for the default model)

---

## 2. Provision the MI300X instance

Follow the AMD Developer Cloud Getting Started guide:
https://www.amd.com/en/developer/resources/technical-articles/2025/how-to-get-started-on-the-amd-developer-cloud-.html

The default ROCm-enabled image already includes Docker and the AMD GPU
driver. Verify GPU access:

```bash
rocm-smi
# Expected: 1 × AMD Instinct MI300X listed
```

---

## 3. Pull the vLLM ROCm image

```bash
docker pull rocm/vllm:latest
```

Image size: ~30 GB (ROCm runtime + PyTorch + vLLM + dependencies).

---

## 4. Start the vLLM server

### Option A — Docker (recommended)

```bash
docker run --rm \
    --device=/dev/kfd \
    --device=/dev/dri \
    --group-add video \
    --ipc=host \
    --shm-size 16g \
    -p 8000:8000 \
    -e VLLM_MODEL=Qwen/Qwen2.5-14B-Instruct \
    -e VLLM_API_KEY=$(openssl rand -hex 32) \
    -v ~/.cache/huggingface:/root/.cache/huggingface \
    rocm/vllm:latest \
    sh -c 'vllm serve $VLLM_MODEL \
        --host 0.0.0.0 --port 8000 \
        --tensor-parallel-size 1 \
        --dtype auto \
        --gpu-memory-utilization 0.9 \
        --max-model-len 32768 \
        --api-key $VLLM_API_KEY'
```

The HF cache mount avoids re-downloading the ~28 GB Qwen 2.5 weights on
container restart.

**Print the API key** that was generated (`echo $VLLM_API_KEY` from inside
the container, or use a fixed string instead of `openssl rand`). You will
paste this into the Streamlit app's `.env` as `VLLM_API_KEY`.

### Option B — `serve.sh` directly

If vLLM is pip-installed in a ROCm-enabled environment on the host:

```bash
chmod +x infra/vllm/serve.sh
VLLM_MODEL=Qwen/Qwen2.5-14B-Instruct \
VLLM_API_KEY=<your-key> \
./infra/vllm/serve.sh
```

---

## 5. Verify the endpoint

From any machine with network access to the MI300X:

```bash
curl http://<mi300x-public-ip>:8000/v1/models \
    -H "Authorization: Bearer <your-api-key>"
```

Expected response (truncated):

```json
{
  "object": "list",
  "data": [
    {
      "id": "Qwen/Qwen2.5-14B-Instruct",
      "object": "model",
      "owned_by": "vllm",
      ...
    }
  ]
}
```

A simple chat-completion smoke test:

```bash
curl http://<mi300x-public-ip>:8000/v1/chat/completions \
    -H "Authorization: Bearer <your-api-key>" \
    -H "Content-Type: application/json" \
    -d '{
        "model": "Qwen/Qwen2.5-14B-Instruct",
        "messages": [{"role": "user", "content": "What is 2+2?"}],
        "temperature": 0.0
    }'
```

---

## 6. Connect the Streamlit app

In the project root `.env`:

```dotenv
LLM_PROFILE=vllm
VLLM_BASE_URL=http://<mi300x-public-ip>:8000/v1
VLLM_MODEL=Qwen/Qwen2.5-14B-Instruct
VLLM_API_KEY=<your-key>
```

Then start the Streamlit app:

```bash
docker compose up langgraph-app
```

Or directly:

```bash
streamlit run app/main.py
```

---

## 7. Performance benchmark (expected)

On a single AMD MI300X (192 GB HBM3, ROCm 6.2+, vLLM 0.6+):

| Metric | Qwen 2.5 14B | Qwen 2.5 32B |
|--------|--------------|--------------|
| Time-to-first-token | ~0.5 s | ~1.0 s |
| Throughput (single user) | 50-80 tok/s | 25-40 tok/s |
| Concurrent capacity (KV-cache) | ~50 sessions | ~20 sessions |
| Max context length | 32K (configured) | 32K (configured) |

These numbers depend on prompt length, batch size, and the exact ROCm/vLLM
version. Run a benchmark with `vllm bench` after startup for the actual
numbers on your instance.

---

## 8. Cost monitoring

AMD Developer Cloud MI300X pricing (as of May 2026):
- ~$4-8/hour pay-as-you-go

`$100 / team-member × 3 team-members = $300 total credit`. At $5/h, that's
**60 hours of MI300X uptime**. Plan accordingly:

- **Only run during demo/test/build sessions** — stop the instance when idle
- Keep one teammate's credit as **failover/buffer** for the final 24 hours
- Run end-to-end smoke tests early so a hot fix doesn't burn deadline-day credits

---

## 9. Plan B — local fallback if MI300X is unavailable

If the AMD credit doesn't arrive in time, or the MI300X instance has issues:

```bash
# Switch the Streamlit app to Ollama profile
LLM_PROFILE=ollama OLLAMA_MODEL=qwen2.5:7b-instruct streamlit run app/main.py
```

Pull the model first:

```bash
ollama pull qwen2.5:7b-instruct
```

This runs on a laptop GPU (or CPU) and lets development continue. Quality
will be lower (7B vs 14B/32B), but the demo-flow stays alive.

---

## 10. Production hardening (post-hackathon)

For an actual production deployment, beyond the hackathon scope:

- Use a real reverse proxy (Caddy / Nginx) with TLS instead of the raw vLLM port
- Rotate `VLLM_API_KEY` regularly
- Set up Prometheus + Grafana for vLLM `/metrics`
- Use `--quantization` flag for fp8/int8 to fit a larger model on smaller hardware
- Configure `--enable-prefix-caching` for repeated long system prompts
- Use `vllm-deploy` (sky pilot) for multi-GPU and multi-region scaling
