#!/usr/bin/env python3
"""
State management utilities for Aurora restore operations.
Provides state tracking, audit logging, and metrics for Lambda functions.
"""

import json
import logging
import time
import uuid
from enum import Enum
from typing import Dict, Any, Optional, List

import boto3
from botocore.exceptions import ClientError

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class RestoreState(Enum):
    """Enum for Aurora restore operation states."""
    INITIALIZED = "initialized"
    SNAPSHOT_CHECK = "snapshot_check"
    COPY_SNAPSHOT = "copy_snapshot"
    CHECK_COPY_STATUS = "check_copy_status"
    DELETE_RDS = "delete_rds"
    RESTORE_SNAPSHOT = "restore_snapshot"
    CHECK_RESTORE_STATUS = "check_restore_status"
    SETUP_DB_USERS = "setup_db_users"
    ARCHIVE_SNAPSHOT = "archive_snapshot"
    COMPLETED = "completed"
    FAILED = "failed"

class StateManager:
    """Manager for state tracking, audit logging, and metrics."""
    
    def __init__(self, region: str):
        """
        Initialize the state manager.
        
        Args:
            region: AWS region
        """
        self.region = region
        self.dynamodb = boto3.client('dynamodb', region_name=region)
        self.state_table_name = None
        self.audit_table_name = None
        self.metrics_table_name = None
    
    def _get_table_name(self, table_type: str) -> str:
        """
        Get the DynamoDB table name for a specific table type.
        
        Args:
            table_type: Type of table (state, audit, metrics)
            
        Returns:
            str: Table name
        """
        if table_type == 'state':
            if not self.state_table_name:
                self.state_table_name = f"aurora-restore-state-{self.region}"
            return self.state_table_name
        elif table_type == 'audit':
            if not self.audit_table_name:
                self.audit_table_name = f"aurora-restore-audit-{self.region}"
            return self.audit_table_name
        elif table_type == 'metrics':
            if not self.metrics_table_name:
                self.metrics_table_name = f"aurora-restore-metrics-{self.region}"
            return self.metrics_table_name
        else:
            raise ValueError(f"Invalid table type: {table_type}")
    
    def save_state(self, operation_id: str, step: str, state_data: Dict[str, Any]) -> None:
        """
        Save state data to DynamoDB.
        
        Args:
            operation_id: Operation ID
            step: Step name
            state_data: State data to save
        """
        table_name = self._get_table_name('state')
        
        # Add metadata
        state_data['operation_id'] = operation_id
        state_data['step'] = step
        state_data['timestamp'] = int(time.time())
        
        # Convert to DynamoDB format
        dynamo_data = {}
        for key, value in state_data.items():
            if isinstance(value, bool):
                dynamo_data[key] = {'BOOL': value}
            elif isinstance(value, int):
                dynamo_data[key] = {'N': str(value)}
            elif isinstance(value, str):
                dynamo_data[key] = {'S': value}
            elif isinstance(value, dict):
                dynamo_data[key] = {'M': self._dict_to_dynamo(value)}
            elif isinstance(value, list):
                dynamo_data[key] = {'L': self._list_to_dynamo(value)}
            elif value is None:
                dynamo_data[key] = {'NULL': True}
        
        try:
            self.dynamodb.put_item(
                TableName=table_name,
                Item=dynamo_data
            )
            logger.info(f"Saved state for operation {operation_id}, step {step}")
        except ClientError as e:
            logger.error(f"Error saving state: {str(e)}")
            raise
    
    def get_state(self, operation_id: str) -> Optional[Dict[str, Any]]:
        """
        Get state data from DynamoDB.
        
        Args:
            operation_id: Operation ID
            
        Returns:
            Optional[Dict[str, Any]]: State data, or None if not found
        """
        table_name = self._get_table_name('state')
        
        try:
            response = self.dynamodb.get_item(
                TableName=table_name,
                Key={'operation_id': {'S': operation_id}}
            )
            
            if 'Item' not in response:
                return None
            
            # Convert from DynamoDB format
            return self._dynamo_to_dict(response['Item'])
        except ClientError as e:
            logger.error(f"Error getting state: {str(e)}")
            raise
    
    def update_state(self, operation_id: str, state: RestoreState, state_data: Dict[str, Any]) -> None:
        """
        Update state and trigger next step.
        
        Args:
            operation_id: Operation ID
            state: New state
            state_data: State data to save
        """
        # Save state
        self.save_state(operation_id, state.value, state_data)
        
        # Trigger next step based on state
        if state == RestoreState.COPY_SNAPSHOT:
            self._trigger_lambda('aurora-restore-copy-snapshot', operation_id, state_data)
        elif state == RestoreState.DELETE_RDS:
            self._trigger_lambda('aurora-restore-delete-rds', operation_id, state_data)
        elif state == RestoreState.RESTORE_SNAPSHOT:
            self._trigger_lambda('aurora-restore-restore-snapshot', operation_id, state_data)
        elif state == RestoreState.SETUP_DB_USERS:
            self._trigger_lambda('aurora-restore-setup-db-users', operation_id, state_data)
        elif state == RestoreState.ARCHIVE_SNAPSHOT:
            self._trigger_lambda('aurora-restore-archive-snapshot', operation_id, state_data)
        elif state == RestoreState.COMPLETED or state == RestoreState.FAILED:
            self._trigger_lambda('aurora-restore-sns-notification', operation_id, state_data)
    
    def log_audit_event(self, operation_id: str, step: str, status: str, details: Dict[str, Any]) -> None:
        """
        Log an audit event to DynamoDB.
        
        Args:
            operation_id: Operation ID
            step: Step name
            status: Event status (SUCCESS, ERROR, etc.)
            details: Event details
        """
        table_name = self._get_table_name('audit')
        
        # Add metadata
        audit_data = {
            'operation_id': operation_id,
            'step': step,
            'status': status,
            'timestamp': int(time.time()),
            'details': details
        }
        
        # Convert to DynamoDB format
        dynamo_data = {}
        for key, value in audit_data.items():
            if isinstance(value, bool):
                dynamo_data[key] = {'BOOL': value}
            elif isinstance(value, int):
                dynamo_data[key] = {'N': str(value)}
            elif isinstance(value, str):
                dynamo_data[key] = {'S': value}
            elif isinstance(value, dict):
                dynamo_data[key] = {'M': self._dict_to_dynamo(value)}
            elif isinstance(value, list):
                dynamo_data[key] = {'L': self._list_to_dynamo(value)}
            elif value is None:
                dynamo_data[key] = {'NULL': True}
        
        try:
            self.dynamodb.put_item(
                TableName=table_name,
                Item=dynamo_data
            )
            logger.info(f"Logged audit event for operation {operation_id}, step {step}, status {status}")
        except ClientError as e:
            logger.error(f"Error logging audit event: {str(e)}")
            raise
    
    def update_metrics(self, operation_id: str, step: str, metric_name: str, value: int = 1) -> None:
        """
        Update metrics in DynamoDB.
        
        Args:
            operation_id: Operation ID
            step: Step name
            metric_name: Metric name
            value: Metric value
        """
        table_name = self._get_table_name('metrics')
        
        # Add metadata
        metric_data = {
            'operation_id': operation_id,
            'step': step,
            'metric_name': metric_name,
            'value': value,
            'timestamp': int(time.time())
        }
        
        # Convert to DynamoDB format
        dynamo_data = {}
        for key, value in metric_data.items():
            if isinstance(value, bool):
                dynamo_data[key] = {'BOOL': value}
            elif isinstance(value, int):
                dynamo_data[key] = {'N': str(value)}
            elif isinstance(value, str):
                dynamo_data[key] = {'S': value}
            elif isinstance(value, dict):
                dynamo_data[key] = {'M': self._dict_to_dynamo(value)}
            elif isinstance(value, list):
                dynamo_data[key] = {'L': self._list_to_dynamo(value)}
            elif value is None:
                dynamo_data[key] = {'NULL': True}
        
        try:
            self.dynamodb.put_item(
                TableName=table_name,
                Item=dynamo_data
            )
            logger.info(f"Updated metrics for operation {operation_id}, step {step}, metric {metric_name}")
        except ClientError as e:
            logger.error(f"Error updating metrics: {str(e)}")
            raise
    
    def _trigger_lambda(self, function_name: str, operation_id: str, state_data: Dict[str, Any]) -> None:
        """
        Trigger a Lambda function.
        
        Args:
            function_name: Lambda function name
            operation_id: Operation ID
            state_data: State data to pass to the Lambda function
        """
        lambda_client = boto3.client('lambda', region_name=self.region)
        
        # Prepare payload
        payload = {
            'operation_id': operation_id,
            'state': state_data
        }
        
        try:
            lambda_client.invoke(
                FunctionName=function_name,
                InvocationType='Event',
                Payload=json.dumps(payload)
            )
            logger.info(f"Triggered Lambda function {function_name} for operation {operation_id}")
        except ClientError as e:
            logger.error(f"Error triggering Lambda function {function_name}: {str(e)}")
            raise
    
    def _dict_to_dynamo(self, d: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert a dictionary to DynamoDB format.
        
        Args:
            d: Dictionary to convert
            
        Returns:
            Dict[str, Any]: DynamoDB-formatted dictionary
        """
        result = {}
        for key, value in d.items():
            if isinstance(value, bool):
                result[key] = {'BOOL': value}
            elif isinstance(value, int):
                result[key] = {'N': str(value)}
            elif isinstance(value, str):
                result[key] = {'S': value}
            elif isinstance(value, dict):
                result[key] = {'M': self._dict_to_dynamo(value)}
            elif isinstance(value, list):
                result[key] = {'L': self._list_to_dynamo(value)}
            elif value is None:
                result[key] = {'NULL': True}
        return result
    
    def _list_to_dynamo(self, l: List[Any]) -> List[Any]:
        """
        Convert a list to DynamoDB format.
        
        Args:
            l: List to convert
            
        Returns:
            List[Any]: DynamoDB-formatted list
        """
        result = []
        for item in l:
            if isinstance(item, bool):
                result.append({'BOOL': item})
            elif isinstance(item, int):
                result.append({'N': str(item)})
            elif isinstance(item, str):
                result.append({'S': item})
            elif isinstance(item, dict):
                result.append({'M': self._dict_to_dynamo(item)})
            elif isinstance(item, list):
                result.append({'L': self._list_to_dynamo(item)})
            elif item is None:
                result.append({'NULL': True})
        return result
    
    def _dynamo_to_dict(self, d: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert a DynamoDB-formatted dictionary to a regular dictionary.
        
        Args:
            d: DynamoDB-formatted dictionary
            
        Returns:
            Dict[str, Any]: Regular dictionary
        """
        result = {}
        for key, value in d.items():
            if 'S' in value:
                result[key] = value['S']
            elif 'N' in value:
                result[key] = int(value['N'])
            elif 'BOOL' in value:
                result[key] = value['BOOL']
            elif 'M' in value:
                result[key] = self._dynamo_to_dict(value['M'])
            elif 'L' in value:
                result[key] = self._dynamo_to_list(value['L'])
            elif 'NULL' in value:
                result[key] = None
        return result
    
    def _dynamo_to_list(self, l: List[Any]) -> List[Any]:
        """
        Convert a DynamoDB-formatted list to a regular list.
        
        Args:
            l: DynamoDB-formatted list
            
        Returns:
            List[Any]: Regular list
        """
        result = []
        for item in l:
            if 'S' in item:
                result.append(item['S'])
            elif 'N' in item:
                result.append(int(item['N']))
            elif 'BOOL' in item:
                result.append(item['BOOL'])
            elif 'M' in item:
                result.append(self._dynamo_to_dict(item['M']))
            elif 'L' in item:
                result.append(self._dynamo_to_list(item['L']))
            elif 'NULL' in item:
                result.append(None)
        return result 