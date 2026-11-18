# Agentra + local Qwen: GPU laptop setup

This release adds autonomous public-web research: search, follow URLs, read pages,
and produce an answer with source quotes. It does not automate logins, forms,
purchases, file downloads, or arbitrary computer use. CAPTCHA pages stop the run.

## Friend's Windows laptop (RTX 4060 8 GB, 16 GB RAM)

1. Install Docker Desktop (Linux containers/WSL2), Ollama for Windows, and an NVIDIA driver.
2. In PowerShell, run `ollama pull qwen3.5:latest`. Model files are not inside the Agentra image.
3. Start Docker Desktop and Ollama. Keep other memory-heavy apps closed.
4. Get this repository or unpack the provided transfer bundle.
5. From its directory, run:
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts/start-friend.ps1
   ```
   If you also received `agentra-ollama.tar`, place it in the repository root and use:
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts/start-friend.ps1 -UseSavedImage
   ```
6. Open `.env` locally. Copy the value of `local` in `AGENTRA_TOKENS` into the UI's
   Connect dialog. Copy `AGENTRA_APPROVER_TOKEN` into the task's Approver credential.
   Do not share this file. Each machine generates its own credentials.
7. Enter a task, e.g. `Find today's 22K and 24K gold prices per gram in Hyderabad.
   Check the source's date and cite the source.` Click **Authorize & run**.
8. Watch the browser and task events. Stop cancels the agent loop. Completed and
   cancelled browser sessions remain inspectable; idle sessions expire. Use **Close task browser** when finished to free its browser slot.

The browser service uses CPU in Docker. Ollama uses the host GPU, so no Docker GPU
configuration is needed. Run `ollama ps` during a task to check GPU/CPU allocation.
The runner uses a 4K context, thinking disabled, at most 12 decisions by default,
and a 15-minute deadline. One research task runs at a time. Model calls time out
after 180 seconds. Ollama may retain the model for up to two minutes afterward;
`ollama stop qwen3.5:latest` releases it sooner. Cancellation closes the model HTTP
request but the server may take time to stop inference.

## If Ollama cannot be reached from Docker

The default endpoint is `http://host.docker.internal:11434`. Check it with:
```powershell
docker compose exec agentra python -c "import urllib.request; print(urllib.request.urlopen('http://host.docker.internal:11434/api/version',timeout=5).read().decode())"
```
If refused, quit Ollama from the tray and start it in a terminal with:
```powershell
$env:OLLAMA_HOST = '0.0.0.0:11434'
$env:OLLAMA_NO_CLOUD = '1'
ollama serve
```
This makes Ollama listen beyond loopback. Keep Windows Firewall blocking inbound
LAN/public access to port 11434; allow only the local Docker path if needed.
Do not expose unauthenticated Ollama to the internet.
Official configuration reference: https://docs.ollama.com/faq

## Settings and honest completion reporting

Optional `.env` settings:
```
AGENTRA_OLLAMA_URL=http://host.docker.internal:11434
AGENTRA_OLLAMA_MODEL=qwen3.5:latest
```
After editing, run `docker compose up -d`. No cloud API key is required. Internet
access is still required for websites and first-time image/model downloads.

`ANSWER_READY` / `task_completed: true` means Qwen declared an answer complete and
Agentra checked its supplied quotes occur in pages delivered to the model. This
is not independent fact checking or proof every claim is correct. Check dates,
units, and sources. Limits, unreachable Ollama, and human challenges produce
explicit incomplete/failure states. The low-level `/read` endpoint still returns
`task_completed: false`, since it only reads a page.

Task records are tenant-scoped, memory-only and capped at 50. Restarting the
container clears tasks and browser sessions. The model receives page text and
links, never API or approval credentials. The task-start approval permits public
URL navigation only; existing browser egress restrictions still apply.

## API

`POST /tasks` (Bearer tenant token):
```json
{"prompt":"Research a topic with sources","approval_token":"your separate approver token","max_steps":12}
```
Poll `GET /tasks/{id}`; stop with `DELETE /tasks/{id}`. The returned `session_id`
is the same session shown by the live presentation view.

## Sharing

The supplied tar is a local Docker image export, not a Docker Hub publication.
Share the transfer files, never your `.env`. Building from the GitHub repository
is also supported. No registry account is required for image import.

