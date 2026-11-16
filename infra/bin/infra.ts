#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib';
import { MobilerunStack } from '../lib/mobilerun-stack';

const app = new cdk.App();

new MobilerunStack(app, 'MobilerunStack', {
  env: {
    account: process.env.CDK_DEFAULT_ACCOUNT || process.env.CDK_DEPLOY_ACCOUNT,
    region: process.env.CDK_DEFAULT_REGION || process.env.CDK_DEPLOY_REGION || 'eu-west-2',
  },
  description: 'Mobilerun self-hosted backend (cost-optimized Lambda + DynamoDB + S3)',
  budgetAlertEmail: process.env.BUDGET_EMAIL || 'macandersonuche@yahoo.com',
});

app.synth();
