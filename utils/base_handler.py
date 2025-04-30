#!/usr/bin/env python3
"""
Base handler class for Aurora restore Lambda functions.
Provides common functionality and error handling for all Lambda functions.
"""

import time
import json
import uuid
import logging
from typing import Dict, Any, TypeVar, Generic, Optional
import boto3

from utils.config_utils import ConfigManager
from utils.state_utils import StateManager, RestoreState
from utils.aws_utils import publish_sns_message

# Configure logging
logger = logging.getLogger(__name__)

T = TypeVar('T')

class BaseHandler(Generic[T]):
    """Base handler class for Lambda functions with common functionality."""
    
    def __init__(self, step_name: str):
        """
        Initialize the base handler.
        
        Args:
            step_name: Name of the step being handled (e.g., 'snapshot_check')
        """
        self.step_name = step_name
        self.config_manager = ConfigManager()
        self.config = self.config_manager.get_all()
        self.state_manager = StateManager(self.config.region)
        self.start_time = time.time()
    
    def validate_event(self, event: Dict[str, Any]) -> None:
        """
        Validate the incoming event.
        
        Args:
            event: The Lambda event to validate
            
        Raises:
            ValueError: If event validation fails
        """
        if not isinstance(event, dict):
            raise ValueError("Event must be a dictionary")
    
    def get_operation_id(self, event: Dict[str, Any]) -> str:
        """
        Get or generate operation ID from event.
        
        Args:
            event: Lambda event
            
        Returns:
            str: Operation ID
        """
        if event and isinstance(event, dict):
            if 'operation_id' in event:
                return event['operation_id']
            if 'body' in event and isinstance(event['body'], dict) and 'operation_id' in event['body']:
                return event['body']['operation_id']
        
        return f"op-{int(time.time())}-{uuid.uuid4().hex[:8]}"
    
    def handle_error(self, operation_id: str, error: Exception, details: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle an error in the operation.
        
        Args:
            operation_id: Operation ID
            error: The error that occurred
            details: Additional details
            
        Returns:
            Dict[str, Any]: Error response
        """
        error_message = str(error)
        logger.error(f"Error in {self.step_name}: {error_message}", extra={
            'operation_id': operation_id,
            'step': self.step_name,
            'error': error_message,
            'details': details
        })
        
        self.state_manager.log_audit_event(
            operation_id,
            self.step_name,
            'ERROR',
            {'error': error_message, 'details': details}
        )
        
        self.state_manager.update_state(
            operation_id,
            RestoreState.FAILED,
            {'error': error_message}
        )
        
        if self.config.sns_topic_arn:
            publish_sns_message(
                self.config.sns_topic_arn,
                f"Error in {self.step_name}: {error_message}",
                {
                    'operation_id': operation_id,
                    'step': self.step_name,
                    'error': error_message,
                    'details': details
                }
            )
        
        return self.create_response(
            operation_id,
            {
                'error': error_message,
                'details': details
            },
            500
        )
    
    def create_response(self, operation_id: str, data: Dict[str, Any], status_code: int = 200) -> Dict[str, Any]:
        """
        Create a standardized response.
        
        Args:
            operation_id: Operation ID
            data: Response data
            status_code: HTTP status code
            
        Returns:
            Dict[str, Any]: Standardized response
        """
        return {
            'statusCode': status_code,
            'body': json.dumps({
                'operation_id': operation_id,
                'step': self.step_name,
                'timestamp': int(time.time()),
                'data': data
            })
        }
    
    def execute(self, event: Dict[str, Any], context: Any) -> Dict[str, Any]:
        """
        Execute the Lambda function.
        
        Args:
            event: Lambda event
            context: Lambda context
            
        Returns:
            Dict[str, Any]: Lambda response
        """
        try:
            # Validate event
            self.validate_event(event)
            
            # Get operation ID
            operation_id = self.get_operation_id(event)
            
            # Load configuration from event and state
            if 'state' in event:
                self.config_manager.load_config(event=event, state=event['state'])
            else:
                self.config_manager.load_config(event=event)
            
            self.config = self.config_manager.get_all()
            self.config_manager.validate_config()
            
            # Process the event
            return self.process(event, context)
        except Exception as e:
            # Handle any unhandled exceptions
            operation_id = self.get_operation_id(event) if event else "unknown"
            return self.handle_error(operation_id, e, {})
    
    def process(self, event: Dict[str, Any], context: Any) -> Dict[str, Any]:
        """
        Process the event.
        
        Args:
            event: Lambda event
            context: Lambda context
            
        Returns:
            Dict[str, Any]: Response
        """
        raise NotImplementedError("Subclasses must implement process()") 