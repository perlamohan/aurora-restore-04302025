#!/usr/bin/env python3
"""
Lambda function to send notifications about the completion of the restore process.
"""

import json
import logging
import time
from typing import Dict, Any, Optional, List

from utils.base_handler import BaseHandler
from utils.aws_utils import get_sns_client, get_sqs_client, publish_sns_message
from utils.config_utils import ConfigManager, ConfigValidator
from utils.state_utils import StateManager, RestoreState

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class NotifyCompletionHandler(BaseHandler):
    """Handler for sending completion notifications."""
    
    def __init__(self):
        """Initialize the notify completion handler."""
        super().__init__('notify_completion')
        self.config_manager = ConfigManager()
        self.state_manager = StateManager(self.config_manager.get_all().region)
        self.sns_client = None
        self.sqs_client = None
    
    def validate_config(self) -> None:
        """
        Validate required configuration parameters.
        
        Raises:
            ValueError: If required parameters are missing or invalid
        """
        config = self.config_manager.get_all()
        
        # Validate configuration using the ConfigValidator
        errors = ConfigValidator.validate_function_config(config.__dict__, 'aurora-restore-notify-completion')
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
        
        self.sns_client = get_sns_client(config.target_region)
        self.sqs_client = get_sqs_client(config.target_region)
    
    def get_operation_summary(self, operation_id: str) -> Dict[str, Any]:
        """
        Get a summary of the restore operation.
        
        Args:
            operation_id: ID of the operation
            
        Returns:
            Dict[str, Any]: Operation summary
            
        Raises:
            Exception: If summary retrieval fails
        """
        try:
            # Get state data
            state_data = self.state_manager.get_state(operation_id)
            
            if not state_data:
                raise ValueError(f"State data not found for operation {operation_id}")
            
            # Extract relevant information
            summary = {
                'operation_id': operation_id,
                'target_cluster_id': state_data.get('target_cluster_id'),
                'status': state_data.get('status', 'unknown'),
                'success': state_data.get('success', False),
                'start_time': state_data.get('start_time'),
                'end_time': state_data.get('end_time'),
                'duration_seconds': state_data.get('duration_seconds', 0),
                'error': state_data.get('error')
            }
            
            # Add verification information if available
            if 'verification_status' in state_data:
                summary['verification_status'] = state_data['verification_status']
                summary['schema_count'] = len(state_data.get('schema_details', {}).get('schemas', []))
                summary['table_count'] = len(state_data.get('schema_details', {}).get('tables', []))
            
            return summary
        except Exception as e:
            logger.error(f"Error getting operation summary: {str(e)}")
            raise
    
    def send_sns_notification(self, operation_id: str, summary: Dict[str, Any]) -> str:
        """
        Send SNS notification.
        
        Args:
            operation_id: ID of the operation
            summary: Operation summary
            
        Returns:
            str: Message ID
            
        Raises:
            Exception: If notification fails
        """
        try:
            config = self.config_manager.get_all()
            topic_arn = config.sns_topic_arn
            
            # Prepare message
            message = {
                'operation_id': operation_id,
                'event_type': 'aurora_restore_completion',
                'timestamp': int(time.time()),
                'summary': summary
            }
            
            # Send message
            message_id = publish_sns_message(
                topic_arn=topic_arn,
                message=json.dumps(message),
                subject=f"Aurora Restore Completion - {summary['target_cluster_id']}"
            )
            
            logger.info(f"Sent SNS notification with ID {message_id}")
            
            return message_id
        except Exception as e:
            logger.error(f"Error sending SNS notification: {str(e)}")
            raise
    
    def send_sqs_message(self, operation_id: str, summary: Dict[str, Any]) -> str:
        """
        Send SQS message.
        
        Args:
            operation_id: ID of the operation
            summary: Operation summary
            
        Returns:
            str: Message ID
            
        Raises:
            Exception: If message sending fails
        """
        try:
            config = self.config_manager.get_all()
            queue_url = config.notification_queue_url
            
            # Prepare message
            message = {
                'operation_id': operation_id,
                'event_type': 'aurora_restore_completion',
                'timestamp': int(time.time()),
                'summary': summary
            }
            
            # Send message
            response = self.sqs_client.send_message(
                QueueUrl=queue_url,
                MessageBody=json.dumps(message)
            )
            
            message_id = response['MessageId']
            logger.info(f"Sent SQS message with ID {message_id}")
            
            return message_id
        except Exception as e:
            logger.error(f"Error sending SQS message: {str(e)}")
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
            
            # Get operation summary
            summary = self.get_operation_summary(operation_id)
            
            # Send notifications
            sns_message_id = self.send_sns_notification(operation_id, summary)
            sqs_message_id = self.send_sqs_message(operation_id, summary)
            
            # Save state
            state_data = {
                'notification_sent': True,
                'notification_time': int(time.time()),
                'sns_message_id': sns_message_id,
                'sqs_message_id': sqs_message_id
            }
            
            # Save state using StateManager
            self.state_manager.save_state(operation_id, 'notify_completion', state_data)
            
            # Log audit event
            self.state_manager.log_audit_event(
                operation_id,
                'notify_completion',
                'SUCCESS',
                {
                    'target_cluster_id': summary['target_cluster_id'],
                    'status': summary['status'],
                    'sns_message_id': sns_message_id,
                    'sqs_message_id': sqs_message_id
                }
            )
            
            # Update metrics
            self.state_manager.update_metrics(operation_id, 'notify_completion', 'notification_sent', 1)
            
            # Update state and trigger next step
            self.state_manager.update_state(operation_id, RestoreState.COMPLETED, state_data)
            
            return self.create_response(operation_id, {
                'message': f"Successfully sent completion notifications for cluster {summary['target_cluster_id']}",
                'target_cluster_id': summary['target_cluster_id'],
                'status': summary['status'],
                'sns_message_id': sns_message_id,
                'sqs_message_id': sqs_message_id,
                'next_step': None
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
    handler = NotifyCompletionHandler()
    return handler.execute(event, context) 