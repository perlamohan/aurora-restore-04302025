#!/usr/bin/env python3
"""
Consolidated AWS utilities for Aurora restore operations.
Provides common AWS service interactions and helper functions.
"""

import boto3
import json
from typing import Dict, Any, Optional
from botocore.exceptions import ClientError

def get_ssm_parameter(name: str, default: str = '') -> str:
    """
    Get parameter from SSM Parameter Store.
    
    Args:
        name: Parameter name
        default: Default value if parameter not found
        
    Returns:
        str: Parameter value
    """
    ssm = boto3.client('ssm')
    try:
        response = ssm.get_parameter(Name=name, WithDecryption=True)
        return response['Parameter']['Value']
    except ClientError as e:
        if e.response['Error']['Code'] == 'ParameterNotFound':
            return default
        raise

def get_rds_client(region: str) -> Any:
    """
    Get RDS client for specified region.
    
    Args:
        region: AWS region
        
    Returns:
        boto3.client: RDS client
    """
    return boto3.client('rds', region_name=region)

def wait_for_cluster_available(cluster_id: str, region: str) -> None:
    """
    Wait for cluster to become available.
    
    Args:
        cluster_id: Cluster identifier
        region: AWS region
    """
    rds = get_rds_client(region)
    waiter = rds.get_waiter('db_cluster_available')
    waiter.wait(DBClusterIdentifier=cluster_id)

def wait_for_cluster_deleted(cluster_id: str, region: str) -> None:
    """
    Wait for cluster to be deleted.
    
    Args:
        cluster_id: Cluster identifier
        region: AWS region
    """
    rds = get_rds_client(region)
    waiter = rds.get_waiter('db_cluster_deleted')
    waiter.wait(DBClusterIdentifier=cluster_id)

def get_secret(secret_id: str) -> Dict[str, Any]:
    """
    Get secret from Secrets Manager.
    
    Args:
        secret_id: Secret identifier
        
    Returns:
        dict: Secret value
    """
    secrets = boto3.client('secretsmanager')
    try:
        response = secrets.get_secret_value(SecretId=secret_id)
        return json.loads(response['SecretString'])
    except ClientError as e:
        raise Exception(f"Failed to get secret {secret_id}: {str(e)}")

def publish_sns_message(topic_arn: str, message: str, subject: Optional[str] = None) -> None:
    """
    Publish message to SNS topic.
    
    Args:
        topic_arn: SNS topic ARN
        message: Message to publish
        subject: Optional message subject
    """
    sns = boto3.client('sns')
    try:
        params = {
            'TopicArn': topic_arn,
            'Message': message
        }
        if subject:
            params['Subject'] = subject
        sns.publish(**params)
    except ClientError as e:
        raise Exception(f"Failed to publish SNS message: {str(e)}")

def get_s3_client(region: str) -> Any:
    """
    Get S3 client for specified region.
    
    Args:
        region: AWS region
        
    Returns:
        boto3.client: S3 client
    """
    return boto3.client('s3', region_name=region)

def get_dynamodb_client(region: str) -> Any:
    """
    Get DynamoDB client for specified region.
    
    Args:
        region: AWS region
        
    Returns:
        boto3.client: DynamoDB client
    """
    return boto3.client('dynamodb', region_name=region) 