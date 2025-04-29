# AWS Deployment Guide for Aurora Restore Solution

This document outlines the pre-implementation steps required to deploy the Aurora restore solution in AWS. It includes AWS CLI commands for creating all necessary resources with appropriate tags.

## Prerequisites

Before deploying the solution, ensure you have:

1. AWS CLI installed and configured with appropriate credentials
2. Required permissions to create resources in your AWS account
3. Access to both source and target AWS accounts (if cross-account restore)

## Resource Creation Sequence

### 1. Create DynamoDB Table for State Management

```bash
# Create DynamoDB table for state management
aws dynamodb create-table \
  --table-name aurora-restore-state \
  --attribute-definitions AttributeName=operation_id,AttributeType=S \
  --key-schema AttributeName=operation_id,KeyType=HASH \
  --provisioned-throughput ReadCapacityUnits=5,WriteCapacityUnits=5 \
  --tags Key=Environment,Value=Production Key=Project,Value=AuroraRestore Key=Service,Value=StateManagement
```

### 2. Create DynamoDB Table for Audit Logs

```bash
# Create DynamoDB table for audit logs
aws dynamodb create-table \
  --table-name aurora-restore-audit \
  --attribute-definitions AttributeName=metric_id,AttributeType=S \
  --key-schema AttributeName=metric_id,KeyType=HASH \
  --provisioned-throughput ReadCapacityUnits=5,WriteCapacityUnits=5 \
  --tags Key=Environment,Value=Production Key=Project,Value=AuroraRestore Key=Service,Value=Audit
```

### 3. Create SNS Topic for Notifications

```bash
# Create SNS topic for notifications
aws sns create-topic \
  --name aurora-restore-notifications \
  --tags Key=Environment,Value=Production Key=Project,Value=AuroraRestore Key=Service,Value=Notifications
```

### 4. Create IAM Role for Lambda Functions

```bash
# Create IAM role for Lambda functions
aws iam create-role \
  --role-name aurora-restore-lambda-role \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [
      {
        "Effect": "Allow",
        "Principal": {
          "Service": "lambda.amazonaws.com"
        },
        "Action": "sts:AssumeRole"
      }
    ]
  }' \
  --tags Key=Environment,Value=Production Key=Project,Value=AuroraRestore Key=Service,Value=Lambda

# Attach basic Lambda execution policy
aws iam attach-role-policy \
  --role-name aurora-restore-lambda-role \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole

# Create custom policy for Aurora restore operations
aws iam create-policy \
  --policy-name aurora-restore-policy \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [
      {
        "Effect": "Allow",
        "Action": [
          "rds:DescribeDBClusterSnapshots",
          "rds:CopyDBClusterSnapshot",
          "rds:DeleteDBClusterSnapshot",
          "rds:RestoreDBClusterFromSnapshot",
          "rds:DescribeDBClusters",
          "rds:DeleteDBCluster",
          "rds:CreateDBCluster",
          "rds:ModifyDBCluster"
        ],
        "Resource": "*"
      },
      {
        "Effect": "Allow",
        "Action": [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:UpdateItem",
          "dynamodb:DeleteItem"
        ],
        "Resource": [
          "arn:aws:dynamodb:*:*:table/aurora-restore-state",
          "arn:aws:dynamodb:*:*:table/aurora-restore-audit"
        ]
      },
      {
        "Effect": "Allow",
        "Action": [
          "sns:Publish"
        ],
        "Resource": "arn:aws:sns:*:*:aurora-restore-notifications"
      },
      {
        "Effect": "Allow",
        "Action": [
          "secretsmanager:GetSecretValue"
        ],
        "Resource": "arn:aws:secretsmanager:*:*:secret:aurora-restore/*"
      },
      {
        "Effect": "Allow",
        "Action": [
          "ssm:GetParameter",
          "ssm:GetParameters"
        ],
        "Resource": "arn:aws:ssm:*:*:parameter/aurora-restore/*"
      }
    ]
  }' \
  --tags Key=Environment,Value=Production Key=Project,Value=AuroraRestore Key=Service,Value=Lambda

# Attach custom policy to role
aws iam attach-role-policy \
  --role-name aurora-restore-lambda-role \
  --policy-arn arn:aws:iam::$(aws sts get-caller-identity --query Account --output text):policy/aurora-restore-policy
```

### 5. Create SSM Parameters

```bash
# Create SSM parameters for configuration
aws ssm put-parameter \
  --name "/aurora-restore/source-cluster-id" \
  --value "your-source-cluster-id" \
  --type String \
  --tags Key=Environment,Value=Production Key=Project,Value=AuroraRestore Key=Service,Value=Configuration

aws ssm put-parameter \
  --name "/aurora-restore/source-region" \
  --value "us-east-1" \
  --type String \
  --tags Key=Environment,Value=Production Key=Project,Value=AuroraRestore Key=Service,Value=Configuration

aws ssm put-parameter \
  --name "/aurora-restore/target-cluster-id" \
  --value "your-target-cluster-id" \
  --type String \
  --tags Key=Environment,Value=Production Key=Project,Value=AuroraRestore Key=Service,Value=Configuration

aws ssm put-parameter \
  --name "/aurora-restore/target-region" \
  --value "us-west-2" \
  --type String \
  --tags Key=Environment,Value=Production Key=Project,Value=AuroraRestore Key=Service,Value=Configuration

aws ssm put-parameter \
  --name "/aurora-restore/kms-key-id" \
  --value "arn:aws:kms:region:account:key/your-kms-key-id" \
  --type String \
  --tags Key=Environment,Value=Production Key=Project,Value=AuroraRestore Key=Service,Value=Configuration
```

### 6. Create Secrets in Secrets Manager

```bash
# Create secret for master database credentials
aws secretsmanager create-secret \
  --name aurora-restore/master-db-credentials \
  --description "Master database credentials for Aurora restore" \
  --secret-string '{
    "database": "your_database_name",
    "username": "admin",
    "password": "your-secure-password"
  }' \
  --tags Key=Environment,Value=Production Key=Project,Value=AuroraRestore Key=Service,Value=Credentials

# Create secret for application and read-only user credentials
aws secretsmanager create-secret \
  --name aurora-restore/app-db-credentials \
  --description "Application and read-only user credentials for Aurora restore" \
  --secret-string '{
    "app_username": "app_user",
    "app_password": "your-secure-app-password",
    "readonly_username": "readonly_user",
    "readonly_password": "your-secure-readonly-password"
  }' \
  --tags Key=Environment,Value=Production Key=Project,Value=AuroraRestore Key=Service,Value=Credentials
```

### 7. Create CloudWatch Log Group

```bash
# Create CloudWatch log group for Lambda functions
aws logs create-log-group \
  --log-group-name /aws/lambda/aurora-restore \
  --tags Environment=Production,Project=AuroraRestore,Service=Logging
```

### 8. Create S3 Bucket for Deployment Packages

```bash
# Create S3 bucket for deployment packages
aws s3api create-bucket \
  --bucket aurora-restore-deployment \
  --region us-east-1 \
  --create-bucket-configuration LocationConstraint=us-east-1

# Add tags to the bucket
aws s3api put-bucket-tagging \
  --bucket aurora-restore-deployment \
  --tagging 'TagSet=[{Key=Environment,Value=Production},{Key=Project,Value=AuroraRestore},{Key=Service,Value=Deployment}]'
```

## Cross-Account Configuration (if applicable)

If you're performing cross-account restores, you'll need to set up additional permissions:

### 1. Create IAM Role in Target Account for Source Account to Assume

```bash
# In the target account
aws iam create-role \
  --role-name aurora-restore-cross-account-role \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [
      {
        "Effect": "Allow",
        "Principal": {
          "AWS": "arn:aws:iam::SOURCE_ACCOUNT_ID:root"
        },
        "Action": "sts:AssumeRole"
      }
    ]
  }' \
  --tags Key=Environment,Value=Production Key=Project,Value=AuroraRestore Key=Service,Value=CrossAccount

# Attach policy to the role
aws iam attach-role-policy \
  --role-name aurora-restore-cross-account-role \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole

# Create custom policy for cross-account operations
aws iam create-policy \
  --policy-name aurora-restore-cross-account-policy \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [
      {
        "Effect": "Allow",
        "Action": [
          "rds:DescribeDBClusterSnapshots",
          "rds:CopyDBClusterSnapshot",
          "rds:DeleteDBClusterSnapshot",
          "rds:RestoreDBClusterFromSnapshot",
          "rds:DescribeDBClusters",
          "rds:DeleteDBCluster",
          "rds:CreateDBCluster",
          "rds:ModifyDBCluster"
        ],
        "Resource": "*"
      }
    ]
  }' \
  --tags Key=Environment,Value=Production Key=Project,Value=AuroraRestore Key=Service,Value=CrossAccount

# Attach custom policy to role
aws iam attach-role-policy \
  --role-name aurora-restore-cross-account-role \
  --policy-arn arn:aws:iam::$(aws sts get-caller-identity --query Account --output text):policy/aurora-restore-cross-account-policy
```

### 2. Update SSM Parameters with Cross-Account Information

```bash
# Add cross-account role ARN to SSM parameters
aws ssm put-parameter \
  --name "/aurora-restore/cross-account-role-arn" \
  --value "arn:aws:iam::TARGET_ACCOUNT_ID:role/aurora-restore-cross-account-role" \
  --type String \
  --tags Key=Environment,Value=Production Key=Project,Value=AuroraRestore Key=Service,Value=CrossAccount
```

## Verification Steps

After creating all resources, verify the setup:

```bash
# Verify DynamoDB tables
aws dynamodb describe-table --table-name aurora-restore-state
aws dynamodb describe-table --table-name aurora-restore-audit

# Verify SNS topic
aws sns get-topic-attributes --topic-arn arn:aws:sns:$(aws configure get region):$(aws sts get-caller-identity --query Account --output text):aurora-restore-notifications

# Verify IAM role
aws iam get-role --role-name aurora-restore-lambda-role

# Verify SSM parameters
aws ssm get-parameter --name "/aurora-restore/source-cluster-id"
aws ssm get-parameter --name "/aurora-restore/target-cluster-id"

# Verify Secrets Manager secrets
aws secretsmanager describe-secret --secret-id aurora-restore/master-db-credentials
aws secretsmanager describe-secret --secret-id aurora-restore/app-db-credentials

# Verify CloudWatch log group
aws logs describe-log-groups --log-group-name-prefix /aws/lambda/aurora-restore

# Verify S3 bucket
aws s3api get-bucket-tagging --bucket aurora-restore-deployment
```

## Next Steps

After completing these pre-implementation steps:

1. Package and deploy the Lambda functions
2. Set up Step Functions workflow (if applicable)
3. Configure event triggers or scheduling
4. Test the solution with a small-scale restore

## Packaging and Deploying Lambda Layers

Before deploying the Lambda functions, you need to package the utilities and dependencies as Lambda layers. This section provides detailed steps for creating and deploying these layers.

### 1. Package Utilities as a Lambda Layer

The utilities code needs to be packaged as a Lambda layer that will be used by all Lambda functions.

```bash
# Create a directory for the layer
mkdir -p aurora-restore-layers/utils-layer/python

# Copy the utils directory to the layer directory
cp -r utils/* aurora-restore-layers/utils-layer/python/

# Create a zip file for the layer
cd aurora-restore-layers/utils-layer
zip -r ../utils-layer.zip .
cd ../..

# Upload the layer to S3
aws s3 cp aurora-restore-layers/utils-layer.zip s3://aurora-restore-deployment/layers/

# Create the Lambda layer
aws lambda publish-layer-version \
  --layer-name aurora-restore-utils \
  --description "Utilities for Aurora restore Lambda functions" \
  --content S3Bucket=aurora-restore-deployment,S3Key=layers/utils-layer.zip \
  --compatible-runtimes python3.9 \
  --compatible-architectures x86_64 \
  --tags Environment=Production,Project=AuroraRestore,Service=Lambda
```

### 2. Package Dependencies as Lambda Layers

You need to package the required Python dependencies as separate Lambda layers.

#### 2.1. Package python-json-logger

```bash
# Create a directory for the layer
mkdir -p aurora-restore-layers/json-logger-layer/python

# Install the dependency to the layer directory
pip install python-json-logger -t aurora-restore-layers/json-logger-layer/python/

# Create a zip file for the layer
cd aurora-restore-layers/json-logger-layer
zip -r ../json-logger-layer.zip .
cd ../..

# Upload the layer to S3
aws s3 cp aurora-restore-layers/json-logger-layer.zip s3://aurora-restore-deployment/layers/

# Create the Lambda layer
aws lambda publish-layer-version \
  --layer-name aurora-restore-json-logger \
  --description "Python JSON Logger for Aurora restore Lambda functions" \
  --content S3Bucket=aurora-restore-deployment,S3Key=layers/json-logger-layer.zip \
  --compatible-runtimes python3.9 \
  --compatible-architectures x86_64 \
  --tags Environment=Production,Project=AuroraRestore,Service=Lambda
```

#### 2.2. Package psycopg2-binary

```bash
# Create a directory for the layer
mkdir -p aurora-restore-layers/psycopg2-layer/python

# Install the dependency to the layer directory
pip install psycopg2-binary -t aurora-restore-layers/psycopg2-layer/python/

# Create a zip file for the layer
cd aurora-restore-layers/psycopg2-layer
zip -r ../psycopg2-layer.zip .
cd ../..

# Upload the layer to S3
aws s3 cp aurora-restore-layers/psycopg2-layer.zip s3://aurora-restore-deployment/layers/

# Create the Lambda layer
aws lambda publish-layer-version \
  --layer-name aurora-restore-psycopg2 \
  --description "Psycopg2 for Aurora restore Lambda functions" \
  --content S3Bucket=aurora-restore-deployment,S3Key=layers/psycopg2-layer.zip \
  --compatible-runtimes python3.9 \
  --compatible-architectures x86_64 \
  --tags Environment=Production,Project=AuroraRestore,Service=Lambda
```

#### 2.3. Package tenacity (for retry mechanism)

```bash
# Create a directory for the layer
mkdir -p aurora-restore-layers/tenacity-layer/python

# Install the dependency to the layer directory
pip install tenacity -t aurora-restore-layers/tenacity-layer/python/

# Create a zip file for the layer
cd aurora-restore-layers/tenacity-layer
zip -r ../tenacity-layer.zip .
cd ../..

# Upload the layer to S3
aws s3 cp aurora-restore-layers/tenacity-layer.zip s3://aurora-restore-deployment/layers/

# Create the Lambda layer
aws lambda publish-layer-version \
  --layer-name aurora-restore-tenacity \
  --description "Tenacity for Aurora restore Lambda functions" \
  --content S3Bucket=aurora-restore-deployment,S3Key=layers/tenacity-layer.zip \
  --compatible-runtimes python3.9 \
  --compatible-architectures x86_64 \
  --tags Environment=Production,Project=AuroraRestore,Service=Lambda
```

### 3. Package and Deploy Lambda Functions

Now you can package and deploy each Lambda function with the required layers.

```bash
# Create a directory for the Lambda function
mkdir -p aurora-restore-lambda/snapshot-check

# Copy the Lambda function code
cp lambda_functions/aurora-restore-snapshot-check/lambda_function.py aurora-restore-lambda/snapshot-check/

# Create a zip file for the Lambda function
cd aurora-restore-lambda/snapshot-check
zip -r ../snapshot-check.zip .
cd ../..

# Upload the Lambda function to S3
aws s3 cp aurora-restore-lambda/snapshot-check.zip s3://aurora-restore-deployment/lambda/

# Get the layer ARNs
UTILS_LAYER_ARN=$(aws lambda list-layer-versions --layer-name aurora-restore-utils --query 'LayerVersions[0].LayerVersionArn' --output text)
JSON_LOGGER_LAYER_ARN=$(aws lambda list-layer-versions --layer-name aurora-restore-json-logger --query 'LayerVersions[0].LayerVersionArn' --output text)
PSYCOPG2_LAYER_ARN=$(aws lambda list-layer-versions --layer-name aurora-restore-psycopg2 --query 'LayerVersions[0].LayerVersionArn' --output text)
TENACITY_LAYER_ARN=$(aws lambda list-layer-versions --layer-name aurora-restore-tenacity --query 'LayerVersions[0].LayerVersionArn' --output text)

# Create the Lambda function
aws lambda create-function \
  --function-name aurora-restore-snapshot-check \
  --runtime python3.9 \
  --handler lambda_function.lambda_handler \
  --role arn:aws:iam::$(aws sts get-caller-identity --query Account --output text):role/aurora-restore-lambda-role \
  --code S3Bucket=aurora-restore-deployment,S3Key=lambda/snapshot-check.zip \
  --timeout 300 \
  --memory-size 256 \
  --layers $UTILS_LAYER_ARN $JSON_LOGGER_LAYER_ARN $PSYCOPG2_LAYER_ARN $TENACITY_LAYER_ARN \
  --environment Variables={STATE_TABLE_NAME=aurora-restore-state,AUDIT_TABLE_NAME=aurora-restore-audit} \
  --tags Environment=Production,Project=AuroraRestore,Service=Lambda
```

Repeat the above steps for each Lambda function, adjusting the function name, handler, and environment variables as needed.

### 4. Verify Lambda Layers and Functions

After deploying the layers and functions, verify that they were created correctly:

```bash
# Verify Lambda layers
aws lambda list-layers --compatible-runtime python3.9

# Verify Lambda functions
aws lambda list-functions --query 'Functions[?starts_with(FunctionName, `aurora-restore-`)]'
```

## Environment Variables for Lambda Functions

Each Lambda function requires specific environment variables to function correctly. Below is a detailed list of environment variables for each function:

### Common Environment Variables

All Lambda functions share these common environment variables:

| Variable Name | Description | Example Value |
|---------------|-------------|---------------|
| `STATE_TABLE_NAME` | DynamoDB table for state management | `aurora-restore-state` |
| `AUDIT_TABLE_NAME` | DynamoDB table for audit logs | `aurora-restore-audit` |
| `ENVIRONMENT` | Environment name (dev, test, prod) | `prod` |
| `LOG_LEVEL` | Logging level (DEBUG, INFO, WARNING, ERROR) | `INFO` |

### Function-Specific Environment Variables

#### 1. aurora-restore-snapshot-check

| Variable Name | Description | Example Value |
|---------------|-------------|---------------|
| `SOURCE_REGION` | AWS region of the source cluster | `us-east-1` |
| `SOURCE_CLUSTER_ID` | ID of the source Aurora cluster | `my-source-cluster` |
| `SNAPSHOT_PREFIX` | Prefix for snapshot names | `aurora-snapshot` |

#### 2. aurora-restore-copy-snapshot

| Variable Name | Description | Example Value |
|---------------|-------------|---------------|
| `SOURCE_REGION` | AWS region of the source cluster | `us-east-1` |
| `TARGET_REGION` | AWS region for the target cluster | `us-west-2` |
| `KMS_KEY_ID` | KMS key ID for snapshot encryption | `arn:aws:kms:us-west-2:123456789012:key/abcd1234-ef56-gh78-ij90-klmnopqrstuv` |

#### 3. aurora-restore-check-copy-status

| Variable Name | Description | Example Value |
|---------------|-------------|---------------|
| `SOURCE_REGION` | AWS region of the source cluster | `us-east-1` |
| `TARGET_REGION` | AWS region for the target cluster | `us-west-2` |
| `MAX_COPY_ATTEMPTS` | Maximum number of copy status check attempts | `60` |
| `COPY_CHECK_INTERVAL` | Interval between copy status checks (seconds) | `30` |

#### 4. aurora-restore-delete-rds

| Variable Name | Description | Example Value |
|---------------|-------------|---------------|
| `TARGET_REGION` | AWS region for the target cluster | `us-west-2` |
| `TARGET_CLUSTER_ID` | ID of the target Aurora cluster | `my-target-cluster` |
| `SKIP_FINAL_SNAPSHOT` | Whether to skip final snapshot when deleting | `true` |

#### 5. aurora-restore-restore-snapshot

| Variable Name | Description | Example Value |
|---------------|-------------|---------------|
| `TARGET_REGION` | AWS region for the target cluster | `us-west-2` |
| `TARGET_CLUSTER_ID` | ID of the target Aurora cluster | `my-target-cluster` |
| `DB_SUBNET_GROUP_NAME` | DB subnet group for the restored cluster | `my-db-subnet-group` |
| `VPC_SECURITY_GROUP_IDS` | Comma-separated list of VPC security group IDs | `sg-12345678,sg-87654321` |
| `KMS_KEY_ID` | KMS key ID for encryption | `arn:aws:kms:us-west-2:123456789012:key/abcd1234-ef56-gh78-ij90-klmnopqrstuv` |
| `PORT` | Port for the restored cluster | `5432` |
| `DELETION_PROTECTION` | Whether to enable deletion protection | `false` |

#### 6. aurora-restore-check-restore-status

| Variable Name | Description | Example Value |
|---------------|-------------|---------------|
| `TARGET_REGION` | AWS region for the target cluster | `us-west-2` |
| `TARGET_CLUSTER_ID` | ID of the target Aurora cluster | `my-target-cluster` |
| `MAX_RESTORE_ATTEMPTS` | Maximum number of restore status check attempts | `60` |
| `RESTORE_CHECK_INTERVAL` | Interval between restore status checks (seconds) | `30` |

#### 7. aurora-restore-setup-db-users

| Variable Name | Description | Example Value |
|---------------|-------------|---------------|
| `TARGET_REGION` | AWS region for the target cluster | `us-west-2` |
| `TARGET_CLUSTER_ID` | ID of the target Aurora cluster | `my-target-cluster` |
| `MASTER_CREDENTIALS_SECRET_ID` | Secret ID for master database credentials | `aurora-restore/master-db-credentials` |
| `APP_CREDENTIALS_SECRET_ID` | Secret ID for application credentials | `aurora-restore/app-db-credentials` |
| `DB_CONNECTION_TIMEOUT` | Database connection timeout (seconds) | `30` |

#### 8. aurora-restore-archive-snapshot

| Variable Name | Description | Example Value |
|---------------|-------------|---------------|
| `TARGET_REGION` | AWS region for the target cluster | `us-west-2` |
| `ARCHIVE_SNAPSHOT` | Whether to archive the snapshot after restore | `true` |

#### 9. aurora-restore-sns-notification

| Variable Name | Description | Example Value |
|---------------|-------------|---------------|
| `TARGET_REGION` | AWS region for the target cluster | `us-west-2` |
| `SNS_TOPIC_ARN` | ARN of the SNS topic for notifications | `arn:aws:sns:us-west-2:123456789012:aurora-restore-notifications` |

### Setting Environment Variables for Lambda Functions

You can set these environment variables when creating or updating Lambda functions:

```bash
# Example for aurora-restore-snapshot-check
aws lambda update-function-configuration \
  --function-name aurora-restore-snapshot-check \
  --environment "Variables={
    STATE_TABLE_NAME=aurora-restore-state,
    AUDIT_TABLE_NAME=aurora-restore-audit,
    ENVIRONMENT=prod,
    LOG_LEVEL=INFO,
    SOURCE_REGION=us-east-1,
    SOURCE_CLUSTER_ID=my-source-cluster,
    SNAPSHOT_PREFIX=aurora-snapshot
  }"
```

Repeat this process for each Lambda function, setting the appropriate environment variables.

## Troubleshooting

If you encounter issues during resource creation:

1. Check AWS CloudTrail logs for permission errors
2. Verify IAM role permissions
3. Ensure all required services are enabled in your AWS account
4. Check for resource naming conflicts
5. Verify cross-account permissions if applicable 