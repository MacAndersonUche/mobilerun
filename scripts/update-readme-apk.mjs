#!/usr/bin/env node
/**
 * Update README.md with latest APK download links and QR code
 */

import { readFileSync, writeFileSync } from 'fs';

const repo = process.env.GITHUB_REPOSITORY;
const runNumber = process.env.GITHUB_RUN_NUMBER;
const sha = process.env.GITHUB_SHA;
const runId = process.env.GITHUB_RUN_ID;
const tag = `apk-${runNumber}`;
const version = `1.0.${runNumber}`;

const apkSection = `<!-- LATEST_APK_START -->
## 📱 Install Latest Android App

**Version:** ${version} | **Build:** [#${runNumber}](https://github.com/${repo}/actions/runs/${runId}) | **Commit:** [\`${sha.substring(0, 7)}\`](https://github.com/${repo}/commit/${sha})

[![Release](https://img.shields.io/badge/download-mobilerun.apk-blue?style=for-the-badge&logo=android)](https://github.com/${repo}/releases/latest/download/mobilerun.apk)

### Quick Install - Scan QR Code

<p align="center">
  <img src="https://github.com/${repo}/releases/latest/download/apk-download-qr.png" alt="Download APK QR Code" width="300"/>
</p>

<p align="center">
  <em>Scan with your Android device to download and install</em>
</p>

### Manual Download

| Method | Link |
|--------|------|
| **Latest APK** | [mobilerun.apk](https://github.com/${repo}/releases/latest/download/mobilerun.apk) |
| **All Releases** | [View all releases](https://github.com/${repo}/releases) |
| **This Build** | [Release ${tag}](https://github.com/${repo}/releases/tag/${tag}) |

### Installation Notes

1. Download the APK on your Android device (or scan the QR code above)
2. Open the downloaded file to install
3. If prompted, enable "Install from unknown sources" in Settings
4. **Play Protect Warning:** If you see a warning, tap "More details" then "Install anyway"
   - This is normal for apps outside the Play Store
5. New builds will update in place (same signing key used for all builds)

### After Installation

Open the Mobilerun app and scan the pairing QR code from the control UI to connect your device.
<!-- LATEST_APK_END -->`;

let readme = readFileSync('README.md', 'utf8');

const startMarker = '<!-- LATEST_APK_START -->';
const endMarker = '<!-- LATEST_APK_END -->';

const startIndex = readme.indexOf(startMarker);
const endIndex = readme.indexOf(endMarker);

if (startIndex !== -1 && endIndex !== -1) {
  // Replace existing section
  readme = readme.substring(0, startIndex) + apkSection + readme.substring(endIndex + endMarker.length);
  console.log('✓ Updated existing APK section in README.md');
} else {
  // Append to end
  readme += '\n\n' + apkSection + '\n';
  console.log('✓ Added new APK section to README.md');
}

writeFileSync('README.md', readme, 'utf8');
console.log(`✓ README.md updated with build ${runNumber}`);
