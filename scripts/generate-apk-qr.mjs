#!/usr/bin/env node
/**
 * Generate QR code for APK download URL
 */

import QRCode from 'qrcode';

const repo = process.env.GITHUB_REPOSITORY;
const runNumber = process.env.GITHUB_RUN_NUMBER;
const tag = `apk-${runNumber}`;
const url = `https://github.com/${repo}/releases/download/${tag}/mobilerun.apk`;

console.log(`Generating QR code for: ${url}`);

await QRCode.toFile('apk-download-qr.png', url, {
  type: 'png',
  width: 512,
  margin: 2,
  errorCorrectionLevel: 'M',
  color: {
    dark: '#000000',
    light: '#FFFFFF'
  }
});

console.log('✓ QR code generated: apk-download-qr.png');
