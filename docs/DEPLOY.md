# Deployment guide

This app is a **Python FastAPI server** with Playwright and the Claude agent SDK. GitHub Pages hosts only the static landing page in `docs/`. The live builder runs on a compute host.

## Architecture

```
Browser ──► FastAPI (stateless API)
              ├── POST /api/jobs/capture  → job queue
              ├── GET  /api/jobs/{id}     → poll status
              ├── GET  /health            → readiness
              └── /chat, /sse, …          → agent UI

Job queue ──► worker pool (CAPTURE_WORKERS) ──► Playwright/Chromium
```

Env vars:

| Variable | Default | Purpose |
|----------|---------|---------|
| `PORT` | `8000` | HTTP port |
| `CAPTURE_WORKERS` | `2` | Max concurrent capture jobs |
| `QUOTA_PER_HOUR` | `30` | Jobs per client key per hour |
| `AGENT_MODEL` | `haiku` | Claude model for agent loop |

Clients are keyed by `X-API-Key` header, else first `X-Forwarded-For` hop, else `anonymous`.

---

## 1. GitHub Pages (landing site)

1. Push `main` to https://github.com/AndyUneducated/lumalabs
2. Repo **Settings → Pages → Build and deployment**
   - Source: **GitHub Actions**
3. The workflow `.github/workflows/pages.yml` deploys `docs/` on every push to `main`
4. Site URL: **https://andyuneducated.github.io/lumalabs/**

---

## 2. Docker (local or any host)

```bash
cp .env.example .env   # add keys / use Claude CLI login in container
docker compose up --build
# open http://localhost:8000
curl http://localhost:8000/health
```

---

## 3. Render (public API URL)

1. Connect the GitHub repo at [render.com](https://render.com)
2. Use the included `render.yaml` (Docker web service)
3. Add secrets in the Render dashboard (`ANTHROPIC_API_KEY` or ship Claude CLI)
4. Note the public URL, e.g. `https://lumalabs-builder.onrender.com`
5. Update `docs/index.html` `API_URL` (or use browser `localStorage.setItem('lumalabs_api', 'https://…')`)

Health check: `GET /health`

---

## 4. Verify before submit

```bash
pip install -r requirements.txt httpx
python scripts/verify_phase7.py   # queue + API
./submit.sh
```

---

## 5. Push checklist

```bash
git add -A
git commit -m "Add scalable job API, Docker, and GitHub Pages deploy"
git push origin main
```

After push: CI runs verify scripts; Pages workflow publishes `docs/`.
