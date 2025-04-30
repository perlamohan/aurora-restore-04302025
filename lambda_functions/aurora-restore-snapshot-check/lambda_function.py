#!/usr/bin/env python3
"""
Lambda function to check if the daily snapshot exists in the source account.
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Tuple

from utils.base_handler import BaseHandler
from utils.aws_utils import get_rds_client
from utils.config_utils import ConfigManager, ConfigValidator
from utils.state_utils import StateManager, RestoreState

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
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
        Validate configuration.
        
        Raises:
            ValueError: If configuration is invalid
        """
        config = self.config_manager.get_all()
        if not ConfigValidator.validate_and_log(config.__dict__, 'aurora-restore-snapshot-check'):
            raise ValueError("Configuration validation failed. Check logs for details.")
    
    def get_target_date(self, event: Dict[str, Any]) -> datetime.date:
        """
        Get target date from event.
        
        Args:
            event: Lambda event
            
        Returns:
            datetime.date: Target date
        """
        if 'target_date' in event:
            try:
                return datetime.strptime(event['target_date'], '%Y-%m-%d').date()
            except ValueError:
                logger.warning(f"Invalid target_date format: {event['target_date']}, using yesterday")
        
        # Default to yesterday
        return (datetime.now() - timedelta(days=1)).date()
    
    def get_snapshot_name(self, target_date: datetime.date) -> str:
        """
        Generate snapshot name.
        
        Args:
            target_date: Target date
            
        Returns:
            str: Snapshot name
        """
        config = self.config_manager.get_all()
        return f"{config.snapshot_prefix}-{target_date.strftime('%Y%m%d')}"
    
    def initialize_rds_client(self) -> None:
        """
        Initialize RDS client.
        
        Raises:
            Exception: If client initialization fails
        """
        if not self.rds_client:
            config = self.config_manager.get_all()
            self.rds_client = get_rds_client(config.source_region)
    
    def check_snapshot(self, snapshot_name: str) -> Tuple[bool, Optional[Dict]]:
        """
        Check if snapshot exists.
        
        Args:
            snapshot_name: Snapshot name
            
        Returns:
            Tuple[bool, Optional[Dict]]: (exists, snapshot details)
        """
        self.initialize_rds_client()
        
        try:
            response = self.rds_client.describe_db_cluster_snapshots(
                DBClusterIdentifier=self.config_manager.get_all().source_cluster_id,
                SnapshotType='automated'
            )
            
            for snapshot in response.get('DBClusterSnapshots', []):
                if snapshot['DBClusterSnapshotIdentifier'] == snapshot_name:
                    return True, snapshot
            
            return False, None
        except Exception as e:
            logger.error(f"Error checking snapshot: {str(e)}")
            raise
    
    def process(self, event: Dict[str, Any], context: Any) -> Dict[str, Any]:
        """
        Process the event.
        
        Args:
            event: Lambda event
            context: Lambda context
            
        Returns:
            Dict[str, Any]: Response
        """
        operation_id = self.get_operation_id(event)
        
        try:
            # Load and validate configuration
            self.config_manager.load_config(event)
            self.validate_config()
            
            # Get target date
            target_date = self.get_target_date(event)
            logger.info(f"Checking for snapshot on {target_date}")
            
            # Generate snapshot name
            snapshot_name = self.get_snapshot_name(target_date)
            logger.info(f"Looking for snapshot: {snapshot_name}")
            
            # Check if snapshot exists
            exists, snapshot_details = self.check_snapshot(snapshot_name)
            
            if exists:
                logger.info(f"Snapshot found: {snapshot_name}")
                
                # Update state
                self.state_manager.update_state(
                    operation_id,
                    RestoreState.SNAPSHOT_CHECK,
                    {
                        'snapshot_name': snapshot_name,
                        'snapshot_arn': snapshot_details['DBClusterSnapshotArn'],
                        'snapshot_status': snapshot_details['Status'],
                        'snapshot_type': snapshot_details['SnapshotType'],
                        'snapshot_created_at': snapshot_details['SnapshotCreateTime'].isoformat()
                    }
                )
                
                # Log audit event
                self.state_manager.log_audit_event(
                    operation_id,
                    self.step_name,
                    'SUCCESS',
                    {
                        'snapshot_name': snapshot_name,
                        'snapshot_arn': snapshot_details['DBClusterSnapshotArn'],
                        'snapshot_status': snapshot_details['Status']
                    }
                )
                
                # Update metrics
                self.state_manager.update_metrics(
                    operation_id,
                    self.step_name,
                    'snapshot_found'
                )
                
                return self.create_response(
                    operation_id,
                    {
                        'snapshot_exists': True,
                        'snapshot_name': snapshot_name,
                        'snapshot_arn': snapshot_details['DBClusterSnapshotArn'],
                        'snapshot_status': snapshot_details['Status'],
                        'snapshot_type': snapshot_details['SnapshotType'],
                        'snapshot_created_at': snapshot_details['SnapshotCreateTime'].isoformat()
                    }
                )
            else:
                logger.warning(f"Snapshot not found: {snapshot_name}")
                
                # Update state
                self.state_manager.update_state(
                    operation_id,
                    RestoreState.FAILED,
                    {
                        'error': f"Snapshot not found: {snapshot_name}",
                        'snapshot_name': snapshot_name
                    }
                )
                
                # Log audit event
                self.state_manager.log_audit_event(
                    operation_id,
                    self.step_name,
                    'FAILED',
                    {
                        'error': f"Snapshot not found: {snapshot_name}",
                        'snapshot_name': snapshot_name
                    }
                )
                
                # Update metrics
                self.state_manager.update_metrics(
                    operation_id,
                    self.step_name,
                    'snapshot_not_found'
                )
                
                return self.create_response(
                    operation_id,
                    {
                        'snapshot_exists': False,
                        'snapshot_name': snapshot_name,
                        'error': f"Snapshot not found: {snapshot_name}"
                    },
                    404
                )
        except Exception as e:
            return self.handle_error(operation_id, e, {'event': event})

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler.
    
    Args:
        event: Lambda event
        context: Lambda context
        
    Returns:
        Dict[str, Any]: Response
    """
    handler = SnapshotCheckHandler()
    return handler.execute(event, context) 