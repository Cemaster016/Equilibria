# Equilibria — Deployment Guide
## React Frontend (Vercel) + FastAPI Backend (Render)

Both are **free tiers**, no credit card required for basic usage.

---

## STEP 1 — Prepare your GitHub repo

First, commit your cached Kano data so Render doesn't need to re-download
500MB of WorldPop rasters on every deploy.

```bash
cd C:\Users\USER\Documents\Projects\Equilibria\equilibria

# Tell git to track the cached demo data
# Remove data/* from .gitignore for the processed folder only
git add data/processed/kano_state_nigeria/
git add data/raw/roads/
git add data/raw/population/

git add .
git commit -m "Add deployment config + cached Kano demo data"
git push origin main
```

---

## STEP 2 — Copy deployment files into your project

Copy these files from the deployment pack:

| File | Where to put it in your project |
|---|---|
| `Dockerfile` | project root (next to `pyproject.toml`) |
| `render.yaml` | project root |
| `api.py` | `src/equilibria/api.py` |
| `vercel.json` | `frontend/vercel.json` |
| `frontend.env.development` | rename to `frontend/.env.development` |
| `frontend.env.production` | rename to `frontend/.env.production` |

---

## STEP 3 — Update your React app to use VITE_API_URL

In your React frontend, wherever you call the backend, replace
any hardcoded `http://localhost:8000` with:

```typescript
const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

// Example fetch call
const response = await fetch(`${API_URL}/api/run`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ prompt: userPrompt })
})
```

---

## STEP 4 — Deploy the backend on Render

1. Go to **https://render.com** and sign up (free, GitHub login works)
2. Click **"New +"** → **"Web Service"**
3. Connect your GitHub repo
4. Render will detect `render.yaml` automatically — click **"Apply"**
5. Go to your service → **Environment** tab → add two Secret variables:
   - `GOOGLE_API_KEY` = your AI Studio key
   - `GROQ_API_KEY` = your Groq key
6. Click **"Manual Deploy"** → **"Deploy latest commit"**
7. Wait 5–10 minutes for the Docker build
8. Your backend URL will be: `https://equilibria-api.onrender.com`
   (Render gives you this URL on the service dashboard)

**Test it works:**
```bash
curl https://equilibria-api.onrender.com/api/health
# Should return: {"status":"ok","message":"Equilibria API is ready."}
```

---

## STEP 5 — Deploy the frontend on Vercel

1. Go to **https://vercel.com** and sign up (free, GitHub login works)
2. Click **"Add New"** → **"Project"**
3. Import your GitHub repo
4. Set **Root Directory** to `frontend`
5. Set **Framework Preset** to `Vite`
6. Under **Environment Variables**, add:
   - `VITE_API_URL` = `https://equilibria-api.onrender.com`
     (your actual Render URL from Step 4)
7. Click **"Deploy"**
8. Your frontend URL will be: `https://equilibria-yourname.vercel.app`

---

## STEP 6 — Test the full stack

Open your Vercel URL in a browser. Type:

```
Suggest 3 new clinic sites in Kano State, Nigeria
```

Click Run. The frontend calls the Render backend, which runs the
7-agent pipeline and returns the map + report.

---

## Important: Render Free Tier Behaviour

Render's free tier **spins down after 15 minutes of inactivity**.
The first request after a spin-down takes ~30 seconds to wake up.
This is fine for a demo — just warn the judges or click the app once
before your demo to wake it up.

To keep it awake during your demo window, use UptimeRobot (free):
1. Go to https://uptimerobot.com → sign up
2. Add a new HTTP monitor pointing to:
   `https://equilibria-api.onrender.com/api/health`
3. Set interval to 14 minutes
This keeps your backend warm during the demo.

---

## Your final Kaggle submission links

After deployment, your submission should include:
- **GitHub repo**: `https://github.com/YOUR_USERNAME/equilibria`
- **Live demo**: `https://equilibria-yourname.vercel.app`
- **Demo video**: your YouTube link

---

## Troubleshooting

**CORS error in browser console:**
The `api.py` already sets `allow_origins=["*"]` — if you still see CORS
errors, check that your `VITE_API_URL` in Vercel has no trailing slash.

**502 Bad Gateway on Render:**
Check Render logs → usually means the Docker build failed. Most common
cause: a missing dependency in `pyproject.toml`. Check the build log.

**Map not rendering:**
The folium map HTML is 68MB. Some browsers throttle large HTML blobs in
`dangerouslySetInnerHTML`. Use `<iframe srcDoc={...}>` instead of
`dangerouslySetInnerHTML` for the map tab in your React component.

**Render build timeout:**
GeoPandas + OSMnx + scipy take ~8 minutes to build. This is within
Render's free tier build limit. If it times out, trigger a manual redeploy.
