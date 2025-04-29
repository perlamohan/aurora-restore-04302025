# Aurora Restore Snapshot Check - Deployment Manual

This document provides step-by-step instructions for deploying and testing the `aurora-restore-snapshot-check` Lambda function.

## Table of Contents
1. [Prerequisites](#prerequisites)
2. [Setting Up Infrastructure](#setting-up-infrastructure)
3. [Creating Lambda Layers](#creating-lambda-layers)
4. [Deploying the Lambda Function](#deploying-the-lambda-function)
5. [Testing the Function](#testing-the-function)
6. [Troubleshooting](#troubleshooting)

## Prerequisites

- AWS CLI installed and configured with appropriate credentials
- Python 3.9 installed
- Required Python packages:
  - boto3
  - jsonschema

## Setting Up Infrastructure

1. **Create DynamoDB Tables**

```bash
# Set your AWS region
export REGION="us-east-1"  # Change to your desired region

# Create State Table
aws dynamodb create-table \
    --table-name "aurora-restore-state-${REGION}" \
    --attribute-definitions \
        AttributeName=operation_id,AttributeType=S \
    --key-schema \
        AttributeName=operation_id,KeyType=HASH \
    --provisioned-throughput \
        ReadCapacityUnits=5,WriteCapacityUnits=5 \
    --region ${REGION}

# Create Audit Table
aws dynamodb create-table \
    --table-name "aurora-restore-audit-${REGION}" \
    --attribute-definitions \
        AttributeName=operation_id,AttributeType=S \
        AttributeName=timestamp,AttributeType=N \
    --key-schema \
        AttributeName=operation_id,KeyType=HASH \
        AttributeName=timestamp,KeyType=RANGE \
    --provisioned-throughput \
        ReadCapacityUnits=5,WriteCapacityUnits=5 \
    --region ${REGION}

# Create Metrics Table
aws dynamodb create-table \
    --table-name "aurora-restore-metrics-${REGION}" \
    --attribute-definitions \
        AttributeName=operation_id,AttributeType=S \
        AttributeName=metric_name,AttributeType=S \
    --key-schema \
        AttributeName=operation_id,KeyType=HASH \
        AttributeName=metric_name,KeyType=RANGE \
    --provisioned-throughput \
        ReadCapacityUnits=5,WriteCapacityUnits=5 \
    --region ${REGION}
```

2. **Create SSM Parameters**

```bash
# Required parameters
aws ssm put-parameter \
    --name "/aurora-restore/source-region" \
    --value "${REGION}" \
    --type String \
    --region ${REGION}

aws ssm put-parameter \
    --name "/aurora-restore/source-cluster-id" \
    --value "your-source-cluster-id" \
    --type String \
    --region ${REGION}

aws ssm put-parameter \
    --name "/aurora-restore/snapshot-prefix" \
    --value "daily-snapshot" \
    --type String \
    --region ${REGION}

# Optional parameters
aws ssm put-parameter \
    --name "/aurora-restore/environment" \
    --value "dev" \
    --type String \
    --region ${REGION}

aws ssm put-parameter \
    --name "/aurora-restore/log-level" \
    --value "INFO" \
    --type String \
    --region ${REGION}
```

## Creating Lambda Layers

1. **Create Utils Layer**

```bash
# Create directory structure
mkdir -p lambda-layers/utils/python
cd lambda-layers/utils/python

# Copy utility files
cp ../../../utils/base_handler.py .
cp ../../../utils/config_utils.py .
cp ../../../utils/state_utils.py .
cp ../../../utils/aws_utils.py .

# Create __init__.py
touch __init__.py

# Create the layer zip
cd ..
zip -r ../utils-layer.zip python/

# Create the layer in AWS
aws lambda publish-layer-version \
    --layer-name aurora-restore-utils \
    --description "Utility functions for Aurora restore Lambda functions" \
    --zip-file fileb://utils-layer.zip \
    --compatible-runtimes python3.9 \
    --region ${REGION}

cd ../..
```

2. **Create Dependencies Layer**

```bash
# Create directory structure
mkdir -p lambda-layers/dependencies/python
cd lambda-layers/dependencies/python

# Install required packages
pip install boto3 jsonschema -t .

# Create the layer zip
cd ..
zip -r ../dependencies-layer.zip python/

# Create the layer in AWS
aws lambda publish-layer-version \
    --layer-name aurora-restore-dependencies \
    --description "Dependencies for Aurora restore Lambda functions" \
    --zip-file fileb://dependencies-layer.zip \
    --compatible-runtimes python3.9 \
    --region ${REGION}

cd ../..
```

## Deploying the Lambda Function

1. **Create Deployment Package**

```bash
# Create deployment directory
mkdir -p deployment
cd deployment

# Copy Lambda function
cp ../lambda_functions/aurora-restore-snapshot-check/lambda_function.py .

# Create deployment zip
zip -r ../deployment.zip lambda_function.py

cd ..
```

2. **Create IAM Role**

```bash
# Create role
aws iam create-role \
    --role-name aurora-restore-lambda-role \
    --assume-role-policy-document '{
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {
                "Service": "lambda.amazonaws.com"
            },
            "Action": "sts:AssumeRole"
        }]
    }' \
    --region ${REGION}

# Attach policies
aws iam attach-role-policy \
    --role-name aurora-restore-lambda-role \
    --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole \
    --region ${REGION}

aws iam attach-role-policy \
    --role-name aurora-restore-lambda-role \
    --policy-arn arn:aws:iam::aws:policy/AmazonDynamoDBFullAccess \
    --region ${REGION}

aws iam attach-role-policy \
    --role-name aurora-restore-lambda-role \
    --policy-arn arn:aws:iam::aws:policy/AmazonSSMReadOnlyAccess \
    --region ${REGION}

aws iam attach-role-policy \
    --role-name aurora-restore-lambda-role \
    --policy-arn arn:aws:iam::aws:policy/AmazonRDSReadOnlyAccess \
    --region ${REGION}
```

3. **Create Lambda Function**

```bash
# Get role ARN
ROLE_ARN=$(aws iam get-role --role-name aurora-restore-lambda-role --query 'Role.Arn' --output text --region ${REGION})

# Create function
aws lambda create-function \
    --function-name aurora-restore-snapshot-check \
    --runtime python3.9 \
    --role ${ROLE_ARN} \
    --handler lambda_function.lambda_handler \
    --zip-file fileb://deployment.zip \
    --timeout 300 \
    --memory-size 256 \
    --environment "Variables={STATE_TABLE_NAME=aurora-restore-state-${REGION},AUDIT_TABLE_NAME=aurora-restore-audit-${REGION},METRICS_TABLE_NAME=aurora-restore-metrics-${REGION}}" \
    --region ${REGION}

# Add layers
aws lambda update-function-configuration \
    --function-name aurora-restore-snapshot-check \
    --layers arn:aws:lambda:${REGION}:${AWS_ACCOUNT_ID}:layer:aurora-restore-utils:1 arn:aws:lambda:${REGION}:${AWS_ACCOUNT_ID}:layer:aurora-restore-dependencies:1 \
    --region ${REGION}
```

## Testing the Function

1. **Create Test Event**

Create a file named `test_event.json` with the following content:

```json
{
    "operation_id": "test-op-001",
    "source_region": "us-east-1",
    "source_cluster_id": "your-source-cluster-id",
    "snapshot_prefix": "daily-snapshot",
    "environment": "dev",
    "log_level": "INFO",
    "target_date": "2024-04-29"
}
```

2. **Invoke Function**

```bash
# Invoke function
aws lambda invoke \
    --function-name aurora-restore-snapshot-check \
    --payload file://test_event.json \
    --region ${REGION} \
    response.json

# Check response
cat response.json
```

3. **Verify DynamoDB Entries**

```bash
# Check state table
aws dynamodb get-item \
    --table-name aurora-restore-state-${REGION} \
    --key '{"operation_id": {"S": "test-op-001"}}' \
    --region ${REGION}

# Check audit table
aws dynamodb query \
    --table-name aurora-restore-audit-${REGION} \
    --key-condition-expression "operation_id = :op_id" \
    --expression-attribute-values '{":op_id": {"S": "test-op-001"}}' \
    --region ${REGION}
```

## Troubleshooting

1. **Check CloudWatch Logs**

```bash
# Get log stream name
LOG_STREAM=$(aws logs describe-log-streams \
    --log-group-name /aws/lambda/aurora-restore-snapshot-check \
    --order-by LastEventTime \
    --descending \
    --limit 1 \
    --query 'logStreams[0].logStreamName' \
    --output text \
    --region ${REGION})

# Get logs
aws logs get-log-events \
    --log-group-name /aws/lambda/aurora-restore-snapshot-check \
    --log-stream-name ${LOG_STREAM} \
    --region ${REGION}
```

2. **Common Issues**

- **Missing Permissions**: Ensure the Lambda role has all required permissions
- **Invalid SSM Parameters**: Verify SSM parameter values are correct
- **Layer Issues**: Check layer versions and compatibility
- **DynamoDB Errors**: Verify table names and permissions

3. **Cleanup**

```bash
# Delete Lambda function
aws lambda delete-function \
    --function-name aurora-restore-snapshot-check \
    --region ${REGION}

# Delete IAM role
aws iam detach-role-policy \
    --role-name aurora-restore-lambda-role \
    --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole \
    --region ${REGION}

aws iam detach-role-policy \
    --role-name aurora-restore-lambda-role \
    --policy-arn arn:aws:iam::aws:policy/AmazonDynamoDBFullAccess \
    --region ${REGION}

aws iam detach-role-policy \
    --role-name aurora-restore-lambda-role \
    --policy-arn arn:aws:iam::aws:policy/AmazonSSMReadOnlyAccess \
    --region ${REGION}

aws iam detach-role-policy \
    --role-name aurora-restore-lambda-role \
    --policy-arn arn:aws:iam::aws:policy/AmazonRDSReadOnlyAccess \
    --region ${REGION}

aws iam delete-role \
    --role-name aurora-restore-lambda-role \
    --region ${REGION}

# Delete DynamoDB tables
aws dynamodb delete-table \
    --table-name aurora-restore-state-${REGION} \
    --region ${REGION}

aws dynamodb delete-table \
    --table-name aurora-restore-audit-${REGION} \
    --region ${REGION}

aws dynamodb delete-table \
    --table-name aurora-restore-metrics-${REGION} \
    --region ${REGION}
``` 