#!/usr/bin/env python3
"""
Lambda function to set up database users after a cluster restore.
"""

import json
import logging
from typing import Dict, Any, Optional, Tuple, List

from utils.base_handler import BaseHandler
from utils.aws_utils import get_rds_client, get_secret
from utils.config_utils import ConfigManager, ConfigValidator
from utils.state_utils import StateManager, RestoreState

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class SetupDbUsersHandler(BaseHandler):
    """Handler for setting up database users."""
    
    def __init__(self):
        """Initialize the setup DB users handler."""
        super().__init__('setup_db_users')
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
        errors = ConfigValidator.validate_function_config(config.__dict__, 'aurora-restore-setup-db-users')
        if errors:
            raise ValueError(f"Configuration validation errors: {', '.join(errors)}")
    
    def initialize_clients(self) -> None:
        """
        Initialize AWS clients.
        
        Raises:
            ValueError: If required parameters are missing
        """
        config = self.config_manager.get_all()
        if not config.target_region:
            raise ValueError("Target region is required")
        
        self.rds_client = get_rds_client(config.target_region)
    
    def get_cluster_endpoint(self, cluster_id: str) -> Tuple[str, int]:
        """
        Get the cluster endpoint and port.
        
        Args:
            cluster_id: ID of the cluster
            
        Returns:
            Tuple[str, int]: Cluster endpoint and port
            
        Raises:
            Exception: If endpoint retrieval fails
        """
        try:
            response = self.rds_client.describe_db_clusters(
                DBClusterIdentifier=cluster_id
            )
            
            if not response['DBClusters']:
                raise ValueError(f"Cluster {cluster_id} not found")
            
            cluster = response['DBClusters'][0]
            endpoint = cluster['Endpoint']
            port = cluster['Port']
            
            return endpoint, port
        except Exception as e:
            logger.error(f"Error getting endpoint for cluster {cluster_id}: {str(e)}")
            raise
    
    def get_master_credentials(self) -> Tuple[str, str]:
        """
        Get master database credentials from Secrets Manager.
        
        Returns:
            Tuple[str, str]: Master username and password
            
        Raises:
            Exception: If credentials retrieval fails
        """
        try:
            config = self.config_manager.get_all()
            secret_id = config.master_credentials_secret_id
            secret = get_secret(secret_id)
            
            if not secret:
                raise ValueError(f"Secret {secret_id} not found")
            
            username = secret.get('username')
            password = secret.get('password')
            
            if not username or not password:
                raise ValueError(f"Invalid credentials in secret {secret_id}")
            
            return username, password
        except Exception as e:
            logger.error(f"Error getting master credentials: {str(e)}")
            raise
    
    def setup_users(self, endpoint: str, port: int, master_username: str, master_password: str) -> List[Dict[str, str]]:
        """
        Set up database users.
        
        Args:
            endpoint: Cluster endpoint
            port: Cluster port
            master_username: Master database username
            master_password: Master database password
            
        Returns:
            List[Dict[str, str]]: List of created users
            
        Raises:
            Exception: If user setup fails
        """
        try:
            # Import psycopg2 here to avoid Lambda layer issues
            import psycopg2
            
            # Connect to the database
            conn = psycopg2.connect(
                host=endpoint,
                port=port,
                database='postgres',
                user=master_username,
                password=master_password
            )
            
            # Create a cursor
            cur = conn.cursor()
            
            # Get list of users to create from config
            config = self.config_manager.get_all()
            users = config.get('db_users', [])
            created_users = []
            
            for user in users:
                username = user.get('username')
                password = user.get('password')
                privileges = user.get('privileges', [])
                
                if not username or not password:
                    logger.warning(f"Skipping user setup: missing username or password")
                    continue
                
                # Create user
                cur.execute(f"CREATE USER {username} WITH PASSWORD '{password}'")
                
                # Grant privileges
                for privilege in privileges:
                    cur.execute(f"GRANT {privilege} TO {username}")
                
                created_users.append({
                    'username': username,
                    'privileges': privileges
                })
            
            # Commit the transaction
            conn.commit()
            
            # Close the cursor and connection
            cur.close()
            conn.close()
            
            return created_users
        except Exception as e:
            logger.error(f"Error setting up users: {str(e)}")
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
            
            # Initialize clients
            self.initialize_clients()
            
            # Get cluster details
            cluster_id = self.config_manager.get_all().target_cluster_id
            
            # Get cluster endpoint
            endpoint, port = self.get_cluster_endpoint(cluster_id)
            
            # Get master credentials
            master_username, master_password = self.get_master_credentials()
            
            # Set up users
            created_users = self.setup_users(endpoint, port, master_username, master_password)
            
            # Save state
            state_data = {
                'target_cluster_id': cluster_id,
                'endpoint': endpoint,
                'port': port,
                'users_created': created_users,
                'status': 'success',
                'success': True
            }
            
            # Save state using StateManager
            self.state_manager.save_state(operation_id, 'setup_db_users', state_data)
            
            # Log audit event
            self.state_manager.log_audit_event(
                operation_id,
                'setup_db_users',
                'SUCCESS',
                {
                    'target_cluster_id': cluster_id,
                    'users_created': len(created_users)
                }
            )
            
            # Update metrics
            self.state_manager.update_metrics(operation_id, 'setup_db_users', 'users_created', len(created_users))
            
            # Update state and trigger next step
            self.state_manager.update_state(operation_id, RestoreState.NOTIFY_COMPLETION, state_data)
            
            return self.create_response(operation_id, {
                'message': f"Successfully set up {len(created_users)} users for cluster {cluster_id}",
                'target_cluster_id': cluster_id,
                'endpoint': endpoint,
                'port': port,
                'users_created': created_users,
                'next_step': 'notify_completion'
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
    handler = SetupDbUsersHandler()
    return handler.execute(event, context) 