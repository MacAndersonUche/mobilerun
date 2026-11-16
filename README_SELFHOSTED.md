# Mobilerun Self-Hosted Edition

> Transform your laptop into a complete mobile automation control center.

This is Mac's fork of [droidrun/mobilerun](https://github.com/droidrun/mobilerun), converted into a **fully self-hosted system** for running AI agents on Android devices without cloud dependencies.

## 🎯 What's Different

| Feature | Upstream mobilerun | This Fork (Self-Hosted) |
|---------|-------------------|------------------------|
| **Control UI** | CLI only | Modern web UI (React + TypeScript) |
| **Device Connection** | USB/ADB cable | **Wireless over WiFi** (no cable needed) |
| **Backend Options** | N/A | Local (laptop) OR AWS Lambda |
| **Frontend Deployment** | N/A | Netlify static site |
| **Performance** | Standard | **Optimized agent loop** with profiling |
| **LLM Providers** | All providers | **Gemini, Claude, OpenAI** (focused) |
| **Pairing** | Manual setup | **QR code pairing** from UI |
| **APK Distribution** | N/A | **Auto-build & QR code** via GitHub Actions |

## 🚀 Quick Start

### 1. Prerequisites

- **Python 3.11+** (for backend)
- **Node.js 20+** (for frontend - optional for local use)
- **Android device** with Developer options enabled
- **API key** for at least one LLM provider (Gemini, OpenAI, or Anthropic)

### 2. Clone & Install

```bash
git clone https://github.com/MacAndersonUche/mobilerun
cd mobilerun

# Install Python dependencies
pip install -e .
```

### 3. Install Android App

Scan the QR code below with your Android device to download the latest app:

<!-- LATEST_APK_START -->
*APK will be available after first GitHub Actions build*
<!-- LATEST_APK_END -->

Or download manually from [Releases](https://github.com/MacAndersonUche/mobilerun/releases/latest).

**Installation:**
1. Download APK on your phone
2. Enable "Install from unknown sources" if prompted
3. Tap "More details" then "Install anyway" if Play Protect warns you (normal for sideloaded apps)

### 4. Start the Backend

#### Option A: Local on Your Laptop (Recommended for First Time)

**On macOS/Linux:**
```bash
./start.sh
```

**On Windows:**
```powershell
start.bat
```

The backend starts at `http://localhost:8000`.

On first run, edit `backend/.env` to add your API keys:

```env
# Add at least one
GOOGLE_API_KEY=your_gemini_key_here
OPENAI_API_KEY=your_openai_key_here
ANTHROPIC_API_KEY=your_anthropic_key_here
```

#### Option B: AWS Lambda (Cloud Deployment)

See [Deployment Guide](#cloud-deployment) below.

### 5. Open the Control UI

**Local Development:**
```bash
cd frontend
npm install
npm run dev
```

Visit `http://localhost:3000`.

**Production:** The UI is deployed to Netlify at `https://mobilerun-control.netlify.app` (or your custom domain).

### 6. Pair Your Device

1. Open the Control UI
2. Click "Pair Device"
3. Enter a device name
4. Scan the QR code with the Mobilerun app on your phone
5. Enable the Accessibility Service when prompted

### 7. Run Your First Task

1. Go to "Run Task" in the UI
2. Select your paired device
3. Enter an instruction like: `"Open Settings and turn on dark mode"`
4. Click "Run Task"
5. Watch the live execution on your phone!

## 📐 Architecture

```
┌─────────────────┐         ┌──────────────────┐         ┌─────────────────┐
│   Frontend      │         │   Backend        │         │  Android App    │
│   (Netlify)     │────────▶│   (Laptop or     │◀────────│  (Your Phone)   │
│                 │  HTTPS  │    AWS Lambda)   │  WSS    │                 │
│  React + TS     │         │  FastAPI+Python  │         │  Kotlin+Compose │
└─────────────────┘         └──────────────────┘         └─────────────────┘
                                      │
                                      │ Uses
                                      ▼
                            ┌──────────────────┐
                            │  mobilerun Core  │
                            │  Python Package  │
                            │  (this repo)     │
                            └──────────────────┘
```

**Key Design Decisions:**

1. **Phone → Backend Connection:** The Android app connects OUTBOUND to the backend via WebSocket, so it works whether the backend is on your laptop (localhost) or in the cloud (Lambda).

2. **Backend URL Configuration:** The frontend stores the backend URL in `localStorage`, configurable in Settings. Default from `VITE_BACKEND_URL` env var.

3. **Auth:** Simple JWT tokens. Local mode can run with `ALLOW_UNAUTHENTICATED=true` for convenience. Cloud mode should use proper JWT secrets.

4. **WebSocket Limitations on Lambda:** Long-running agent loops may exceed Lambda's 15-minute timeout. Current implementation uses step-per-invocation pattern. For production, consider running backend on ECS Fargate or EC2.

## 🌐 Cloud Deployment

### Frontend (Netlify)

1. Fork this repo
2. Connect to Netlify:
   - New site from Git → Select your fork
   - Build command: `cd frontend && npm install && npm run build`
   - Publish directory: `frontend/dist`
   - Environment variables:
     ```
     VITE_BACKEND_URL=https://your-api-url.execute-api.eu-west-2.amazonaws.com/prod
     ```

### Backend (AWS Lambda via CDK)

1. Set GitHub repository secrets:
   ```
   AWS_ACCESS_KEY_ID
   AWS_SECRET_ACCESS_KEY
   JWT_SECRET
   OPENAI_API_KEY (optional)
   ANTHROPIC_API_KEY (optional)
   GOOGLE_API_KEY (optional)
   ```

2. Push to `main` branch - GitHub Actions will deploy automatically

3. Get the API URL from the Actions output and update your Netlify env var

**Note:** If AWS secrets aren't set, the deploy workflow skips cleanly (CI stays green).

## ⚡ Performance Optimizations

This fork includes performance optimization infrastructure:

- **Parallel State Fetching:** Screenshot and UI tree captured simultaneously
- **Smart Caching:** Reduces redundant screenshot/tree fetches with TTL-based cache
- **Profiling Infrastructure:** Built-in performance metrics for measuring agent loop latency
- **Streamlined LLM Calls:** Only Gemini/Claude/OpenAI supported, reducing overhead

These optimizations are designed to reduce per-step latency. Benchmarking against baseline will be available after full integration testing.

## 🛠️ Development

### Run Tests

```bash
# Python tests
pytest

# Frontend tests
cd frontend
npm test
```

### Build APK Locally

```bash
cd android-app
./gradlew assembleRelease
```

APK will be in `android-app/build/outputs/apk/release/`.

### Local Frontend Development

```bash
cd frontend
npm run dev
```

Configure backend URL in Settings UI or set `VITE_BACKEND_URL` env var.

## 📝 Project Structure

```
mobilerun/
├── frontend/              # React + TypeScript control UI
│   ├── src/
│   │   ├── pages/         # Devices, Tasks, History, Settings
│   │   └── config.ts      # Runtime backend URL config
│   ├── netlify.toml       # Netlify deployment config
│   └── package.json
├── backend/               # FastAPI Python backend
│   ├── main.py            # HTTP & WebSocket endpoints
│   ├── auth.py            # JWT authentication
│   ├── Dockerfile.lambda  # Lambda container image
│   └── requirements.txt
├── infra/                 # AWS CDK infrastructure (TypeScript)
│   ├── lib/mobilerun-stack.ts
│   └── bin/infra.ts
├── android-app/           # Android client app (Kotlin)
│   ├── build.gradle.kts
│   ├── src/main/
│   │   ├── AndroidManifest.xml
│   │   └── java/ai/mobilerun/selfhosted/
│   │       ├── MainActivity.kt
│   │       └── BackendClient.kt
│   └── debug.keystore     # Committed for consistent signing
├── scripts/               # Build automation scripts
│   ├── generate-apk-qr.mjs
│   └── update-readme-apk.mjs
├── .github/workflows/
│   ├── android-build.yml  # APK build & release
│   └── deploy.yml         # AWS backend deployment
├── start.sh / start.bat   # Cross-platform startup scripts
└── mobilerun/             # Core Python package (upstream)
    ├── agent/
    ├── profiling/         # NEW: Performance profiling
    └── ...
```

## 🔒 Security Notes

- **Local Mode:** Uses `ALLOW_UNAUTHENTICATED=true` for convenience. Not exposed to internet.
- **Cloud Mode:** MUST set a strong `JWT_SECRET`. Consider additional auth (OAuth, etc.).
- **APK Signing:** Uses committed debug keystore for consistent updates. **Never use this pattern for production apps with sensitive data** - this is for personal automation only.
- **API Keys:** Never commit API keys. Use environment variables or secrets.

## 🤝 Contributing

This is Mac's personal fork optimized for self-hosted use. For general mobilerun improvements, contribute to [droidrun/mobilerun](https://github.com/droidrun/mobilerun).

For issues specific to this self-hosted setup, open an issue here.

## 📄 License

MIT (same as upstream mobilerun)

## 🙏 Credits

- **Upstream:** [droidrun/mobilerun](https://github.com/droidrun/mobilerun) - The amazing foundation this is built on
- **Mac:** Self-hosted architecture, performance optimizations, and control UI
- **Pattern inspiration:** Auto-Fab and Auto-Food-Ordering repos for deployment workflow

---

**Status:** ✅ Functional | 🚧 Active Development

**Last Updated:** November 2026
