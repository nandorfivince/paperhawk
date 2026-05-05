# AMD MI300X Deployment

How we deployed Qwen 2.5 14B Instruct via vLLM on AMD Instinct MI300X using the AMD Developer Cloud (DigitalOcean-powered). End-to-end, with copy-paste commands and the costs we actually paid.

---

## What you get

- **AMD Instinct MI300X** — 192 GB HBM3 GPU, 20 vCPU, 240 GB RAM, 720 GB NVMe boot disk
- **vLLM 0.17.1 + ROCm 7.0** — pre-installed via the Quick Start image
- **OpenAI-compatible REST endpoint** at `http://<droplet-ip>:8000/v1`
- **Cost**: $1.99 / GPU / hour. Free $100 credit covers ~50 hours.

---

## Prerequisites

1. **AMD AI Developer Program signup** — <https://www.amd.com/en/developer/ai-dev-program.html>
   - Approval takes 1–2 business days; you receive a $100 cloud credit by email automatically
2. **lablab.ai event Enroll** (for hackathon participants) — <https://lablab.ai/event/amd-developer-hackathon>
3. **SSH key on your local machine** (we recommend a dedicated key, not your default GitHub key — see step 1 below)

---

## Step 1 — Generate a dedicated SSH key

The default `~/.ssh/id_ed25519` is often passphrase-protected and routed through a GNOME-keyring agent that interferes with non-interactive `ssh-add`. Sidestep it with a passphrase-less, dedicated key:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_amd_paperhawk -N "" -C "you@paperhawk-amd"
cat ~/.ssh/id_ed25519_amd_paperhawk.pub
```

Copy the public key to clipboard for the next step.

---

## Step 2 — Create a GPU Droplet

Go to <https://cloud.amd.com/> (or <https://amd.digitalocean.com/>) and click **Create a GPU Droplet** on the homepage card.

**Caution**: the left-sidebar `GPU Droplets` link routes to the CPU Droplet flow as of May 2026 (a UI bug). Use the homepage card or the top-right `Create ▼` dropdown.

### Configuration

- **GPU Plan**: AMD MI300X (single-GPU, $1.99/hr) — **not** the 8-GPU variant
- **Region**: ATL1 (Atlanta) — NYC1 is often "out of capacity" for MI300X. If the Plan card is greyed out, the URL parameter `?region=atl1` switches you over.
- **Image**: Quick Start → vLLM (0.17.1, ROCm 7.0) — comes with Docker, JupyterLab, and a pre-built `rocm` container
- **SSH Key**: Add a new key, paste the public key from step 1, name it `paperhawk-amd-deploy`
- **Visibility**: doesn't matter; the droplet is private to your account

Click **Create GPU Droplet**. It takes 5–10 minutes to come up. Once `Active`, note the Public IPv4 address.

---

## Step 3 — SSH in

```bash
ssh -i ~/.ssh/id_ed25519_amd_paperhawk -o IdentityAgent=none root@<DROPLET_IP>
```

The `-o IdentityAgent=none` flag bypasses the GNOME-keyring SSH agent if it's misbehaving on your local machine.

You'll see a welcome banner with two key facts:

```
Access the Jupyter Server: http://<IP>:80   (we don't use this)
docker exec -it rocm /bin/bash              (we DO use this)
```

---

## Step 4 — Open port 8000 in the firewall

The Quick Start image ships with UFW enabled, allowing only SSH (22), HTTP (80), and HTTPS (443). vLLM runs on 8000, so we need to open it:

```bash
ufw allow 8000
ufw status | grep 8000
```

You should see `8000 ALLOW Anywhere` and the IPv6 equivalent.

The `--api-key` flag we pass to vLLM in step 6 prevents anyone scanning the public internet from using your endpoint — opening port 8000 is safe with API-key auth.

---

## Step 5 — (Optional) System upgrade and reboot

The Quick Start image ships with ~120 outdated packages including security updates. Recommended before snapshotting:

```bash
apt-get update && DEBIAN_FRONTEND=noninteractive apt-get upgrade -y
reboot
```

Wait ~1.5–2 minutes, then SSH in again. **The `rocm` Docker container does not auto-restart after the reboot**, so:

```bash
docker start rocm
docker ps   # confirm `rocm` is Up
```

---

## Step 6 — Start vLLM serving Qwen 2.5 14B

Enter the Docker container:

```bash
docker exec -it rocm /bin/bash
```

Run vLLM in one long line (line continuations with `\` sometimes break under paste — single-line is most reliable):

```bash
vllm serve Qwen/Qwen2.5-14B-Instruct --api-key sk-paperhawk-2026 --port 8000 --host 0.0.0.0 --enable-auto-tool-choice --tool-call-parser hermes --trust-remote-code
```

What this does:

| Flag | Why |
|---|---|
| `Qwen/Qwen2.5-14B-Instruct` | Model ID on Hugging Face Hub. vLLM auto-downloads on first run (~28 GB, ~6 sec from ATL DC) |
| `--api-key sk-paperhawk-2026` | Bearer token required by every request. Anti-misuse for the public-internet endpoint. |
| `--port 8000` | OpenAI-compat REST at `:8000/v1` |
| `--host 0.0.0.0` | Bind on all interfaces so the public IP is reachable |
| `--enable-auto-tool-choice` + `--tool-call-parser hermes` | Required for our 5-tool agentic chat. Qwen 2.5 uses Hermes-style tool calls. |
| `--trust-remote-code` | Tokenizer ships custom code; flag is no-op for Qwen 2.5 but kept for compatibility |

**What you'll see on first run** (~70 seconds total):

```
INFO 05-04 20:56:36 [utils.py:302]  ▄▄ ▄█ █     █     █ ▀▄▀ █  version 0.17.1
INFO 05-04 20:56:36 [utils.py:302]   █▄█▀ █     █     █     █  model   Qwen/Qwen2.5-14B-Instruct
config.json: 100%|████████████████████| 663/663 [00:00<00:00, 8.25MB/s]
model-00001-of-00008.safetensors: 100%|██████| 3.89G/3.89G [00:05<00:00, 745MB/s]
... (8 shards, ~28 GB total in 5.9 sec)
INFO 05-04 20:57:08 [gpu_model_runner.py:4364] Model loading took 27.63 GiB memory and 17.358448 seconds
INFO 05-04 20:57:32 [gpu_worker.py:424] Available KV cache memory: 141.96 GiB
INFO 05-04 20:57:32 [kv_cache_utils.py:1314] GPU KV cache size: 775,280 tokens
INFO 05-04 20:57:32 [kv_cache_utils.py:1319] Maximum concurrency for 32,768 tokens per request: 23.66x
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

The vLLM server now serves OpenAI-compatible requests. **Don't close this SSH session** — closing it kills the server. Open a second SSH window for the smoke test.

---

## Step 7 — Smoke-test the endpoint

From your local machine:

```bash
# List models
curl http://<DROPLET_IP>:8000/v1/models -H "Authorization: Bearer sk-paperhawk-2026"

# Chat completion
curl http://<DROPLET_IP>:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-paperhawk-2026" \
  -d '{"model":"Qwen/Qwen2.5-14B-Instruct","messages":[{"role":"user","content":"Hello, who are you? Answer in one sentence."}],"max_tokens":50,"temperature":0}'
```

Expected response: `"I am Qwen, a large language model created by Alibaba Cloud."`

If you get `401 Unauthorized`, the Bearer token is wrong (must match the `--api-key` value exactly). If you get `Connection refused`, port 8000 isn't open or the vLLM server didn't start — check the SSH window from step 6.

---

## Step 8 — Snapshot the droplet (cost optimization)

Once everything works, take a live snapshot. It captures the entire boot disk (~96 GB including the Docker container with the cached Qwen model), so a future restart is **30 seconds** instead of a 70-second cold start.

In the AMD Cloud UI:

1. Droplet → **Backups & Snapshots** tab → **Take a Snapshot**
2. Name: `paperhawk-vllm-tested-YYYY-MM-DD`
3. Click **Take Live Snapshot** (live works fine — vLLM does only read-only inference)

The snapshot takes 10–15 minutes. Storage cost: $0.06 / GB / month × ~96 GB = **~$0.32 / day**.

---

## Step 9 — Destroy the droplet (stop the meter)

When you're done with the dev session, **destroy** the droplet (do not just power-off — powered-off droplets still bill at $1.99/hr).

In the UI: Droplet → **Actions** ▼ → **Destroy** → type the droplet name to confirm.

**Important**: when the destroy dialog asks if you also want to destroy the snapshot, **leave it unchecked**. The snapshot survives the destroy and is what you'll use to recreate the droplet.

---

## Step 10 — Recreate from snapshot (Friday morning)

When you need the endpoint live again (e.g., for a demo or judging window):

1. AMD Cloud → **Backups & Snapshots** → click `…` next to your snapshot → **Create GPU Droplet**
2. Configuration: same MI300X / ATL1 / SSH key
3. Wait 5–10 minutes for `Active`. Note the new public IP.

Then SSH in (with the new IP) and:

```bash
docker start rocm
docker exec -it rocm /bin/bash
vllm serve Qwen/Qwen2.5-14B-Instruct --api-key sk-paperhawk-2026 --port 8000 --host 0.0.0.0 --enable-auto-tool-choice --tool-call-parser hermes --trust-remote-code
```

Because the snapshot includes the cached model in the Docker container layer, **vLLM startup is ~30 seconds** instead of 70.

---

## Live performance numbers (measured)

From our end-to-end test on May 5, 2026:

| Metric | Value |
|---|---|
| HF Hub model download (8 safetensors, 28 GB) | 5.9 sec (700+ MB/s from ATL DC) |
| Model load to MI300X VRAM | 17.4 sec |
| CUDA graph compile (51 size-buckets) | 20.5 sec |
| **Total cold-start** | **~70 sec** |
| **Warm restart from snapshot** | **~30 sec** |
| Available KV cache (192 GB − 27.6 GB model − 22 GB headroom) | 141.96 GiB |
| KV cache token capacity | 775,280 tokens |
| Max concurrency at 32k context | 23.66× parallel requests |
| Prompt throughput (live audit demo) | 307 tokens/sec |
| Generation throughput (live audit demo) | 252 tokens/sec |
| Prefix cache hit rate (multi-agent prompts) | 30.4% |
| End-to-end audit demo (3 PDFs from HF Space) | 23.3 sec / 61.7× speedup vs manual |

---

## Cost breakdown (our actual hackathon spend)

| Item | Cost |
|---|---|
| Initial dev session (provisioning, vLLM setup, debugging) | ~$3 |
| Live validation session (30 minutes) | ~$1 |
| Snapshot storage (5 days from Tuesday to Friday) | ~$1.60 |
| Live judging window (estimated 24 hours) | ~$48 |
| **Total estimated** | **~$54** of the free $100 credit |

Plenty of buffer for a longer judging window or a second iteration.

---

## Common pitfalls

- **"Out of capacity in the selected region"**: Switch to ATL1. NYC1 frequently runs out of MI300X. Pass `?region=atl1` in the Create-Droplet URL.
- **`Permission denied (publickey)` on SSH**: Either the `~/.ssh/id_ed25519` is passphrase-protected and the agent isn't unlocked, or you have the wrong key. Use a dedicated passphrase-less key (step 1) and `-o IdentityAgent=none` on the ssh command.
- **vLLM exits with `Triton FlashAttention error` on first run**: Older vLLM 0.8.x builds had this issue. The 0.17.1 + ROCm 7.0 build we use has it fixed. If you're stuck on an older image, prefix with `VLLM_USE_TRITON_FLASH_ATTN=0`.
- **Docker container `rocm` not running after reboot**: Manual `docker start rocm`. Not auto-started by default.
- **Powered-off droplet still billing**: Power-off does **not** stop billing. Only **Destroy** does. Snapshot first if you want to keep the state.

---

## Cross-references

- [`docs/HUGGINGFACE_DEPLOYMENT.md`](HUGGINGFACE_DEPLOYMENT.md) — how the Streamlit Space talks to this vLLM endpoint
- [`docs/ARCHITECTURE.md`](ARCHITECTURE.md) — how the application uses the vLLM endpoint via the provider abstraction
- [`docs/AMD_DEPLOY_LESSONS_LEARNED.md`](AMD_DEPLOY_LESSONS_LEARNED.md) — extended history of every push iteration, error message, and workaround we hit
