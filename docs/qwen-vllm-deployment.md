# Qwen on AMD MI300X — vLLM deployment

This guide covers the production deployment path: running Qwen 2.5 Instruct
(14B or 32B) via [vLLM](https://github.com/vllm-project/vllm) on an
**AMD Instinct MI300X** through the AMD Developer Cloud, with the Streamlit
app calling the vLLM endpoint over the OpenAI-compatible REST API.

For the canonical step-by-step (including the docker run command and a
benchmark table), see [`infra/vllm/README.md`](../infra/vllm/README.md).

## Why this stack?

- **Open source LLM** — Qwen 2.5 is Apache-2 licensed; safe for the MIT
  open-source license here, and a partner-prize bonus on the hackathon.
- **Multilingual** — Qwen 2.5 handles HU/DE/EN well, which matters for our
  multilingual demo data.
- **AMD-native** — vLLM has a ROCm build (`rocm/vllm:latest`) optimized for
  the MI300X. No CUDA, no NVIDIA dependency.
- **OpenAI-compatible API** — `langchain-openai`'s `ChatOpenAI` adapter
  works out of the box with a custom `base_url`. Tool-calling, structured
  output, and streaming all behave the same as the public OpenAI endpoint.
- **No vendor lock-in** — the same code runs against Ollama (locally) and
  against any OpenAI-compatible inference server.

## Cost monitoring

AMD Developer Cloud pricing (May 2026 ballpark):

- ~$4-8/hour pay-as-you-go for an MI300X instance.
- Each team member gets `$100` in cloud credits → 60 hours of MI300X uptime
  at $5/h. With 3 team members, ~180 hours total.

**Discipline:**

1. Only run during demo / test / build sessions; **stop the instance when
   idle**.
2. Keep one teammate's credit untouched as a final-day buffer.
3. Run end-to-end smoke tests early — a hot fix on deadline day burns hours
   you can't get back.

## Plan B: Ollama fallback

If the AMD credit doesn't arrive in time, or the MI300X has a network issue
on demo day:

```bash
LLM_PROFILE=ollama OLLAMA_MODEL=qwen2.5:7b-instruct streamlit run app/main.py
```

Pull the model first:

```bash
ollama pull qwen2.5:7b-instruct
```

Quality drops (7B vs 14B/32B), but the demo flow stays alive on a laptop
GPU or even CPU.

## Production hardening (post-hackathon)

For an actual production deployment beyond the hackathon scope:

- TLS termination (Caddy / Nginx in front of vLLM)
- API-key rotation (`--api-key` flag with a periodic rotation script)
- Prometheus + Grafana on vLLM `/metrics`
- `--quantization fp8` to fit a larger model on smaller hardware
- `--enable-prefix-caching` for repeated long system prompts
- Multi-GPU / multi-region scaling via SkyPilot or vLLM Production Stack
