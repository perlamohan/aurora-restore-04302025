# Manual Run Guide for Aurora Restore Lambda Functions

This guide provides step-by-step instructions for manually running each Lambda function in the Aurora restore pipeline from the AWS Console. It includes the required arguments for testing each function.

## Prerequisites

Before running the Lambda functions manually, ensure you have:

1. Deployed all Lambda functions as described in the AWS deployment guide
2. Set up all required environment variables for each function
3. Created the necessary AWS resources (DynamoDB tables, SNS topics, etc.)
4. Appropriate permissions to invoke Lambda functions

## General Steps for Manual Testing

1. Log in to the AWS Management Console
2. Navigate to the Lambda service
3. Select the function you want to test
4. Click on the "Test" tab
5. Create a new test event or use an existing one
6. Enter the JSON payload as described below
7. Click "Test" to run the function

## Function-Specific Test Events

### 1. aurora-restore-snapshot-check

This function checks if a daily snapshot exists in the source account.

```json
{
  "operation_id": "manual-test-op-123",
  "target_date": "2023-05-15",
  "source_cluster_id": "your-source-cluster",
  "source_region": "us-east-1"
}
```

**Required Environment Variables:**
- `SOURCE_REGION`
- `SOURCE_CLUSTER_ID`
- `SNAPSHOT_PREFIX`
- `STATE_TABLE_NAME`
- `AUDIT_TABLE_NAME`

### 2. aurora-restore-copy-snapshot

This function copies a snapshot from the source to the target region.

```json
{
  "operation_id": "manual-test-op-123",
  "source_snapshot_name": "aurora-snapshot-your-source-cluster-2023-05-15",
  "target_snapshot_name": "aurora-snapshot-your-target-cluster-2023-05-15",
  "source_region": "us-east-1",
  "target_region": "us-west-2"
}
```

**Required Environment Variables:**
- `SOURCE_REGION`
- `TARGET_REGION`
- `KMS_KEY_ID`
- `STATE_TABLE_NAME`
- `AUDIT_TABLE_NAME`

### 3. aurora-restore-check-copy-status

This function checks the status of a snapshot copy operation.

```json
{
  "operation_id": "manual-test-op-123",
  "target_snapshot_name": "aurora-snapshot-your-target-cluster-2023-05-15",
  "source_region": "us-east-1",
  "target_region": "us-west-2"
}
```

**Required Environment Variables:**
- `SOURCE_REGION`
- `TARGET_REGION`
- `MAX_COPY_ATTEMPTS`
- `COPY_CHECK_INTERVAL`
- `STATE_TABLE_NAME`
- `AUDIT_TABLE_NAME`

### 4. aurora-restore-delete-rds

This function deletes an existing RDS cluster.

```json
{
  "operation_id": "manual-test-op-123",
  "target_cluster_id": "your-target-cluster",
  "target_region": "us-west-2",
  "skip_final_snapshot": true
}
```

**Required Environment Variables:**
- `TARGET_REGION`
- `TARGET_CLUSTER_ID`
- `SKIP_FINAL_SNAPSHOT`
- `STATE_TABLE_NAME`
- `AUDIT_TABLE_NAME`

### 5. aurora-restore-restore-snapshot

This function restores a DB cluster from a snapshot.

```json
{
  "operation_id": "manual-test-op-123",
  "target_snapshot_name": "aurora-snapshot-your-target-cluster-2023-05-15",
  "target_cluster_id": "your-target-cluster",
  "target_region": "us-west-2",
  "db_subnet_group_name": "your-db-subnet-group",
  "vpc_security_group_ids": "sg-12345678,sg-87654321",
  "port": 5432,
  "deletion_protection": false
}
```

**Required Environment Variables:**
- `TARGET_REGION`
- `TARGET_CLUSTER_ID`
- `DB_SUBNET_GROUP_NAME`
- `VPC_SECURITY_GROUP_IDS`
- `KMS_KEY_ID`
- `PORT`
- `DELETION_PROTECTION`
- `STATE_TABLE_NAME`
- `AUDIT_TABLE_NAME`

### 6. aurora-restore-check-restore-status

This function checks the status of a cluster restore operation.

```json
{
  "operation_id": "manual-test-op-123",
  "target_cluster_id": "your-target-cluster",
  "target_region": "us-west-2"
}
```

**Required Environment Variables:**
- `TARGET_REGION`
- `TARGET_CLUSTER_ID`
- `MAX_RESTORE_ATTEMPTS`
- `RESTORE_CHECK_INTERVAL`
- `STATE_TABLE_NAME`
- `AUDIT_TABLE_NAME`

### 7. aurora-restore-setup-db-users

This function sets up database users and permissions after restore.

```json
{
  "operation_id": "manual-test-op-123",
  "target_cluster_id": "your-target-cluster",
  "target_region": "us-west-2",
  "cluster_endpoint": "your-cluster.xxxxx.region.rds.amazonaws.com",
  "cluster_port": 5432
}
```

**Required Environment Variables:**
- `TARGET_REGION`
- `TARGET_CLUSTER_ID`
- `MASTER_CREDENTIALS_SECRET_ID`
- `APP_CREDENTIALS_SECRET_ID`
- `DB_CONNECTION_TIMEOUT`
- `STATE_TABLE_NAME`
- `AUDIT_TABLE_NAME`

### 8. aurora-restore-archive-snapshot

This function archives a snapshot after a successful restore.

```json
{
  "operation_id": "manual-test-op-123",
  "target_snapshot_name": "aurora-snapshot-your-target-cluster-2023-05-15",
  "target_region": "us-west-2"
}
```

**Required Environment Variables:**
- `TARGET_REGION`
- `ARCHIVE_SNAPSHOT`
- `STATE_TABLE_NAME`
- `AUDIT_TABLE_NAME`

### 9. aurora-restore-sns-notification

This function sends an SNS notification about the restore process completion.

```json
{
  "operation_id": "manual-test-op-123",
  "target_cluster_id": "your-target-cluster",
  "target_region": "us-west-2",
  "cluster_endpoint": "your-cluster.xxxxx.region.rds.amazonaws.com",
  "cluster_port": 5432,
  "target_snapshot_name": "aurora-snapshot-your-target-cluster-2023-05-15",
  "archive_status": "completed"
}
```

**Required Environment Variables:**
- `TARGET_REGION`
- `SNS_TOPIC_ARN`
- `STATE_TABLE_NAME`
- `AUDIT_TABLE_NAME`

## Testing the Complete Pipeline

To test the complete pipeline, you should run the functions in sequence:

1. First, run `aurora-restore-snapshot-check` with the appropriate arguments
2. After it completes successfully, run `aurora-restore-copy-snapshot`
3. Then run `aurora-restore-check-copy-status` until the copy is complete
4. Run `aurora-restore-delete-rds` to delete the existing target cluster
5. Run `aurora-restore-restore-snapshot` to restore from the snapshot
6. Run `aurora-restore-check-restore-status` until the restore is complete
7. Run `aurora-restore-setup-db-users` to set up database users
8. Run `aurora-restore-archive-snapshot` to archive the snapshot
9. Finally, run `aurora-restore-sns-notification` to send a notification

## Troubleshooting

If you encounter issues when running the functions:

1. **Check CloudWatch Logs**: Each Lambda function writes detailed logs to CloudWatch. Review these logs for error messages.

2. **Verify Environment Variables**: Ensure all required environment variables are set correctly.

3. **Check IAM Permissions**: Verify that the Lambda execution role has the necessary permissions.

4. **Validate Input Parameters**: Make sure the input parameters in your test event are valid.

5. **Check DynamoDB State**: The state table in DynamoDB contains information about the operation. You can query this table to understand the current state.

6. **Verify AWS Resources**: Ensure that all required AWS resources (RDS clusters, snapshots, etc.) exist and are accessible.

## Example: Running aurora-restore-snapshot-check

Here's a detailed example of how to run the `aurora-restore-snapshot-check` function:

1. Log in to the AWS Management Console
2. Navigate to the Lambda service
3. Select the `aurora-restore-snapshot-check` function
4. Click on the "Test" tab
5. Click "Create new event"
6. Enter a name for the test event (e.g., "TestSnapshotCheck")
7. Enter the following JSON in the "Event JSON" field:

```json
{
  "operation_id": "manual-test-op-123",
  "target_date": "2023-05-15",
  "source_cluster_id": "your-source-cluster",
  "source_region": "us-east-1"
}
```

8. Click "Save"
9. Click "Test" to run the function
10. Review the execution results and CloudWatch logs

Repeat similar steps for each function in the pipeline, adjusting the test event JSON as needed. 