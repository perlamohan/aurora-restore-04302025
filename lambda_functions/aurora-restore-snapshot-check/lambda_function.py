#!/usr/bin/env python3
"""
Lambda function to check if the daily snapshot exists in the source account.
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Tuple

from utils.base_handler import BaseHandler
from utils.aws_utils import get_rds_client, wait_for_cluster_available, wait_for_cluster_deleted
from utils.config_utils import ConfigManager, ConfigValidator
from utils.state_utils import StateManager, RestoreState

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class SnapshotCheckHandler(BaseHandler):
    """Handler for checking Aurora snapshots."""
    
    def __init__(self):
        """Initialize the snapshot check handler."""
        super().__init__('snapshot_check')
        self.config_manager = ConfigManager()
        self.state_manager = StateManager(self.config_manager.get_all().region)
        self.rds_client = None
    
    def validate_config(self) -> None:
        """
        Validate required configuration parameters.
        
        Raises:
            ValueError: If required parameters are missing or invalid
        """
        config = self.config_manager.get_all()
        
        # Validate configuration using the ConfigValidator
        errors = ConfigValidator.validate_function_config(config.__dict__, 'aurora-restore-snapshot-check')
        if errors:
            raise ValueError(f"Configuration validation errors: {', '.join(errors)}")
    
    def get_target_date(self, event: Dict[str, Any]) -> datetime.date:
        """
        Get target date from event or use yesterday.
        
        Args:
            event: Lambda event
            
        Returns:
            datetime.date: Target date
        """
        if event and isinstance(event, dict):
            if 'target_date' in event:
                try:
                    return datetime.strptime(event['target_date'], '%Y-%m-%d').date()
                except ValueError:
                    logger.warning(f"Invalid target_date format: {event['target_date']}, using yesterday")
            
            if 'body' in event and isinstance(event['body'], dict) and 'target_date' in event['body']:
                try:
                    return datetime.strptime(event['body']['target_date'], '%Y-%m-%d').date()
                except ValueError:
                    logger.warning(f"Invalid target_date format: {event['body']['target_date']}, using yesterday")
        
        # Default to yesterday
        return (datetime.now() - timedelta(days=1)).date()
    
    def get_snapshot_name(self, target_date: datetime.date) -> str:
        """
        Generate snapshot name based on target date.
        
        Args:
            target_date: Target date
            
        Returns:
            str: Snapshot name
        """
        config = self.config_manager.get_all()
        snapshot_prefix = config.snapshot_prefix
        cluster_id = config.source_cluster_id
        
        # Format: prefix-cluster-id-YYYY-MM-DD
        snapshot_name = f"{snapshot_prefix}-{cluster_id}-{target_date.strftime('%Y-%m-%d')}"
        
        # Validate snapshot name (must be alphanumeric or hyphen, 1-63 characters)
        if not all(c.isalnum() or c == '-' for c in snapshot_name) or len(snapshot_name) > 63:
            raise ValueError(f"Invalid snapshot name: {snapshot_name}")
        
        return snapshot_name
    
    def initialize_rds_client(self) -> None:
        """
        Initialize RDS client.
        
        Raises:
            ValueError: If source region is not set
        """
        config = self.config_manager.get_all()
        if not config.source_region:
            raise ValueError("Source region is required")
        
        self.rds_client = get_rds_client(config.source_region)
    
    def check_snapshot(self, snapshot_name: str) -> Tuple[bool, Optional[Dict]]:
        """
        Check if snapshot exists.
        
        Args:
            snapshot_name: Name of the snapshot to check
            
        Returns:
            Tuple[bool, Optional[Dict]]: (exists, snapshot_details)
        """
        try:
            response = self.rds_client.describe_db_cluster_snapshots(
                DBClusterSnapshotIdentifier=snapshot_name
            )
            
            if response['DBClusterSnapshots']:
                return True, response['DBClusterSnapshots'][0]
            return False, None
        except Exception as e:
            logger.error(f"Error checking snapshot {snapshot_name}: {str(e)}")
            return False, None
    
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
            
            # Get target date
            target_date = self.get_target_date(event)
            logger.info(f"Target date: {target_date}")
            
            # Generate snapshot name
            snapshot_name = self.get_snapshot_name(target_date)
            logger.info(f"Snapshot name: {snapshot_name}")
            
            # Initialize RDS client
            self.initialize_rds_client()
            
            # Check if snapshot exists
            snapshot_exists, snapshot_details = self.check_snapshot(snapshot_name)
            
            # Save state
            state_data = {
                'target_date': target_date.strftime('%Y-%m-%d'),
                'snapshot_name': snapshot_name,
                'snapshot_exists': snapshot_exists
            }
            
            if snapshot_details:
                state_data['snapshot_arn'] = snapshot_details.get('DBClusterSnapshotArn')
                state_data['snapshot_status'] = snapshot_details.get('Status')
                state_data['snapshot_type'] = snapshot_details.get('SnapshotType')
            
            # Save state using StateManager
            self.state_manager.save_state(operation_id, 'snapshot_check', state_data)
            
            # Log audit event
            self.state_manager.log_audit_event(
                operation_id, 
                'snapshot_check', 
                'SUCCESS', 
                {
                    'target_date': target_date.strftime('%Y-%m-%d'),
                    'snapshot_name': snapshot_name,
                    'snapshot_exists': snapshot_exists
                }
            )
            
            # Update metrics
            self.state_manager.update_metrics(operation_id, 'snapshot_check', 'snapshot_check', 1)
            if snapshot_exists:
                self.state_manager.update_metrics(operation_id, 'snapshot_check', 'snapshot_found', 1)
            else:
                self.state_manager.update_metrics(operation_id, 'snapshot_check', 'snapshot_not_found', 1)
            
            # Update state and trigger next step if snapshot exists
            if snapshot_exists:
                self.state_manager.update_state(operation_id, RestoreState.COPY_SNAPSHOT, state_data)
                return self.create_response(operation_id, {
                    'message': f"Snapshot {snapshot_name} exists, triggering copy",
                    'snapshot_name': snapshot_name,
                    'snapshot_arn': snapshot_details.get('DBClusterSnapshotArn'),
                    'next_step': 'copy_snapshot'
                })
            else:
                return self.create_response(operation_id, {
                    'message': f"Snapshot {snapshot_name} does not exist",
                    'snapshot_name': snapshot_name,
                    'next_step': None
                })
        except Exception as e:
            return self.handle_error(operation_id, e, {
                'target_date': target_date.strftime('%Y-%m-%d') if 'target_date' in locals() else None,
                'snapshot_name': snapshot_name if 'snapshot_name' in locals() else None
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
    handler = SnapshotCheckHandler()
    return handler.execute(event, context) 