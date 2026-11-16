# UI reference

## Mac phone recording (primary)

Mac recorded **cloud.mobilerun.ai** on his phone (frames every ~2s). Those frames are the design source of truth for the hosted UI rebuild (dark mode, Home / Agent chat / Settings sheet / Account sheet).

**Status:** Binary frames were not present in this agent run’s attachments. Design was rebuilt from the written screen spec in the task. When frames are available, drop them here as:

```
docs/ui-reference/mac-phone/frame-000.png
docs/ui-reference/mac-phone/frame-002.png
…
```

See `MAC-PHONE-SPEC.md` for the extracted layout contract used for the rebuild.

## Public captures (secondary)

Earlier Playwright captures of public surfaces (no cloud dashboard login):

| File prefix | Source |
|-------------|--------|
| `desktop/mobile-01-mobilerun-ai-*` | https://mobilerun.ai |
| `desktop/mobile-02-cloud-mobilerun*` | https://cloud.mobilerun.ai (login / landing) |
| `desktop-docs-*` | https://docs.mobilerun.ai |
| `desktop/mobile-08-github-*` | https://github.com/droidrun/mobilerun |
| `asset-*` | Docs examples (live stream, phone wall) |

## Design tokens (hosted UI)

| Token | Value |
|-------|-------|
| Background | `#0A0A0A` / `#121212` |
| Cards | `#1C1C1E` / `#27272A` |
| Borders | `#3F3F46` |
| Accent | `#3B82F6` |
| Success | text `#4ADE80` on `#14532D` |
| Muted text | `#A1A1AA` |
| Font | Inter |

Product name / logo: **MobileRun by MacAI** (no third-party marks).

## Re-capture public sources

```bash
cd frontend && node scripts/capture-ui-reference.mjs
```
