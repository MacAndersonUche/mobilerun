#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib';
import { MobilerunStack } from '../lib/mobilerun-stack';

const app = new cdk.App();

new MobilerunStack(app, 'MobilerunStack', {
  env: {
    account: process.env.CDK_DEFAULT_ACCOUNT,
    region: 'eu-west-2',
  },
  description: 'Mobilerun self-hosted backend infrastructure',
});

app.synth();
