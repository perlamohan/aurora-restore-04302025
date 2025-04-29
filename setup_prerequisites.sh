#!/bin/bash

# Set your AWS region
REGION="us-east-1"  # Change this to your desired region

# Create DynamoDB tables
echo "Creating DynamoDB tables..."

# State table
aws dynamodb create-table \
    --table-name "aurora-restore-state-${REGION}" \
    --attribute-definitions \
        AttributeName=operation_id,AttributeType=S \
    --key-schema \
        AttributeName=operation_id,KeyType=HASH \
    --provisioned-throughput \
        ReadCapacityUnits=5,WriteCapacityUnits=5 \
    --region ${REGION}

# Audit table
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

# Metrics table
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

# Create SSM parameters
echo "Creating SSM parameters..."

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

# Create Lambda layer
echo "Creating Lambda layer..."

# Create a temporary directory for the layer
mkdir -p lambda-layer/python
cd lambda-layer/python

# Install required packages
pip install boto3 jsonschema -t .

# Create the layer zip
cd ..
zip -r ../lambda-layer.zip python/

# Create the layer in AWS
aws lambda publish-layer-version \
    --layer-name aurora-restore-dependencies \
    --description "Dependencies for Aurora restore Lambda functions" \
    --zip-file fileb://lambda-layer.zip \
    --compatible-runtimes python3.9 \
    --region ${REGION}

# Clean up
cd ..
rm -rf lambda-layer

echo "Prerequisites setup complete!" 