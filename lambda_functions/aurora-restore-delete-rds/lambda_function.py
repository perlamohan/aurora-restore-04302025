#!/usr/bin/env python3
"""
Lambda function to delete an existing RDS cluster.
"""

import json
import time
from typing import Dict, Any, Optional, Tuple

from utils.base_handler import BaseHandler
from utils.aws_utils import get_rds_client, wait_for_cluster_available
from utils.config_utils import ConfigManager, ConfigValidator
from utils.state_utils import StateManager, RestoreState

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class DeleteRdsHandler(BaseHandler):
    """Handler for deleting RDS clusters."""
    
    def __init__(self):
        """Initialize the delete RDS handler."""
        super().__init__('delete_rds')
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
        errors = ConfigValidator.validate_function_config(config.__dict__, 'aurora-restore-delete-rds')
        if errors:
            raise ValueError(f"Configuration validation errors: {', '.join(errors)}")
    
    def initialize_rds_client(self) -> None:
        """
        Initialize RDS client for target region.
        
        Raises:
            ValueError: If target region is not set
        """
        config = self.config_manager.get_all()
        if not config.target_region:
            raise ValueError("Target region is required")
        
        self.rds_client = get_rds_client(config.target_region)
    
    def check_cluster_exists(self, cluster_id: str) -> bool:
        """
        Check if the RDS cluster exists.
        
        Args:
            cluster_id: ID of the cluster to check
            
        Returns:
            bool: True if cluster exists, False otherwise
            
        Raises:
            Exception: If check fails
        """
        try:
            response = self.rds_client.describe_db_clusters(
                DBClusterIdentifier=cluster_id
            )
            
            return len(response['DBClusters']) > 0
        except Exception as e:
            if 'DBClusterNotFoundFault' in str(e):
                return False
            
            logger.error(f"Error checking if cluster {cluster_id} exists: {str(e)}")
            raise
    
    def delete_cluster(self, cluster_id: str) -> Dict[str, Any]:
        """
        Delete an RDS cluster.
        
        Args:
            cluster_id: ID of the cluster to delete
            
        Returns:
            Dict[str, Any]: Delete response
            
        Raises:
            Exception: If deletion fails
        """
        try:
            # First, get the cluster details to check if it's in a deletable state
            response = self.rds_client.describe_db_clusters(
                DBClusterIdentifier=cluster_id
            )
            
            if not response['DBClusters']:
                raise ValueError(f"Cluster {cluster_id} not found")
            
            cluster = response['DBClusters'][0]
            
            # Check if cluster is in a deletable state
            if cluster['Status'] not in ['available', 'stopped', 'failed']:
                raise ValueError(f"Cluster {cluster_id} is in state {cluster['Status']}, cannot delete")
            
            # Delete the cluster
            delete_response = self.rds_client.delete_db_cluster(
                DBClusterIdentifier=cluster_id,
                SkipFinalSnapshot=True  # Skip final snapshot to speed up deletion
            )
            
            return delete_response['DBCluster']
        except Exception as e:
            logger.error(f"Error deleting cluster {cluster_id}: {str(e)}")
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
            
            # Initialize RDS client
            self.initialize_rds_client()
            
            # Get cluster ID
            config = self.config_manager.get_all()
            cluster_id = config.target_cluster_id
            
            # Check if cluster exists
            cluster_exists = self.check_cluster_exists(cluster_id)
            
            if not cluster_exists:
                # Cluster doesn't exist, no need to delete
                logger.info(f"Cluster {cluster_id} does not exist, no need to delete")
                
                # Save state
                state_data = {
                    'target_cluster_id': cluster_id,
                    'cluster_exists': False,
                    'delete_status': 'skipped',
                    'status': 'completed',
                    'success': True
                }
                
                # Save state using StateManager
                self.state_manager.save_state(operation_id, 'delete_rds', state_data)
                
                # Log audit event
                self.state_manager.log_audit_event(
                    operation_id,
                    'delete_rds',
                    'SUCCESS',
                    {
                        'target_cluster_id': cluster_id,
                        'message': 'Cluster does not exist, no need to delete'
                    }
                )
                
                # Update metrics
                self.state_manager.update_metrics(operation_id, 'delete_rds', 'cluster_not_found', 1)
                
                # Update state and trigger next step
                self.state_manager.update_state(operation_id, RestoreState.RESTORE_SNAPSHOT, state_data)
                
                return self.create_response(operation_id, {
                    'message': f"Cluster {cluster_id} does not exist, no need to delete",
                    'target_cluster_id': cluster_id,
                    'next_step': 'restore_snapshot'
                })
            
            # Delete the cluster
            delete_response = self.delete_cluster(cluster_id)
            
            # Save state
            state_data = {
                'target_cluster_id': cluster_id,
                'cluster_exists': True,
                'delete_status': delete_response['Status'],
                'status': 'deleting',
                'success': True
            }
            
            # Save state using StateManager
            self.state_manager.save_state(operation_id, 'delete_rds', state_data)
            
            # Log audit event
            self.state_manager.log_audit_event(
                operation_id,
                'delete_rds',
                'SUCCESS',
                {
                    'target_cluster_id': cluster_id,
                    'delete_status': delete_response['Status']
                }
            )
            
            # Update metrics
            self.state_manager.update_metrics(operation_id, 'delete_rds', 'cluster_deleted', 1)
            
            # Update state and trigger next step
            self.state_manager.update_state(operation_id, RestoreState.RESTORE_SNAPSHOT, state_data)
            
            return self.create_response(operation_id, {
                'message': f"Cluster {cluster_id} deletion initiated",
                'target_cluster_id': cluster_id,
                'delete_status': delete_response['Status'],
                'next_step': 'restore_snapshot'
            })
            
        except Exception as e:
            return self.handle_error(operation_id, e, {
                'target_cluster_id': self.config_manager.get_all().target_cluster_id if hasattr(self, 'config_manager') else None
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
    handler = DeleteRdsHandler()
    return handler.execute(event, context) 