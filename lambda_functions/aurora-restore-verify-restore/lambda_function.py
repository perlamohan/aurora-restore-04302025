#!/usr/bin/env python3
"""
Lambda function to verify the restored cluster's functionality.
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

class VerifyRestoreHandler(BaseHandler):
    """Handler for verifying cluster restore."""
    
    def __init__(self):
        """Initialize the verify restore handler."""
        super().__init__('verify_restore')
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
        errors = ConfigValidator.validate_function_config(config.__dict__, 'aurora-restore-verify-restore')
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
    
    def verify_connection(self, endpoint: str, port: int, username: str, password: str) -> bool:
        """
        Verify database connection.
        
        Args:
            endpoint: Cluster endpoint
            port: Cluster port
            username: Database username
            password: Database password
            
        Returns:
            bool: True if connection successful, False otherwise
            
        Raises:
            Exception: If verification fails
        """
        try:
            # Import psycopg2 here to avoid Lambda layer issues
            import psycopg2
            
            # Connect to the database
            conn = psycopg2.connect(
                host=endpoint,
                port=port,
                database='postgres',
                user=username,
                password=password
            )
            
            # Create a cursor
            cur = conn.cursor()
            
            # Execute a simple query
            cur.execute('SELECT version()')
            version = cur.fetchone()[0]
            
            # Close the cursor and connection
            cur.close()
            conn.close()
            
            logger.info(f"Successfully connected to database. Version: {version}")
            return True
        except Exception as e:
            logger.error(f"Error verifying connection: {str(e)}")
            return False
    
    def verify_schema(self, endpoint: str, port: int, username: str, password: str) -> Dict[str, Any]:
        """
        Verify database schema.
        
        Args:
            endpoint: Cluster endpoint
            port: Cluster port
            username: Database username
            password: Database password
            
        Returns:
            Dict[str, Any]: Schema verification results
            
        Raises:
            Exception: If verification fails
        """
        try:
            # Import psycopg2 here to avoid Lambda layer issues
            import psycopg2
            
            # Connect to the database
            conn = psycopg2.connect(
                host=endpoint,
                port=port,
                database='postgres',
                user=username,
                password=password
            )
            
            # Create a cursor
            cur = conn.cursor()
            
            # Get list of schemas
            cur.execute("""
                SELECT schema_name 
                FROM information_schema.schemata 
                WHERE schema_name NOT IN ('information_schema', 'pg_catalog')
            """)
            schemas = [row[0] for row in cur.fetchall()]
            
            # Get list of tables
            cur.execute("""
                SELECT table_schema, table_name 
                FROM information_schema.tables 
                WHERE table_schema NOT IN ('information_schema', 'pg_catalog')
            """)
            tables = [{'schema': row[0], 'name': row[1]} for row in cur.fetchall()]
            
            # Close the cursor and connection
            cur.close()
            conn.close()
            
            return {
                'schemas': schemas,
                'tables': tables
            }
        except Exception as e:
            logger.error(f"Error verifying schema: {str(e)}")
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
            username, password = self.get_master_credentials()
            
            # Verify connection
            connection_success = self.verify_connection(endpoint, port, username, password)
            
            if not connection_success:
                error_message = f"Failed to connect to cluster {cluster_id}"
                logger.error(error_message)
                
                # Save state with error
                state_data = {
                    'target_cluster_id': cluster_id,
                    'endpoint': endpoint,
                    'port': port,
                    'connection_success': False,
                    'verification_status': 'failed',
                    'status': 'failed',
                    'success': False,
                    'error': error_message
                }
                
                # Save state using StateManager
                self.state_manager.save_state(operation_id, 'verify_restore', state_data)
                
                # Log audit event
                self.state_manager.log_audit_event(
                    operation_id,
                    'verify_restore',
                    'FAILED',
                    {
                        'target_cluster_id': cluster_id,
                        'error': error_message
                    }
                )
                
                # Update metrics
                self.state_manager.update_metrics(operation_id, 'verify_restore', 'verification_failure', 1)
                
                return self.create_response(operation_id, {
                    'message': error_message,
                    'target_cluster_id': cluster_id,
                    'next_step': None
                })
            
            # Verify schema
            schema_details = self.verify_schema(endpoint, port, username, password)
            
            # Save state
            state_data = {
                'target_cluster_id': cluster_id,
                'endpoint': endpoint,
                'port': port,
                'connection_success': True,
                'verification_status': 'success',
                'status': 'success',
                'success': True,
                'schema_details': schema_details
            }
            
            # Save state using StateManager
            self.state_manager.save_state(operation_id, 'verify_restore', state_data)
            
            # Log audit event
            self.state_manager.log_audit_event(
                operation_id,
                'verify_restore',
                'SUCCESS',
                {
                    'target_cluster_id': cluster_id,
                    'schema_count': len(schema_details['schemas']),
                    'table_count': len(schema_details['tables'])
                }
            )
            
            # Update metrics
            self.state_manager.update_metrics(operation_id, 'verify_restore', 'verification_success', 1)
            
            # Update state and trigger next step
            self.state_manager.update_state(operation_id, RestoreState.SETUP_USERS, state_data)
            
            return self.create_response(operation_id, {
                'message': f"Cluster {cluster_id} verification successful",
                'target_cluster_id': cluster_id,
                'schema_count': len(schema_details['schemas']),
                'table_count': len(schema_details['tables']),
                'next_step': 'setup_users'
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
    handler = VerifyRestoreHandler()
    return handler.execute(event, context) 