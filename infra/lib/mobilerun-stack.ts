import * as cdk from 'aws-cdk-lib';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as apigwv2 from 'aws-cdk-lib/aws-apigatewayv2';
import * as apigwIntegrations from 'aws-cdk-lib/aws-apigatewayv2-integrations';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as budgets from 'aws-cdk-lib/aws-budgets';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as events from 'aws-cdk-lib/aws-events';
import * as targets from 'aws-cdk-lib/aws-events-targets';
import * as iam from 'aws-cdk-lib/aws-iam';
import { Construct } from 'constructs';
import * as path from 'path';

export interface MobilerunStackProps extends cdk.StackProps {
  /**
   * Enable EC2 backend (OFF by default — costs ~$8/month after free tier).
   */
  enableEC2?: boolean;
  budgetAlertEmail?: string;
}

/**
 * Near-zero-cost Mobilerun cloud backend:
 * - Lambda (HTTP + WebSocket + step worker)
 * - HTTP API + WebSocket API (API Gateway v2)
 * - DynamoDB on-demand + S3 (7-day lifecycle)
 * - EventBridge rate rule for step-driven dating/agent loops
 * - $5/month budget alert
 * - No NAT, ALB, RDS, provisioned concurrency, or EC2 by default
 */
export class MobilerunStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: MobilerunStackProps) {
    super(scope, id, props);

    const enableEC2 =
      props?.enableEC2 ?? this.node.tryGetContext('enableEC2') ?? false;
    const budgetEmail =
      props?.budgetAlertEmail ||
      this.node.tryGetContext('budgetEmail') ||
      'macandersonuche@yahoo.com';

    // === Storage (pay-per-request) ===

    const historyTable = new dynamodb.Table(this, 'RunHistory', {
      partitionKey: { name: 'task_id', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'timestamp', type: dynamodb.AttributeType.NUMBER },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      tableName: 'mobilerun-history',
      timeToLiveAttribute: 'ttl',
    });

    historyTable.addGlobalSecondaryIndex({
      indexName: 'device-index',
      partitionKey: { name: 'device_id', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'timestamp', type: dynamodb.AttributeType.NUMBER },
    });

    const settingsTable = new dynamodb.Table(this, 'Settings', {
      partitionKey: { name: 'key', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      tableName: 'mobilerun-settings',
    });

    // WebSocket connection registry (device_id ↔ connectionId)
    const connectionsTable = new dynamodb.Table(this, 'Connections', {
      partitionKey: { name: 'connection_id', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      tableName: 'mobilerun-connections',
      timeToLiveAttribute: 'ttl',
    });
    connectionsTable.addGlobalSecondaryIndex({
      indexName: 'device-index',
      partitionKey: { name: 'device_id', type: dynamodb.AttributeType.STRING },
    });

    // Step-driven job state (dating / agent loops)
    const jobsTable = new dynamodb.Table(this, 'Jobs', {
      partitionKey: { name: 'job_id', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      tableName: 'mobilerun-jobs',
      timeToLiveAttribute: 'ttl',
    });
    jobsTable.addGlobalSecondaryIndex({
      indexName: 'status-index',
      partitionKey: { name: 'status', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'next_run_at', type: dynamodb.AttributeType.NUMBER },
    });

    const screenshotBucket = new s3.Bucket(this, 'Screenshots', {
      bucketName: `mobilerun-screenshots-${this.account}-${this.region}`,
      versioned: false,
      publicReadAccess: false,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryption: s3.BucketEncryption.S3_MANAGED,
      lifecycleRules: [
        {
          id: 'expire-screenshots',
          enabled: true,
          expiration: cdk.Duration.days(7),
        },
        {
          id: 'abort-incomplete-uploads',
          enabled: true,
          abortIncompleteMultipartUploadAfter: cdk.Duration.days(1),
        },
      ],
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
    });

    if (!enableEC2) {
      this.deployLambdaBackend(
        historyTable,
        screenshotBucket,
        settingsTable,
        connectionsTable,
        jobsTable
      );
    } else {
      new cdk.CfnOutput(this, 'EC2Disabled', {
        value:
          'EC2 backend is OFF by default. To enable: cdk deploy -c enableEC2=true',
      });
    }

    // === $5 budget alert ===
    new budgets.CfnBudget(this, 'MonthlyBudget', {
      budget: {
        budgetName: 'mobilerun-monthly-budget',
        budgetType: 'COST',
        timeUnit: 'MONTHLY',
        budgetLimit: { amount: 5, unit: 'USD' },
      },
      notificationsWithSubscribers: [
        {
          notification: {
            notificationType: 'ACTUAL',
            comparisonOperator: 'GREATER_THAN',
            threshold: 80,
            thresholdType: 'PERCENTAGE',
          },
          subscribers: [
            { subscriptionType: 'EMAIL', address: budgetEmail },
          ],
        },
        {
          notification: {
            notificationType: 'ACTUAL',
            comparisonOperator: 'GREATER_THAN',
            threshold: 100,
            thresholdType: 'PERCENTAGE',
          },
          subscribers: [
            { subscriptionType: 'EMAIL', address: budgetEmail },
          ],
        },
      ],
    });

    new cdk.CfnOutput(this, 'HistoryTable', {
      value: historyTable.tableName,
    });
    new cdk.CfnOutput(this, 'SettingsTable', {
      value: settingsTable.tableName,
    });
    new cdk.CfnOutput(this, 'ConnectionsTable', {
      value: connectionsTable.tableName,
    });
    new cdk.CfnOutput(this, 'JobsTable', {
      value: jobsTable.tableName,
    });
    new cdk.CfnOutput(this, 'ScreenshotBucket', {
      value: screenshotBucket.bucketName,
    });
    new cdk.CfnOutput(this, 'EstimatedCost', {
      value:
        'Free tier: ~$0/mo (Lambda 1M req, DynamoDB 25GB, S3 5GB, HTTP API 1M). Light use after free tier: typically <$1/mo. Budget alert at $5.',
    });
    new cdk.CfnOutput(this, 'BudgetAlert', {
      value: `Budget alert set at $5/month to ${budgetEmail}`,
    });
  }

  private lambdaCode(): lambda.Code {
    // Prefer CI-prebuilt asset dir (binary wheels; avoids Pillow jpeg compile in Docker)
    const prebuilt = process.env.LAMBDA_ASSET_DIR;
    if (prebuilt) {
      return lambda.Code.fromAsset(prebuilt);
    }
    const assetPath = path.join(__dirname, '../../backend');
    if (process.env.SKIP_BUNDLING === '1') {
      return lambda.Code.fromAsset(assetPath);
    }
    return lambda.Code.fromAsset(assetPath, {
      bundling: {
        image: lambda.Runtime.PYTHON_3_11.bundlingImage,
        command: [
          'bash',
          '-c',
          [
            'dnf install -y gcc libjpeg-turbo-devel zlib-devel || yum install -y gcc libjpeg-devel zlib-devel || true',
            'pip install -r requirements.txt -t /asset-output',
            'cp -au . /asset-output',
          ].join(' && '),
        ],
      },
    });
  }

  private deployLambdaBackend(
    historyTable: dynamodb.Table,
    screenshotBucket: s3.Bucket,
    settingsTable: dynamodb.Table,
    connectionsTable: dynamodb.Table,
    jobsTable: dynamodb.Table
  ) {
    const envVars: { [key: string]: string } = {
      JWT_SECRET: process.env.JWT_SECRET || 'change-me-in-production',
      OPENAI_API_KEY: process.env.OPENAI_API_KEY || '',
      ANTHROPIC_API_KEY: process.env.ANTHROPIC_API_KEY || '',
      GOOGLE_API_KEY: process.env.GOOGLE_API_KEY || '',
      GEMINI_API_KEY: process.env.GEMINI_API_KEY || '',
      ALLOW_UNAUTHENTICATED: 'false',
      HISTORY_TABLE: historyTable.tableName,
      SETTINGS_TABLE: settingsTable.tableName,
      CONNECTIONS_TABLE: connectionsTable.tableName,
      JOBS_TABLE: jobsTable.tableName,
      SCREENSHOT_BUCKET: screenshotBucket.bucketName,
      USE_AWS_STORAGE: 'true',
      STEP_DRIVEN: 'true',
    };

    const code = this.lambdaCode();

    // HTTP Lambda (REST via HTTP API)
    const httpFn = new lambda.Function(this, 'HttpFunction', {
      runtime: lambda.Runtime.PYTHON_3_11,
      handler: 'main.handler',
      code,
      timeout: cdk.Duration.seconds(29), // HTTP API max ~30s
      memorySize: 512,
      environment: envVars,
      logRetention: logs.RetentionDays.ONE_WEEK,
    });

    // WebSocket Lambda ($connect / $disconnect / $default)
    const wsFn = new lambda.Function(this, 'WebSocketFunction', {
      runtime: lambda.Runtime.PYTHON_3_11,
      handler: 'ws_handler.handler',
      code,
      timeout: cdk.Duration.seconds(29),
      memorySize: 256,
      environment: envVars,
      logRetention: logs.RetentionDays.ONE_WEEK,
    });

    // Step worker — one dating/agent step per invocation (no 15-min long loop)
    const stepFn = new lambda.Function(this, 'StepWorkerFunction', {
      runtime: lambda.Runtime.PYTHON_3_11,
      handler: 'step_worker.handler',
      code,
      timeout: cdk.Duration.minutes(2),
      memorySize: 512,
      environment: envVars,
      logRetention: logs.RetentionDays.ONE_WEEK,
    });

    for (const fn of [httpFn, wsFn, stepFn]) {
      historyTable.grantReadWriteData(fn);
      settingsTable.grantReadWriteData(fn);
      connectionsTable.grantReadWriteData(fn);
      jobsTable.grantReadWriteData(fn);
      screenshotBucket.grantReadWrite(fn);
    }

    // Allow HTTP Lambda to invoke step worker / manage WS connections later
    stepFn.grantInvoke(httpFn);
    httpFn.addEnvironment('STEP_WORKER_ARN', stepFn.functionArn);

    // === HTTP API (cheaper than REST API Gateway) ===
    const httpApi = new apigwv2.HttpApi(this, 'HttpApi', {
      apiName: 'mobilerun-http',
      corsPreflight: {
        allowHeaders: ['Content-Type', 'Authorization', 'X-Api-Key'],
        allowMethods: [
          apigwv2.CorsHttpMethod.GET,
          apigwv2.CorsHttpMethod.POST,
          apigwv2.CorsHttpMethod.PUT,
          apigwv2.CorsHttpMethod.DELETE,
          apigwv2.CorsHttpMethod.OPTIONS,
        ],
        allowOrigins: ['*'],
        maxAge: cdk.Duration.days(1),
      },
    });

    const httpIntegration = new apigwIntegrations.HttpLambdaIntegration(
      'HttpIntegration',
      httpFn
    );
    httpApi.addRoutes({
      path: '/{proxy+}',
      methods: [apigwv2.HttpMethod.ANY],
      integration: httpIntegration,
    });
    httpApi.addRoutes({
      path: '/',
      methods: [apigwv2.HttpMethod.ANY],
      integration: httpIntegration,
    });

    // === WebSocket API (phone ↔ cloud; Lambda cannot hold sockets) ===
    const wsApi = new apigwv2.WebSocketApi(this, 'WebSocketApi', {
      apiName: 'mobilerun-ws',
      connectRouteOptions: {
        integration: new apigwIntegrations.WebSocketLambdaIntegration(
          'WsConnect',
          wsFn
        ),
      },
      disconnectRouteOptions: {
        integration: new apigwIntegrations.WebSocketLambdaIntegration(
          'WsDisconnect',
          wsFn
        ),
      },
      defaultRouteOptions: {
        integration: new apigwIntegrations.WebSocketLambdaIntegration(
          'WsDefault',
          wsFn
        ),
      },
    });

    const wsStage = new apigwv2.WebSocketStage(this, 'WebSocketStage', {
      webSocketApi: wsApi,
      stageName: 'prod',
      autoDeploy: true,
    });

    // Management API permissions so Lambdas can post to devices
    const manageWsPolicy = new iam.PolicyStatement({
      actions: ['execute-api:ManageConnections'],
      resources: [
        `arn:aws:execute-api:${this.region}:${this.account}:${wsApi.apiId}/${wsStage.stageName}/POST/@connections/*`,
      ],
    });
    httpFn.addToRolePolicy(manageWsPolicy);
    wsFn.addToRolePolicy(manageWsPolicy);
    stepFn.addToRolePolicy(manageWsPolicy);

    const wsUrl = `wss://${wsApi.apiId}.execute-api.${this.region}.amazonaws.com/${wsStage.stageName}`;
    httpFn.addEnvironment('WEBSOCKET_API_ENDPOINT', wsUrl);
    wsFn.addEnvironment('WEBSOCKET_API_ENDPOINT', wsUrl);
    stepFn.addEnvironment('WEBSOCKET_API_ENDPOINT', wsUrl);
    httpFn.addEnvironment(
      'WEBSOCKET_MANAGEMENT_ENDPOINT',
      `https://${wsApi.apiId}.execute-api.${this.region}.amazonaws.com/${wsStage.stageName}`
    );
    stepFn.addEnvironment(
      'WEBSOCKET_MANAGEMENT_ENDPOINT',
      `https://${wsApi.apiId}.execute-api.${this.region}.amazonaws.com/${wsStage.stageName}`
    );

    // EventBridge: tick every 1 minute to advance step-driven jobs
    const rule = new events.Rule(this, 'StepTick', {
      schedule: events.Schedule.rate(cdk.Duration.minutes(1)),
      description: 'Advance dating/agent step jobs without long Lambda holds',
    });
    rule.addTarget(new targets.LambdaFunction(stepFn));

    new cdk.CfnOutput(this, 'ApiUrl', {
      value: httpApi.apiEndpoint,
      description: 'HTTP API URL (set as VITE_API_URL / VITE_BACKEND_URL)',
      exportName: 'MobilerunApiUrl',
    });
    new cdk.CfnOutput(this, 'WebSocketUrl', {
      value: wsUrl,
      description: 'WebSocket URL for phone pairing',
      exportName: 'MobilerunWebSocketUrl',
    });
    new cdk.CfnOutput(this, 'StepWorkerArn', {
      value: stepFn.functionArn,
      description: 'Step worker Lambda (dating/agent one-step ticks)',
    });
    new cdk.CfnOutput(this, 'ArchitectureNotes', {
      value:
        'HTTP API + WS API + EventBridge step ticks. Dating/agent loops are step-driven (not one 15-min Lambda). EC2 off. No NAT/ALB/RDS.',
    });
  }
}
