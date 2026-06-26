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

**Do this once before the workflow can succeed** — otherwise `configure-pages` returns `Not Found`.

1. Open https://github.com/AndyUneducated/lumalabs/settings/pages
2. Under **Build and deployment → Source**, choose **GitHub Actions** (not “Deploy from a branch”)
3. Push `main` (or re-run the **Deploy GitHub Pages** workflow under Actions)
4. Site URL: **https://andyuneducated.github.io/lumalabs/**

The workflow `.github/workflows/pages.yml` uploads `docs/` on every push to `main`.

### Troubleshooting Pages deploy

| Symptom | Fix |
|---------|-----|
| `Get Pages site failed … Not Found` | Pages not enabled yet — complete step 2 above, then re-run the workflow |
| `Node 20 is being deprecated` | Informational only; `configure-pages@v5` runs on Node 24 |
| Workflow green but 404 on URL | Wait 1–2 min; check Actions → latest deploy job for the `page_url` |

`enablement: true` on `configure-pages` only works with a PAT (not `GITHUB_TOKEN`), so manual enablement in Settings is the reliable path.

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
