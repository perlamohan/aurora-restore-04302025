#!/usr/bin/env python3
"""
Lambda function to restore an Aurora cluster from a snapshot.
"""

import json
import logging
from typing import Dict, Any, Optional, Tuple

from utils.base_handler import BaseHandler
from utils.aws_utils import get_rds_client, wait_for_cluster_available
from utils.config_utils import ConfigManager, ConfigValidator
from utils.state_utils import StateManager, RestoreState

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class RestoreSnapshotHandler(BaseHandler):
    """Handler for restoring Aurora clusters from snapshots."""
    
    def __init__(self):
        """Initialize the restore snapshot handler."""
        super().__init__('restore_snapshot')
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
        errors = ConfigValidator.validate_function_config(config.__dict__, 'aurora-restore-restore-snapshot')
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
            'target_snapshot_name': event.get('target_snapshot_name'),
            'target_snapshot_arn': event.get('target_snapshot_arn')
        }
        
        missing_params = [k for k, v in required_params.items() if not v]
        if missing_params:
            raise ValueError(f"Missing required snapshot parameters: {', '.join(missing_params)}")
        
        # Validate snapshot name format
        snapshot_name = event['target_snapshot_name']
        if not all(c.isalnum() or c == '-' for c in snapshot_name) or len(snapshot_name) > 63:
            raise ValueError(f"Invalid target snapshot name: {snapshot_name}")
    
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
    
    def check_snapshot_exists(self, snapshot_arn: str) -> Dict[str, Any]:
        """
        Check if the snapshot exists and get its details.
        
        Args:
            snapshot_arn: ARN of the snapshot to check
            
        Returns:
            Dict[str, Any]: Snapshot details
            
        Raises:
            Exception: If snapshot check fails
        """
        try:
            response = self.rds_client.describe_db_cluster_snapshots(
                DBClusterSnapshotIdentifier=snapshot_arn
            )
            
            if not response['DBClusterSnapshots']:
                raise ValueError(f"Snapshot {snapshot_arn} not found")
            
            return response['DBClusterSnapshots'][0]
        except Exception as e:
            logger.error(f"Error checking if snapshot {snapshot_arn} exists: {str(e)}")
            raise
    
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
    
    def restore_from_snapshot(self, snapshot_arn: str, cluster_id: str) -> Dict[str, Any]:
        """
        Restore an Aurora cluster from a snapshot.
        
        Args:
            snapshot_arn: ARN of the snapshot to restore from
            cluster_id: ID for the restored cluster
            
        Returns:
            Dict[str, Any]: Restore response
            
        Raises:
            Exception: If restore fails
        """
        try:
            config = self.config_manager.get_all()
            
            # Prepare restore parameters
            restore_params = {
                'DBClusterIdentifier': cluster_id,
                'DBClusterSnapshotIdentifier': snapshot_arn,
                'DBSubnetGroupName': config.db_subnet_group_name,
                'VpcSecurityGroupIds': config.vpc_security_group_ids,
                'Engine': 'aurora-postgresql',  # Default to Aurora PostgreSQL
                'EngineVersion': config.get('target_engine_version', '13.7'),
                'Port': config.get('target_port', 5432),
                'EnableIAMDatabaseAuthentication': True,
                'EnableCloudwatchLogsExports': ['postgresql', 'upgrade']
            }
            
            # Add KMS key if available
            if config.kms_key_id:
                restore_params['KmsKeyId'] = config.kms_key_id
            
            # Add backup retention period if available
            if config.get('target_backup_retention_period'):
                restore_params['BackupRetentionPeriod'] = int(config['target_backup_retention_period'])
            
            # Add parameter group if available
            if config.get('target_parameter_group'):
                restore_params['DBClusterParameterGroupName'] = config['target_parameter_group']
            
            # Restore the cluster
            response = self.rds_client.restore_db_cluster_from_snapshot(**restore_params)
            
            return response['DBCluster']
        except Exception as e:
            logger.error(f"Error restoring cluster {cluster_id} from snapshot {snapshot_arn}: {str(e)}")
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
            
            # Initialize RDS client
            self.initialize_rds_client()
            
            # Get snapshot and cluster details
            snapshot_arn = event['target_snapshot_arn']
            cluster_id = self.config_manager.get_all().target_cluster_id
            
            # Check if snapshot exists
            snapshot_details = self.check_snapshot_exists(snapshot_arn)
            
            # Check if cluster already exists
            cluster_exists = self.check_cluster_exists(cluster_id)
            
            if cluster_exists:
                # Cluster already exists, cannot restore
                error_message = f"Cluster {cluster_id} already exists, cannot restore from snapshot"
                logger.error(error_message)
                
                # Save state with error
                state_data = {
                    'target_cluster_id': cluster_id,
                    'target_snapshot_name': event['target_snapshot_name'],
                    'target_snapshot_arn': snapshot_arn,
                    'cluster_exists': True,
                    'restore_status': 'failed',
                    'status': 'failed',
                    'success': False,
                    'error': error_message
                }
                
                # Save state using StateManager
                self.state_manager.save_state(operation_id, 'restore_snapshot', state_data)
                
                # Log audit event
                self.state_manager.log_audit_event(
                    operation_id,
                    'restore_snapshot',
                    'FAILED',
                    {
                        'target_cluster_id': cluster_id,
                        'target_snapshot_name': event['target_snapshot_name'],
                        'error': error_message
                    }
                )
                
                # Update metrics
                self.state_manager.update_metrics(operation_id, 'restore_snapshot', 'restore_failure', 1)
                
                return self.create_response(operation_id, {
                    'message': error_message,
                    'target_cluster_id': cluster_id,
                    'target_snapshot_name': event['target_snapshot_name'],
                    'next_step': None
                })
            
            # Restore the cluster
            cluster = self.restore_from_snapshot(snapshot_arn, cluster_id)
            
            # Wait for cluster to become available
            wait_for_cluster_available(cluster_id, self.config_manager.get_all().target_region)
            
            # Save state
            state_data = {
                'target_cluster_id': cluster_id,
                'target_snapshot_name': event['target_snapshot_name'],
                'target_snapshot_arn': snapshot_arn,
                'cluster_arn': cluster['DBClusterArn'],
                'cluster_status': cluster['Status'],
                'cluster_endpoint': cluster.get('Endpoint'),
                'cluster_port': cluster.get('Port'),
                'cluster_engine': cluster['Engine'],
                'cluster_engine_version': cluster['EngineVersion'],
                'cluster_parameter_group': cluster.get('DBClusterParameterGroup'),
                'cluster_subnet_group': cluster['DBSubnetGroup'],
                'cluster_security_groups': cluster.get('VpcSecurityGroups', []),
                'cluster_iam_auth_enabled': cluster.get('IAMDatabaseAuthenticationEnabled', False),
                'cluster_log_exports': cluster.get('EnabledCloudwatchLogsExports', []),
                'restore_status': 'success',
                'status': 'success',
                'success': True
            }
            
            # Save state using StateManager
            self.state_manager.save_state(operation_id, 'restore_snapshot', state_data)
            
            # Log audit event
            self.state_manager.log_audit_event(
                operation_id,
                'restore_snapshot',
                'SUCCESS',
                {
                    'target_cluster_id': cluster_id,
                    'target_snapshot_name': event['target_snapshot_name'],
                    'cluster_arn': cluster['DBClusterArn']
                }
            )
            
            # Update metrics
            self.state_manager.update_metrics(operation_id, 'restore_snapshot', 'restore_success', 1)
            
            # Update state and trigger next step
            self.state_manager.update_state(operation_id, RestoreState.VERIFY_RESTORE, state_data)
            
            return self.create_response(operation_id, {
                'message': f"Cluster {cluster_id} restored successfully from snapshot {event['target_snapshot_name']}",
                'target_cluster_id': cluster_id,
                'target_snapshot_name': event['target_snapshot_name'],
                'cluster_arn': cluster['DBClusterArn'],
                'next_step': 'verify_restore'
            })
            
        except Exception as e:
            return self.handle_error(operation_id, e, {
                'target_cluster_id': self.config_manager.get_all().target_cluster_id if hasattr(self, 'config_manager') else None,
                'target_snapshot_name': event.get('target_snapshot_name'),
                'target_snapshot_arn': event.get('target_snapshot_arn')
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
    handler = RestoreSnapshotHandler()
    return handler.execute(event, context) 