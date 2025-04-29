# Aurora Restore

A serverless application for restoring Aurora databases across regions using AWS Lambda and Step Functions.

## Overview

This project provides a set of Lambda functions that work together to restore an Aurora database from one region to another. The process involves:

1. Creating a snapshot of the source database
2. Copying the snapshot to the target region
3. Restoring the database from the snapshot
4. Setting up database users and permissions
5. Verifying the restore
6. Cleaning up temporary resources

## Architecture

The application uses the following AWS services:

- **AWS Lambda**: Executes the restore operations
- **AWS Step Functions**: Orchestrates the workflow
- **AWS RDS**: Manages the Aurora databases and snapshots
- **AWS SNS**: Sends notifications about the restore process
- **AWS DynamoDB**: Stores state information
- **AWS SSM Parameter Store**: Stores configuration

## Lambda Functions

The application consists of the following Lambda functions:

1. **aurora-restore-copy-snapshot**: Creates a snapshot of the source database and copies it to the target region
2. **aurora-restore-check-copy-status**: Checks the status of the snapshot copy
3. **aurora-restore-restore-snapshot**: Restores the database from the snapshot
4. **aurora-restore-check-restore-status**: Checks the status of the database restore
5. **aurora-restore-setup-db-users**: Sets up database users and permissions
6. **aurora-restore-verify-restore**: Verifies the restored database
7. **aurora-restore-cleanup**: Cleans up temporary resources
8. **aurora-restore-notify-completion**: Sends a notification when the restore is complete

## Configuration

The application uses environment variables for configuration:

### Required Configuration

- `SOURCE_REGION`: The region of the source database
- `TARGET_REGION`: The region where the database will be restored
- `SOURCE_CLUSTER_ID`: The identifier of the source database cluster
- `TARGET_CLUSTER_ID`: The identifier for the target database cluster

### Optional Configuration

- `SNAPSHOT_RETENTION_DAYS`: Number of days to retain snapshots (default: 7)
- `MAX_WAIT_TIME`: Maximum time to wait for operations to complete in seconds (default: 3600)
- `WAIT_INTERVAL`: Interval between status checks in seconds (default: 30)
- `NOTIFICATION_TOPIC_ARN`: ARN of the SNS topic for notifications
- `STATE_MACHINE_ARN`: ARN of the Step Functions state machine

## Deployment

### Prerequisites

- AWS CLI configured with appropriate permissions
- Python 3.8 or later
- Node.js 14 or later (for CDK deployment)

### Manual Deployment

1. Create a Lambda layer with the required dependencies:

```bash
cd lambda_layers
./install_dependencies.sh
```

2. Deploy the Lambda functions and Step Functions state machine using AWS CDK:

```bash
cdk deploy
```

## Usage

To start a restore operation, invoke the Step Functions state machine with the following input:

```json
{
  "source_cluster_id": "my-source-cluster",
  "target_cluster_id": "my-target-cluster"
}
```

## Monitoring

The application logs all operations to CloudWatch Logs. Each log entry includes:

- Operation ID
- Handler name
- Timestamp
- Log level
- Message
- Additional context

## Error Handling

The application includes comprehensive error handling:

- All operations are idempotent
- Errors are logged with full context
- Notifications are sent for all errors
- The state machine tracks the state of each operation

## License

This project is licensed under the MIT License - see the LICENSE file for details. 