# UI reference captures (public sources)

Playwright captures used to align MobileRun by MacAI with the public Mobilerun look **without logging into the cloud dashboard**.

## Sources

| File prefix | Source |
|-------------|--------|
| `desktop/mobile-01-mobilerun-ai-*` | https://mobilerun.ai |
| `desktop/mobile-02-cloud-mobilerun*` | https://cloud.mobilerun.ai (login / landing) |
| `desktop-docs-*` | https://docs.mobilerun.ai (Mintlify docs) |
| `desktop/mobile-08-github-*` | https://github.com/droidrun/mobilerun |
| `asset-09`…`asset-21`, stream/phone assets | Docs examples (live phone stream, phone wall, drive-the-phone) |
| `asset-og-*` | Marketing OG image |

## Design notes extracted

- **Cloud login:** split layout — form column + dark graphic panel; stacked OAuth buttons; Inter-like sans.
- **Marketing site:** spacious SaaS layout, blue accent CTAs, phone-in-hero compositions.
- **Embed / live stream docs:** dark panel tokens (`#0e0e11` bg, `#212124` muted/border), device panel `aspect-ratio: 9 / 19.5`, `border-radius: 24px`.
- **Phone wall examples:** labeled device frames in a grid with Android soft-keys under the screen.

Our product UI keeps **MobileRun by MacAI** naming/logo (no copied brand marks) and a blue accent instead of third-party orange.

## Re-capture

```bash
cd frontend && node scripts/capture-ui-reference.mjs
```
