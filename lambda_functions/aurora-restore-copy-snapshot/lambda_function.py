#!/usr/bin/env python3
"""
Lambda function to copy a snapshot from source to target region.
"""

import json
import logging
from typing import Dict, Any, Optional, Tuple

from utils.base_handler import BaseHandler
from utils.aws_utils import get_rds_client, wait_for_cluster_available, wait_for_cluster_deleted
from utils.config_utils import ConfigManager, ConfigValidator
from utils.state_utils import StateManager, RestoreState

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class CopySnapshotHandler(BaseHandler):
    """Handler for copying Aurora snapshots between regions."""
    
    def __init__(self):
        """Initialize the copy snapshot handler."""
        super().__init__('copy_snapshot')
        self.config_manager = ConfigManager()
        self.state_manager = StateManager(self.config_manager.get_all().region)
        self.rds_client = None
        self.rds_client_target = None
    
    def validate_config(self) -> None:
        """
        Validate required configuration parameters.
        
        Raises:
            ValueError: If required parameters are missing or invalid
        """
        config = self.config_manager.get_all()
        
        # Validate configuration using the ConfigValidator
        errors = ConfigValidator.validate_function_config(config.__dict__, 'aurora-restore-copy-snapshot')
        if errors:
            raise ValueError(f"Configuration validation errors: {', '.join(errors)}")
    
    def validate_snapshot_params(self, event: Dict[str, Any]) -> None:
        """
        Validate snapshot parameters from event.
        
        Args:
            event: Lambda event
            
        Raises:
            ValueError: If required snapshot parameters are missing or invalid
        """
        required_params = {
            'snapshot_name': event.get('snapshot_name'),
            'snapshot_arn': event.get('snapshot_arn')
        }
        
        missing_params = [k for k, v in required_params.items() if not v]
        if missing_params:
            raise ValueError(f"Missing required snapshot parameters: {', '.join(missing_params)}")
        
        # Validate snapshot name format
        snapshot_name = event['snapshot_name']
        if not all(c.isalnum() or c == '-' for c in snapshot_name) or len(snapshot_name) > 63:
            raise ValueError(f"Invalid snapshot name: {snapshot_name}")
    
    def initialize_rds_clients(self) -> None:
        """
        Initialize RDS clients for source and target regions.
        
        Raises:
            ValueError: If regions are not set
        """
        config = self.config_manager.get_all()
        if not config.source_region or not config.target_region:
            raise ValueError("Source and target regions are required")
        
        self.rds_client = get_rds_client(config.source_region)
        self.rds_client_target = get_rds_client(config.target_region)
    
    def get_snapshot_details(self, snapshot_arn: str) -> Dict[str, Any]:
        """
        Get snapshot details from source region.
        
        Args:
            snapshot_arn: ARN of the snapshot
            
        Returns:
            Dict[str, Any]: Snapshot details
            
        Raises:
            Exception: If snapshot details cannot be retrieved
        """
        try:
            logger.info(f"Getting details for snapshot {snapshot_arn}")
            
            response = self.rds_client.describe_db_cluster_snapshots(
                DBClusterSnapshotIdentifier=snapshot_arn
            )
            
            if not response['DBClusterSnapshots']:
                raise ValueError(f"Snapshot {snapshot_arn} not found")
            
            snapshot = response['DBClusterSnapshots'][0]
            
            logger.info(f"Retrieved snapshot details", extra={
                'snapshot_arn': snapshot_arn,
                'status': snapshot['Status'],
                'engine': snapshot['Engine'],
                'engine_version': snapshot['EngineVersion']
            })
            
            return snapshot
            
        except Exception as e:
            logger.error(f"Error getting snapshot details for {snapshot_arn}: {str(e)}")
            raise
    
    def copy_snapshot(self, snapshot_arn: str, target_snapshot_name: str) -> Dict[str, Any]:
        """
        Copy snapshot to target region.
        
        Args:
            snapshot_arn: ARN of the source snapshot
            target_snapshot_name: Name for the target snapshot
            
        Returns:
            Dict[str, Any]: Copy snapshot response
            
        Raises:
            Exception: If snapshot copy fails
        """
        try:
            config = self.config_manager.get_all()
            
            logger.info(f"Copying snapshot {snapshot_arn} to {target_snapshot_name}")
            
            response = self.rds_client_target.copy_db_cluster_snapshot(
                SourceDBClusterSnapshotIdentifier=snapshot_arn,
                TargetDBClusterSnapshotIdentifier=target_snapshot_name,
                SourceRegion=config.source_region,
                KmsKeyId=config.kms_key_id
            )
            
            snapshot = response['DBClusterSnapshot']
            
            logger.info(f"Snapshot copy initiated", extra={
                'target_snapshot_arn': snapshot['DBClusterSnapshotArn'],
                'status': snapshot['Status']
            })
            
            return snapshot
            
        except Exception as e:
            logger.error(f"Error copying snapshot {snapshot_arn} to {target_snapshot_name}: {str(e)}")
            raise
    
    def wait_for_snapshot_copy(self, snapshot_arn: str) -> Dict[str, Any]:
        """
        Wait for a snapshot copy to complete.
        
        Args:
            snapshot_arn: ARN of the snapshot to wait for
            
        Returns:
            Dict[str, Any]: Snapshot details when copy is complete
            
        Raises:
            Exception: If snapshot copy fails or times out
        """
        try:
            config = self.config_manager.get_all()
            
            logger.info(f"Waiting for snapshot copy to complete: {snapshot_arn}")
            
            def check_snapshot():
                response = self.rds_client_target.describe_db_cluster_snapshots(
                    DBClusterSnapshotIdentifier=snapshot_arn
                )
                return response['DBClusterSnapshots'][0]
            
            # Use wait_for_cluster_available with custom check function
            snapshot = wait_for_cluster_available(
                cluster_id=snapshot_arn,
                region=config.target_region,
                check_func=check_snapshot
            )
            
            logger.info(f"Snapshot copy completed", extra={
                'snapshot_arn': snapshot_arn,
                'status': snapshot['Status']
            })
            
            return snapshot
            
        except Exception as e:
            logger.error(f"Error waiting for snapshot copy {snapshot_arn} to complete: {str(e)}")
            raise
    
    def process(self, event: Dict[str, Any], context: Any) -> Dict[str, Any]:
        """
        Process the Lambda event.
        
        Args:
            event: Lambda event
            context: Lambda context
            
        Returns:
            Dict[str, Any]: Lambda response
        """
        try:
            # Get operation ID
            operation_id = self.get_operation_id(event)
            
            # Load configuration
            self.config_manager.load_config(event)
            
            # Validate configuration
            self.validate_config()
            
            # Validate snapshot parameters
            self.validate_snapshot_params(event)
            
            # Initialize RDS clients
            self.initialize_rds_clients()
            
            # Get snapshot details
            snapshot_details = self.get_snapshot_details(event['snapshot_arn'])
            
            # Generate target snapshot name
            target_snapshot_name = f"{event['snapshot_name']}-copy"
            
            # Copy snapshot
            copy_response = self.copy_snapshot(event['snapshot_arn'], target_snapshot_name)
            
            # Wait for copy to complete
            final_snapshot = self.wait_for_snapshot_copy(copy_response['DBClusterSnapshotArn'])
            
            # Prepare state data
            state_data = {
                'source_snapshot_name': event['snapshot_name'],
                'source_snapshot_arn': event['snapshot_arn'],
                'target_snapshot_name': target_snapshot_name,
                'target_snapshot_arn': copy_response['DBClusterSnapshotArn'],
                'snapshot_status': final_snapshot['Status'],
                'engine': final_snapshot['Engine'],
                'engine_version': final_snapshot['EngineVersion']
            }
            
            # Save state
            self.state_manager.save_state(operation_id, 'copy_snapshot', state_data)
            
            # Log audit event
            self.state_manager.log_audit_event(
                operation_id,
                'copy_snapshot',
                'SUCCESS',
                state_data
            )
            
            # Update metrics
            self.state_manager.update_metrics(operation_id, 'copy_snapshot', 'snapshot_copy', 1)
            
            # Update state and trigger next step
            self.state_manager.update_state(operation_id, RestoreState.RESTORE_SNAPSHOT, state_data)
            
            return self.create_response(operation_id, {
                'message': f"Snapshot copy completed: {target_snapshot_name}",
                'source_snapshot_name': event['snapshot_name'],
                'target_snapshot_name': target_snapshot_name,
                'target_snapshot_arn': copy_response['DBClusterSnapshotArn'],
                'next_step': 'restore_snapshot'
            })
            
        except Exception as e:
            return self.handle_error(operation_id, e, {
                'source_snapshot_name': event.get('snapshot_name'),
                'source_snapshot_arn': event.get('snapshot_arn')
            })

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler function.
    
    Args:
        event: Lambda event
        context: Lambda context
        
    Returns:
        Dict[str, Any]: Lambda response
    """
    handler = CopySnapshotHandler()
    return handler.execute(event, context) 