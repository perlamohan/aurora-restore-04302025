# Configuration Sources in Aurora Restore Pipeline

This document explains the various sources of configuration used in the Aurora restore pipeline and how they are accessed by the Lambda functions.

## Configuration Hierarchy

The pipeline uses a hierarchical approach to configuration, with the following priority order:

1. **Event Data**: Configuration passed directly in the Lambda event
2. **State Data**: Configuration stored in DynamoDB state table
3. **Environment Variables**: Configuration set as Lambda environment variables
4. **SSM Parameter Store**: Configuration stored in AWS Systems Manager Parameter Store
5. **Default Values**: Hardcoded defaults in the code

## Configuration Sources

### 1. Environment Variables

Environment variables are the primary source of configuration for Lambda functions. These are set when creating or updating Lambda functions.

```python
# From utils/core.py
def get_config() -> Dict[str, Any]:
    """
    Get configuration from environment variables.
    
    Returns:
        dict: Configuration dictionary
    """
    return {
        'source_region': os.environ.get('SOURCE_REGION', ''),
        'target_region': os.environ.get('TARGET_REGION', ''),
        'source_cluster_id': os.environ.get('SOURCE_CLUSTER_ID', ''),
        'target_cluster_id': os.environ.get('TARGET_CLUSTER_ID', ''),
        'snapshot_prefix': os.environ.get('SNAPSHOT_PREFIX', 'aurora-snapshot'),
        'vpc_security_group_ids': os.environ.get('VPC_SECURITY_GROUP_IDS', ''),
        'db_subnet_group_name': os.environ.get('DB_SUBNET_GROUP_NAME', ''),
        'kms_key_id': os.environ.get('KMS_KEY_ID', ''),
        'master_credentials_secret_id': os.environ.get('MASTER_CREDENTIALS_SECRET_ID', ''),
        'app_credentials_secret_id': os.environ.get('APP_CREDENTIALS_SECRET_ID', ''),
        'copy_status_retry_delay': int(os.environ.get('COPY_STATUS_RETRY_DELAY', '60')),
        'restore_status_retry_delay': int(os.environ.get('RESTORE_STATUS_RETRY_DELAY', '60')),
        'delete_status_retry_delay': int(os.environ.get('DELETE_STATUS_RETRY_DELAY', '60')),
        'environment': ENVIRONMENT,
        'region': AWS_REGION,
        'account_id': AWS_ACCOUNT_ID
    }
```

### 2. SSM Parameter Store

The pipeline can retrieve additional configuration from AWS Systems Manager Parameter Store. This is used for environment-specific configuration that may change between environments.

```python
# From utils/common.py
def get_full_config() -> Dict[str, Any]:
    """
    Get configuration from environment variables and SSM Parameter Store.
    
    Returns:
        dict: Configuration dictionary
    """
    config = get_config()
    
    # Try to get additional config from SSM
    try:
        ssm_config = get_ssm_parameter(f'/aurora-restore/{config["environment"]}/config', '{}')
        config.update(json.loads(ssm_config))
    except Exception as e:
        logger.warning(f"Failed to load SSM config: {str(e)}")
    
    return config
```

The SSM parameter path follows the pattern: `/aurora-restore/{environment}/config`, where `{environment}` is the value of the `ENVIRONMENT` environment variable (defaults to 'dev').

### 3. DynamoDB State Table

The pipeline stores state information in a DynamoDB table, which includes configuration values that are passed between Lambda functions in the pipeline.

```python
# Example from lambda functions
def get_cluster_details(self, event: Dict[str, Any]) -> Tuple[str, str]:
    """
    Get cluster details from event or state.
    
    Args:
        event: Lambda event
        
    Returns:
        Tuple[str, str]: Target cluster ID and region
        
    Raises:
        ValueError: If cluster details are missing
    """
    state = self.load_state()
    
    target_cluster_id = (
        state.get('target_cluster_id') or 
        event.get('target_cluster_id') or 
        self.config.get('target_cluster_id')
    )
    
    target_region = (
        state.get('target_region') or 
        event.get('target_region') or 
        self.config.get('target_region')
    )
    
    if not target_cluster_id:
        raise ValueError("Target cluster ID is required")
    
    if not target_region:
        raise ValueError("Target region is required")
    
    return target_cluster_id, target_region
```

### 4. Lambda Event Data

Configuration can be passed directly in the Lambda event when invoking a function.

```python
# Example from lambda functions
def get_snapshot_details(self, event: Dict[str, Any]) -> str:
    """
    Get snapshot details from event or state.
    
    Args:
        event: Lambda event
        
    Returns:
        str: Target snapshot name
        
    Raises:
        ValueError: If snapshot details are missing
    """
    state = self.load_state()
    
    target_snapshot_name = (
        state.get('target_snapshot_name') or 
        event.get('target_snapshot_name') or 
        self.config.get('target_snapshot_name')
    )
    
    if not target_snapshot_name:
        raise ValueError("Target snapshot name is required")
    
    return target_snapshot_name
```

### 5. Default Values

If a configuration value is not found in any of the above sources, the code uses default values.

```python
# Example from utils/core.py
ENVIRONMENT = os.environ.get('ENVIRONMENT', 'dev')
AWS_REGION = os.environ.get('AWS_REGION', 'us-east-1')
AWS_ACCOUNT_ID = os.environ.get('AWS_ACCOUNT_ID', '')
```

## Configuration Flow

1. When a Lambda function is invoked, it first loads the base configuration from environment variables using `get_config()`.
2. It then attempts to load additional configuration from SSM Parameter Store using `get_full_config()`.
3. When processing an event, it checks for configuration in the event data.
4. If not found in the event, it checks the state data from DynamoDB.
5. If still not found, it uses the configuration loaded from environment variables and SSM.
6. If a required configuration value is not found in any source, the function raises a `ValueError`.

## Configuration Management

To manage configuration for the pipeline:

1. **Environment Variables**: Set these when creating or updating Lambda functions using the AWS CLI or console.
2. **SSM Parameters**: Store environment-specific configuration in SSM Parameter Store.
3. **State Data**: This is managed automatically by the pipeline as it progresses through steps.
4. **Event Data**: This is passed when invoking Lambda functions, typically by the previous step in the pipeline.

## Configuration File

The project includes a `config.json` file that serves as a template for configuration values:

```json
{
    "source_region": "us-east-1",
    "target_region": "us-west-2",
    "source_cluster_id": "your-source-cluster",
    "target_cluster_id": "your-target-cluster",
    "snapshot_prefix": "aurora-snapshot",
    "vpc_config": {
        "vpc_id": "vpc-xxxxxxxx",
        "subnet_ids": [
            "subnet-xxxxxxxx",
            "subnet-yyyyyyyy"
        ],
        "security_group_ids": [
            "sg-xxxxxxxx"
        ]
    },
    "restore_params": {
        "db_subnet_group_name": "your-db-subnet-group",
        "vpc_security_group_ids": [
            "sg-xxxxxxxx"
        ],
        "environment": "dev",
        "deletion_protection": false,
        "port": 5432,
        "availability_zones": [
            "us-west-2a",
            "us-west-2b"
        ],
        "enable_iam_database_authentication": true,
        "storage_encrypted": true
    },
    "master_credentials_secret_id": "aurora-restore-master-credentials",
    "app_credentials_secret_id": "aurora-restore-app-credentials",
    "sns_topic_arn": "arn:aws:sns:region:account:aurora-restore-notifications"
}
```

This file is used as a reference when setting up the pipeline and should be updated with your specific values before deployment. 