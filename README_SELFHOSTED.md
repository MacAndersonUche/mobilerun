# 🏠 Self-Hosted Mobilerun Control Center

> Transform your PC into a complete mobile automation control center with wireless device control, modern web UI, and LLM-powered agent execution.

## 🚀 Quick Start (Primary Workflow)

**One command to run everything:**

```bash
# Install mobilerun
pip install -e .

# Start the control center (runs backend + UI)
mobilerun serve
```

This will:
- ✅ Start the backend server on your PC
- ✅ Serve the web UI locally at http://localhost:8000
- ✅ Auto-open the UI in your browser

**Then install the APK and link with the same Cognito account:**

1. Scan the **APK download QR** on Devices / Settings (or grab it from [Releases](https://github.com/MacAndersonUche/mobilerun/releases)) — QR is **download-only**, never for pairing
2. Open MobileRun → pair → **Enable Accessibility** (only manual step; Android 13+ may need *Allow restricted settings*). Notifications and battery unrestricted are requested automatically. Live-view MediaProjection is optional and only prompted when you open Live View.
3. Tap **Sign in & link phone** → enter the code on the hosted **Account** page while signed in
4. Hosted UI = management (dashboard, live view, chat, modes, Needs you). APK = wireless executor.

**Now you're ready!**

- Type tasks in the web UI: `"open WhatsApp"`, `"search for pizza near me"`
- Or use the CLI: `mobilerun run "your task here"`
- Watch live step logs, LLM reasoning, and phone screen in the UI
- The agent runs on your PC, actions execute on your phone

## 📋 Table of Contents

- [How It Works](#-how-it-works)
- [Installation](#-installation)
- [Usage](#-usage)
  - [Web UI](#web-ui)
  - [CLI Commands](#cli-commands)
- [Configuration](#-configuration)
- [Android App](#-android-app)
- [Cloud Deployment](#-cloud-deployment-optional)
- [Architecture](#-architecture)
- [Troubleshooting](#-troubleshooting)

## 🎯 How It Works

```
┌─────────────┐          ┌──────────────┐          ┌─────────────┐
│   Your PC   │   WiFi   │ Android App  │  A11y    │   Phone     │
│             │◄────────►│              │─────────►│   Screen    │
│  Backend    │          │  WebSocket   │          │             │
│  + Agent    │          │  Client      │          │  Actions    │
│  + Web UI   │          │              │          │  Execute    │
└─────────────┘          └──────────────┘          └─────────────┘
       ▲
       │
   Browser
   (localhost:8000)
```

**Key Flow:**

1. You run `mobilerun serve` on your PC (advertises `_mobilerun._tcp` via mDNS) **or** use the hosted Netlify UI + AWS API
2. Install APK via **download QR** (GitHub release). Sign in once (Cognito) on UI + APK — **same account links the phone** (device-code on Account)
3. APK completes permissions onboarding and keeps a foreground WebSocket (LAN mDNS preferred, else AWS)
4. Hosted UI manages agents; APK executes actions wirelessly
5. You type a task in the UI or CLI
6. Agent loop runs on PC or cloud (your API keys & compute)
7. Commands sent to phone via WebSocket; UI shows **active route + latency + permission status**
8. Accessibility Service executes taps, swipes, etc.
9. Live view frames stream back while the UI is subscribed

### Cognito setup (hosted)

```bash
# Backend / Lambda
COGNITO_USER_POOL_ID=eu-west-2_xxx
COGNITO_APP_CLIENT_ID=xxx
COGNITO_REGION=eu-west-2
ALLOWED_USER_EMAILS=macandersonuche@yahoo.com

# Netlify (frontend)
VITE_COGNITO_DOMAIN=xxx.auth.eu-west-2.amazoncognito.com
VITE_COGNITO_CLIENT_ID=xxx
# redirect: https://<site>/auth/callback  (SPA redirect already in netlify.toml)
```

See [SECURITY.md](./SECURITY.md) for JWT validation, device ownership, and the device-code flow.

## 🔧 Installation

### Prerequisites

- **PC:** Python 3.10+, pip
- **Phone:** Android 7.0+ with WiFi
- **LLM API Key:** OpenAI, Anthropic Claude, Google Gemini, or xAI Grok (`XAI_API_KEY`)

### Install Mobilerun

```bash
# Clone the repo
git clone https://github.com/MacAndersonUche/mobilerun.git
cd mobilerun

# Install with dev dependencies
pip install -e ".[dev]"

# (Optional) Install specific LLM providers
pip install -e ".[anthropic]"  # For Claude
pip install -e ".[gemini]"     # For Gemini
# xAI Grok uses the OpenAI-compatible client already bundled (https://api.x.ai/v1)
```

### Configure LLM Provider

```bash
# Option 1: Environment variable (pick one or more)
export OPENAI_API_KEY="sk-..."
export ANTHROPIC_API_KEY="sk-ant-..."
export GOOGLE_API_KEY="..."
export XAI_API_KEY="xai-..."          # Grok at https://api.x.ai/v1
export LLM_PROVIDER=xai               # gemini | openai | anthropic | xai
export LLM_MODEL=grok-4.7             # optional; defaults to current xAI docs id

# Option 2: Configuration wizard / CLI
mobilerun configure
mobilerun configure xai               # OAuth path (optional)

# Option 3: Set in backend/.env file
echo "XAI_API_KEY=xai-..." >> backend/.env
```

### Install Android App

1. Download the latest APK from [Releases](https://github.com/MacAndersonUche/mobilerun/releases)
2. Install on your phone (Settings → Security → Install unknown apps)
3. Open the app
4. Enable Accessibility Service:
   - Settings → Accessibility → Mobilerun → Enable
   - Grant all permissions
5. Return to the Mobilerun app

## 💻 Usage

### Primary Method: `mobilerun serve`

Start everything with one command:

```bash
mobilerun serve

# Options:
#   --host 0.0.0.0              # Bind to all interfaces
#   --port 8000                 # Custom port
#   --no-browser                # Don't auto-open browser
#   --allow-unauthenticated     # Disable JWT auth (local use)
```

**What you'll see:**

```
══════════════════════════════════════════════════════════════════════
🚀 Mobilerun Control Center Starting...
══════════════════════════════════════════════════════════════════════

📱 Backend API: http://localhost:8000
🌐 Web UI: http://localhost:8000/
✓ Frontend served from: /path/to/frontend/dist

──────────────────────────────────────────────────────────────────────
📲 PAIR YOUR ANDROID DEVICE:
──────────────────────────────────────────────────────────────────────

1. Install the Mobilerun app on your phone
2. Enable Accessibility Service in Settings
3. Return to app and scan this QR code:

[ASCII QR CODE HERE]

──────────────────────────────────────────────────────────────────────
💡 Quick Start:
──────────────────────────────────────────────────────────────────────
  • Open http://localhost:8000 in your browser
  • Pair your phone using the QR code above
  • Type tasks in the UI (e.g., 'open WhatsApp')
  • Or use CLI: mobilerun run 'your task here'

══════════════════════════════════════════════════════════════════════

✓ Opened http://localhost:8000 in your browser
```

### Web UI

The UI opens automatically at `http://localhost:8000`

**Devices Page:**
- See connected phones
- Connection status (WiFi)
- Pair new devices (QR code)

**Live View:**
- Phone-frame panel streaming the device screen (MediaProjection → JPEG over WebSocket, ~2–5 fps)
- Current app / step / action, tap·swipe overlays, live log, pause/stop
- Optional click/swipe on the view to send manual taps
- Streams **only while the UI is subscribed** (no frame storage; AWS relays via WebSocket API)

**AI Chat:**
- Chat with the configured LLM (Gemini / Claude / OpenAI / Grok)
- Toggle **My PC** vs **Hosted server** execution target
- Turns messages into tasks, dating start/stop, device info / message counts
- Confirms before destructive or bulk-send actions
- History in local SQLite (`~/.mobilerun/chat.db`) or DynamoDB `HISTORY_TABLE` on AWS

**Tasks Page:**
- Type natural language instructions
- Select device & LLM model
- Enable reasoning/vision modes

**History Page:**
- Past task results
- Success/failure status
- Full execution logs

**Settings Page:**
- Backend URL configuration
- LLM provider selection (incl. xAI Grok)
- API key management

### CLI Commands

Run tasks from the terminal:

```bash
# Basic usage
mobilerun run "open WhatsApp"

# With options
mobilerun run "search for coffee shops" --reasoning --max-steps 20

# Specific device
mobilerun run "take a screenshot" --device-id phone-abc123

# Custom backend
mobilerun run "your task" --backend http://192.168.1.100:8000
```

**What happens:**
- Task submitted to backend
- Executes via the agent on your PC
- Shows in UI history
- CLI polls and displays result

## ⚙️ Configuration

### LLM Providers

**Supported (self-hosted):** Google Gemini, OpenAI, Anthropic Claude, **xAI Grok**

Goal: replica of cloud.mobilerun.ai where you only pay **AWS + LLM tokens**.

| Provider | Env var | Default model (configurable) | Notes |
|----------|---------|------------------------------|-------|
| Gemini | `GOOGLE_API_KEY` / `GEMINI_API_KEY` | `gemini-3.8-flash` | |
| OpenAI | `OPENAI_API_KEY` | `gpt-6-astra` | |
| Anthropic | `ANTHROPIC_API_KEY` | `claude-sonnet-5` | |
| xAI Grok | `XAI_API_KEY` | `grok-4.7` | OpenAI-compatible at `https://api.x.ai/v1` |

**Configuration:**

```bash
# Via environment
export OPENAI_API_KEY="sk-..."
export ANTHROPIC_API_KEY="sk-ant-..."
export GOOGLE_API_KEY="..."
export XAI_API_KEY="xai-..."
export LLM_PROVIDER=xai
export LLM_MODEL=grok-4.7   # or grok-4.6, etc.

# Or in backend/.env
XAI_API_KEY=xai-...
LLM_PROVIDER=xai
LLM_MODEL=grok-4.7
```

UI Settings → Provider picker includes **xAI (Grok)**. Lambda deploy accepts optional GitHub secret `XAI_API_KEY`.

### Backend Options

Create `backend/.env`:

```bash
# Server
HOST=0.0.0.0
PORT=8000

# Auth (optional)
JWT_SECRET=your-secret-here
ALLOW_UNAUTHENTICATED=true  # For local use

# LLM (gemini | openai | anthropic | xai)
OPENAI_API_KEY=sk-...
XAI_API_KEY=xai-...
LLM_PROVIDER=gemini
# LLM_MODEL=grok-4.7

# Pairing
PAIRING_TOKEN=auto-generated
```

### Frontend Configuration

The UI auto-detects `http://localhost:8000` when served locally.

For remote backends, edit Settings in the UI or set:

```javascript
// Stored in localStorage
localStorage.setItem('backendUrl', 'http://your-server:8000');
```

## 📱 Android App

### Features

- ✅ **WiFi / cloud WebSocket:** No USB cable needed in any mode
- ✅ **mDNS / NSD discovery:** Prefers laptop `_mobilerun._tcp` on LAN; falls back to AWS
- ✅ **Dual-endpoint QR:** One scan stores LAN + cloud; shows route + latency in-app
- ✅ **Accessibility Service:** Real gesture execution (tap, swipe, scroll)
- ✅ **UI Tree Capture:** Sends layout XML to agent
- ✅ **Always Connected:** Session token + exponential backoff reconnect
- ✅ **Social mode:** Everyday apps + signature footer + Needs-you escalation
- ✅ **Needs you:** Shared confirmation queue for Social + Dating (UI / APK / optional email)

### Setup

1. **Install APK** from [Releases](https://github.com/MacAndersonUche/mobilerun/releases)

2. **Enable Accessibility:**
   ```
   Settings → Accessibility → Mobilerun Self-Hosted → Enable
   ```
   Grant all permissions (overlay, accessibility, notifications)

3. **Pair Device:**
   - Open Mobilerun app
   - Tap "Pair to Backend"
   - Scan QR code from `mobilerun serve` terminal

4. **Verify Connection:**
   - App shows "Connected" status
   - Backend UI shows device in Devices page

### Permissions Required

- **Accessibility Service:** Execute taps, swipes, get UI tree
- **Display Over Other Apps:** Screen capture (future)
- **Internet:** WebSocket connection to PC

### Building from Source

```bash
cd android-app
./gradlew assembleRelease

# APK at: build/outputs/apk/release/app-release.apk
```

## ☁️ Cloud Deployment (Optional)

> **Note:** The primary workflow is local PC (`mobilerun serve`). Cloud deployment is optional for remote access or shared deployments.

### Why Deploy to AWS?

- **Remote Access:** Control your phone from anywhere
- **Shared Backend:** Team can share one deployment
- **Persistent Storage:** DynamoDB + S3 for run history
- **Always-On:** No need to keep PC running

### Architecture Options

**Option 1: EC2 Backend (Recommended)**
- ✅ Free tier eligible (t3.micro, 750 hrs/month for 12 months)
- ✅ No timeout limits (unlike Lambda's 15 minutes)
- ✅ Full WebSocket support for live phone connections
- ✅ Runs FastAPI backend as systemd service
- ⚠️ Costs after free tier: ~$8/month for t3.micro

**Option 2: Lambda Backend**
- ✅ Serverless (pay per use)
- ✅ Auto-scaling
- ⚠️ 15-minute timeout (not ideal for long tasks)
- ⚠️ Cold starts
- 💰 Cost: Free tier 1M requests/month, then $0.20 per 1M

### Prerequisites

1. **AWS Account** (sign up at aws.amazon.com)
2. **AWS CLI** installed and configured
3. **Node.js 20+** (for CDK)
4. **GitHub Secrets** (for CI/CD):
   - `AWS_ACCESS_KEY_ID`
   - `AWS_SECRET_ACCESS_KEY`
   - Optional: `JWT_SECRET`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY` / `GOOGLE_API_KEY`, `XAI_API_KEY`

### Deploy Manually

```bash
# Install CDK dependencies
cd infra
npm install

# Bootstrap CDK (first time only)
npx cdk bootstrap

# Option 1: Deploy with EC2 backend (recommended)
npx cdk deploy -c backendMode=ec2 -c enableStorage=true

# Option 2: Deploy with Lambda backend
npx cdk deploy -c backendMode=lambda -c enableStorage=true

# Set environment variables
export JWT_SECRET="your-secret"
export OPENAI_API_KEY="sk-..."
```

**What gets deployed:**

- **EC2 Instance** (t3.micro, eu-west-2)
  - Amazon Linux 2023
  - FastAPI backend running on port 8000
  - Systemd service for auto-restart
  - Systems Manager access (no SSH needed)
  
- **DynamoDB Tables** (pay-per-request)
  - `mobilerun-history`: Task run history
  - `mobilerun-settings`: User settings & device metadata
  
- **S3 Bucket**
  - `mobilerun-screenshots-{account}-{region}`
  - Screenshots and trajectories
  - Lifecycle: Glacier after 30 days, delete after 90 days
  
- **Security Group**
  - Port 443 (HTTPS)
  - Port 8000 (HTTP/WebSocket)
  
- **Elastic IP**
  - Static IP for backend
  - No DNS changes when redeployed

### Deploy via GitHub Actions

Push to `main` branch with secrets configured:

```bash
git push origin main
```

The workflow:
1. Checks if `AWS_ACCESS_KEY_ID` secret exists
2. Skips cleanly if not configured
3. Deploys to eu-west-2 with EC2 backend
4. Outputs backend URL in summary

### Configure Your App

After deployment:

1. **Get Backend URL:**
   ```bash
   # From CDK output
   npx cdk deploy --outputs-file outputs.json
   cat outputs.json | grep BackendUrl
   
   # Or check GitHub Actions summary
   ```

2. **Update Frontend:**
   - Open Settings page in UI
   - Set Backend URL to EC2 public IP: `http://YOUR-IP:8000`
   - (Or configure domain + HTTPS with Caddy)

3. **Update Android App:**
   - Scan new QR code from `mobilerun serve` on EC2
   - Or manually enter backend URL

### Cost Breakdown

**Free Tier (12 months):**
- EC2 t3.micro: 750 hours/month ✅
- DynamoDB: 25 GB storage, 25 WCU, 25 RCU ✅
- S3: 5 GB storage, 20,000 GET, 2,000 PUT ✅
- Data Transfer: 100 GB/month outbound ✅

**After Free Tier (Monthly):**
- EC2 t3.micro: ~$8 (if running 24/7)
- DynamoDB: $0 for light use (pay-per-request)
- S3: $0.023/GB + $0.0004/1000 GET
- Elastic IP: $0 (while attached)

**Total Est. Cost:** $8-12/month after free tier

**Cost Optimization Tips:**
1. Stop EC2 when not in use: `aws ec2 stop-instances --instance-ids i-xxx`
2. Use S3 lifecycle (already configured)
3. Set DynamoDB TTL for old data
4. Use local PC for development

### Optional: Domain & HTTPS

**Option 1: Use Elastic IP directly**
```bash
http://YOUR-IP:8000
```

**Option 2: Add domain with Caddy (on EC2)**
```bash
# SSH to EC2 via Systems Manager
aws ssm start-session --target i-YOUR-INSTANCE-ID

# Install Caddy
sudo yum install -y caddy

# Configure reverse proxy
sudo caddy reverse-proxy --from mobilerun.yourdomain.com --to localhost:8000
```

**Option 3: CloudFront + ACM**
- Add CloudFront distribution
- Use ACM certificate
- Point to EC2 origin

### Sync Local ↔ Cloud

The backend supports AWS storage when deployed to AWS. Your local PC backend can optionally sync:

```bash
# Enable cloud storage in local backend
export USE_AWS_STORAGE=true
export AWS_REGION=eu-west-2
export HISTORY_TABLE=mobilerun-history
export SETTINGS_TABLE=mobilerun-settings
export SCREENSHOT_BUCKET=mobilerun-screenshots-xxx-eu-west-2

# Run local backend (will write to AWS)
mobilerun serve
```

This way, runs on your PC also save to AWS for backup/sharing.

### Netlify Frontend (Optional)

The frontend can also be served from Netlify:

- **Site:** macsmobilerun.netlify.app (if configured)
- **Base Directory:** `frontend`
- **Build Command:** `npm ci && npm run build`
- **Publish Directory:** `dist`

Point it at your EC2/Lambda backend via Settings page.

## 🏗️ Architecture

### Components

1. **Backend (FastAPI + Uvicorn)**
   - Serves web UI (static files)
   - WebSocket server for phone connections
   - Agent execution with mobilerun
   - Task queue & history
   - JWT auth (optional)

2. **Frontend (React + TypeScript + Vite)**
   - Devices page (pairing & status)
   - Tasks page (submit & monitor)
   - History page (past runs)
   - Settings page (config)
   - Built and served by backend

3. **Android App (Kotlin + Compose)**
   - WebSocket client
   - Accessibility Service
   - Command execution (tap, swipe, keys)
   - UI tree extraction
   - QR code scanner

4. **Agent (Mobilerun Core)**
   - LLM-powered ReAct loop
   - Vision support (screenshots)
   - Tool calling (Android actions)
   - State management
   - Trajectory tracking

### Data Flow

```
User Input (UI or CLI)
    ↓
Backend API (/api/tasks)
    ↓
Agent Loop (on PC)
    ├─► LLM Reasoning
    ├─► Tool Selection
    └─► Action Commands
         ↓
WebSocket to Phone
    ↓
Android Accessibility Service
    ├─► Execute Gesture
    ├─► Capture Screenshot
    └─► Extract UI Tree
         ↓
WebSocket to PC
    ↓
Agent Loop (next step)
    ↓
UI Update (live logs)
```

## ⚡ Performance Optimizations

This fork includes performance optimization infrastructure:

- **Parallel State Fetching:** Screenshot and UI tree captured simultaneously
- **Smart Caching:** Reduces redundant screenshot/tree fetches with TTL-based cache
- **Profiling Infrastructure:** Built-in performance metrics for measuring agent loop latency
- **Streamlined LLM Calls:** Gemini / Claude / OpenAI / xAI Grok (no unused provider sprawl)

These optimizations are designed to reduce per-step latency. Benchmarking against baseline will be available after full integration testing.

## 🔐 Security

### Local Mode (Default)

- Backend runs on `localhost:8000`
- Not exposed to internet
- `ALLOW_UNAUTHENTICATED=true` for convenience
- Only devices on your LAN can connect

### Production Mode

If exposing backend publicly:

1. **Enable JWT Auth:**
   ```bash
   # backend/.env
   JWT_SECRET=your-long-random-secret
   ALLOW_UNAUTHENTICATED=false
   ```

2. **HTTPS:** Use reverse proxy (nginx/Caddy) with Let's Encrypt

3. **Firewall:** Restrict access to known IPs

4. **Pairing Tokens:** Rotate regularly

### APK Signing

- Debug keystore committed for personal use
- For public distribution, use proper signing key

## 🐛 Troubleshooting

### Phone Won't Connect

**Check:**
1. PC and phone on same WiFi network
2. Firewall allows port 8000
3. Backend URL correct in app (scan QR again)
4. Accessibility Service enabled

**Test:**
```bash
# From phone browser, visit:
http://your-pc-ip:8000/api/devices
```

### Accessibility Service Not Working

1. Disable and re-enable in Settings
2. Reboot phone
3. Check app has all permissions
4. Try reinstalling app

### Agent Tasks Fail

**Check:**
1. LLM API key valid (`echo $OPENAI_API_KEY`)
2. Internet connection on PC
3. Backend logs for errors
4. UI tree capture working (check logs)

**Debug:**
```bash
# Run with debug logging
mobilerun serve --log-level debug
```

### Frontend Not Loading

**Check:**
1. Frontend built:
   ```bash
   cd frontend && npm run build
   ```
2. Backend finds dist directory:
   ```bash
   export FRONTEND_DIR="/path/to/frontend/dist"
   mobilerun serve
   ```
3. Or use Netlify site + Settings page to configure backend URL

### CLI `mobilerun run` Fails

**Check:**
1. Backend running (`mobilerun serve` in another terminal)
2. Device connected (check UI Devices page)
3. Backend URL correct (`--backend http://localhost:8000`)

## 💕 Dating Mode

**Automated dating app workflow** targeting Mac's phone "MobileRun" folder apps:

**Supported Apps (default):**
- ✅ Taimi, Bumble, Yubo, Badoo, BLK, Hily, Hinge
- ⚙️ Facebook, Snapchat, Instagram (off by default)

**Features:**
- 📱 Swipe/like with per-app daily caps and rules
- 💬 **Sequential replies** — one conversation after another (never parallel), with human-like gaps (30–180s)
- ✉️ Opening messages to new matches: **50–100 per app/day** (randomized within range, configurable)
- 📈 Global auto-messaging cap: **100–500/day** across all apps (openers + replies, configurable)
- 📊 Per-app stats + **progress vs caps** in the Dating Mode UI dashboard
- 🤖 Human-like pacing: randomized delays, Bézier swipe curves with jitter, active hours, session breaks
- 🔄 Round-robin or single-app mode; start/stop/pause from UI or CLI
- Works for the MobileRun folder apps **and any other dating app added to the list**

**Usage:**

```bash
# From CLI
mobilerun dating --start         # Start dating automation
mobilerun dating --stop          # Stop
mobilerun dating --status        # Check status
mobilerun dating --stats         # View per-app statistics

# From UI → Dating Mode page:
# - Toggle apps, set global message min/max, persona prompt
# - Enable/disable review-before-send
# - Live progress bars: openers vs target, global messages vs cap
# - Review & approve/edit/reject queued messages one-by-one
```

**Configuration:**
- Editable persona/style prompt in UI
- Per-app opener target range (default 50–100; Bumble/Hinge customized)
- Global message range (default 100–500 openers+replies/day)
- Active hours (default: 9 AM – 11 PM)
- Session limits + conversation gaps for sequential sends
- Review mode: optional approval queue before sending

**Stats Tracked:**
- Daily/total swipes, openers, replies per app
- Progress vs opener target and global message cap
- Unread message count, new matches
- Session count, runtime minutes

**Safety:**
- Sequential messaging only (no parallel sends)
- Global swipe cap (300/day) + message range (100–500)
- Human-like timing: Bézier curves, jitter, variable delays
- Session breaks and active-hour enforcement
- Review queue prevents unintended sends
- JWT auth required on all dating API endpoints

---

## 📊 Current Status

**✅ Fully Implemented & Verified:**
- Backend API with WebSocket support
- Frontend UI (all pages functional)
- Android app with Accessibility Service
- WebSocket device driver
- CLI commands (`serve`, `run`, `dating`)
- QR code pairing flow
- CI/CD (APK build, tests, linting)
- Cross-platform scripts
- Netlify deployment config
- AWS CDK infrastructure
- Dating Mode engine, scheduler, stats, API & CLI

**⚠️ Requires Physical Device Testing:**
- End-to-end task execution on real phone
- Screenshot capture via MediaProjection API
- Full agent loop with wireless device
- Dating Mode live execution (app navigation, inbox reading, LLM replies)
- Performance benchmarking

**📝 Documentation:**
- Installation: Complete
- Usage: Complete
- Troubleshooting: Complete
- Architecture: Complete
- Dating Mode: Complete

## 🤝 Contributing

This is Mac's personal automation fork. For upstream contributions, see [droidrun/mobilerun](https://github.com/droidrun/mobilerun).

## 📜 License

MIT License (same as upstream mobilerun)

## 🙏 Acknowledgments

Built on [droidrun/mobilerun](https://github.com/droidrun/mobilerun) - excellent foundation for LLM-powered mobile automation.

---

**Need Help?**

1. Check [Troubleshooting](#-troubleshooting)
2. Review backend logs
3. Test with `mobilerun run "open settings"` (simple task)
4. Open an issue with logs attached

**Happy Automating! 🎉**
