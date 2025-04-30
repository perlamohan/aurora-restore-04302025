#!/usr/bin/env python3
"""
Consolidated configuration utilities for Aurora restore operations.
Provides configuration management, validation, templating, and CLI functionality.
"""

import os
import json
import argparse
import logging
import sys
from typing import Dict, Any, List, Optional, Union
from dataclasses import dataclass

from utils.aws_utils import get_ssm_parameter

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Function-specific required fields
FUNCTION_REQUIRED_FIELDS = {
    "aurora-restore-snapshot-check": [
        "source_region",
        "source_cluster_id",
        "snapshot_prefix"
    ],
    "aurora-restore-copy-snapshot": [
        "source_region",
        "target_region",
        "kms_key_id"
    ],
    "aurora-restore-check-copy-status": [
        "source_region",
        "target_region",
        "max_copy_attempts",
        "copy_check_interval"
    ],
    "aurora-restore-delete-rds": [
        "target_region",
        "target_cluster_id",
        "skip_final_snapshot"
    ],
    "aurora-restore-restore-snapshot": [
        "target_region",
        "target_cluster_id",
        "db_subnet_group_name",
        "vpc_security_group_ids",
        "kms_key_id",
        "port",
        "deletion_protection"
    ],
    "aurora-restore-check-restore-status": [
        "target_region",
        "target_cluster_id",
        "max_restore_attempts",
        "restore_check_interval"
    ],
    "aurora-restore-setup-db-users": [
        "target_region",
        "target_cluster_id",
        "master_credentials_secret_id",
        "app_credentials_secret_id",
        "db_connection_timeout"
    ],
    "aurora-restore-archive-snapshot": [
        "target_region",
        "archive_snapshot"
    ],
    "aurora-restore-sns-notification": [
        "target_region",
        "sns_topic_arn"
    ]
}

# Default configuration template
DEFAULT_CONFIG_TEMPLATE = {
    "source_region": "us-east-1",
    "target_region": "us-west-2",
    "source_cluster_id": "your-source-cluster",
    "target_cluster_id": "your-target-cluster",
    "snapshot_prefix": "aurora-snapshot",
    "vpc_config": {
        "vpc_id": "vpc-xxxxxxxx",
        "subnet_ids": [
            "subnet-xxxxxxxx",
            "subnet-yyyyyyyy"
        ],
        "security_group_ids": [
            "sg-xxxxxxxx"
        ]
    },
    "restore_params": {
        "db_subnet_group_name": "your-db-subnet-group",
        "vpc_security_group_ids": [
            "sg-xxxxxxxx"
        ],
        "environment": "dev",
        "deletion_protection": False,
        "port": 5432,
        "availability_zones": [
            "us-west-2a",
            "us-west-2b"
        ],
        "enable_iam_database_authentication": True,
        "storage_encrypted": True
    },
    "master_credentials_secret_id": "aurora-restore/master-db-credentials",
    "app_credentials_secret_id": "aurora-restore/app-db-credentials",
    "sns_topic_arn": "arn:aws:sns:region:account:aurora-restore-notifications",
    "retry_params": {
        "copy_status_retry_delay": 60,
        "restore_status_retry_delay": 60,
        "delete_status_retry_delay": 60,
        "max_copy_attempts": 60,
        "copy_check_interval": 30,
        "max_restore_attempts": 60,
        "restore_check_interval": 30
    },
    "db_params": {
        "db_connection_timeout": 30
    },
    "archive_snapshot": True,
    "state_table_name": "aurora-restore-state",
    "audit_table_name": "aurora-restore-audit",
    "log_level": "INFO"
}

@dataclass
class Config:
    """Configuration data class."""
    source_region: str
    target_region: str
    source_cluster_id: str
    target_cluster_id: str
    snapshot_prefix: str
    vpc_security_group_ids: str
    db_subnet_group_name: str
    kms_key_id: str
    master_credentials_secret_id: str
    app_credentials_secret_id: str
    copy_status_retry_delay: int
    restore_status_retry_delay: int
    delete_status_retry_delay: int
    environment: str
    region: str
    account_id: str
    sns_topic_arn: Optional[str] = None

class ConfigManager:
    """Configuration manager for Aurora restore operations."""
    
    def __init__(self):
        """Initialize the configuration manager."""
        self.config = None
        self.environment = os.environ.get('ENVIRONMENT', 'dev')
        self.region = os.environ.get('AWS_REGION', 'us-east-1')
        self.account_id = os.environ.get('AWS_ACCOUNT_ID', '')
    
    def get_env_config(self) -> Dict[str, Any]:
        """
        Get configuration from environment variables.
        
        Returns:
            dict: Configuration dictionary
        """
        return {
            'source_region': os.environ.get('SOURCE_REGION', ''),
            'target_region': os.environ.get('TARGET_REGION', ''),
            'source_cluster_id': os.environ.get('SOURCE_CLUSTER_ID', ''),
            'target_cluster_id': os.environ.get('TARGET_CLUSTER_ID', ''),
            'snapshot_prefix': os.environ.get('SNAPSHOT_PREFIX', 'aurora-snapshot'),
            'vpc_security_group_ids': os.environ.get('VPC_SECURITY_GROUP_IDS', ''),
            'db_subnet_group_name': os.environ.get('DB_SUBNET_GROUP_NAME', ''),
            'kms_key_id': os.environ.get('KMS_KEY_ID', ''),
            'master_credentials_secret_id': os.environ.get('MASTER_CREDENTIALS_SECRET_ID', ''),
            'app_credentials_secret_id': os.environ.get('APP_CREDENTIALS_SECRET_ID', ''),
            'copy_status_retry_delay': int(os.environ.get('COPY_STATUS_RETRY_DELAY', '60')),
            'restore_status_retry_delay': int(os.environ.get('RESTORE_STATUS_RETRY_DELAY', '60')),
            'delete_status_retry_delay': int(os.environ.get('DELETE_STATUS_RETRY_DELAY', '60')),
            'environment': self.environment,
            'region': self.region,
            'account_id': self.account_id
        }
    
    def load_config(self, event: Optional[Dict[str, Any]] = None, state: Optional[Dict[str, Any]] = None) -> None:
        """
        Load configuration from multiple sources.
        
        Args:
            event: Lambda event containing configuration
            state: State data containing configuration
        """
        # Start with environment variables
        config = self.get_env_config()
        
        # Load from SSM Parameter Store
        try:
            ssm_config = get_ssm_parameter(f'/aurora-restore/{self.environment}/config', '{}')
            config.update(json.loads(ssm_config))
        except Exception as e:
            logger.warning(f"Failed to load SSM config: {str(e)}")
        
        # Update from event if provided
        if event:
            config.update(event)
        
        # Update from state if provided
        if state:
            config.update(state)
        
        self.config = config
    
    def get_all(self) -> Config:
        """
        Get all configuration values.
        
        Returns:
            Config: Configuration object
        """
        if not self.config:
            self.load_config()
        return Config(**self.config)
    
    def validate_config(self) -> None:
        """
        Validate configuration.
        
        Raises:
            ValueError: If configuration is invalid
        """
        if not self.config:
            self.load_config()
        
        # Check required fields for all functions
        required_fields = [
            "source_region",
            "target_region",
            "source_cluster_id",
            "target_cluster_id",
            "state_table_name",
            "audit_table_name"
        ]
        
        missing_fields = [field for field in required_fields if not self.config.get(field)]
        if missing_fields:
            raise ValueError(f"Missing required configuration fields: {', '.join(missing_fields)}")

class ConfigValidator:
    """Configuration validator."""
    
    @staticmethod
    def validate_config(config: Dict[str, Any]) -> List[str]:
        """
        Validate configuration.
        
        Args:
            config: Configuration dictionary
            
        Returns:
            List[str]: List of validation errors
        """
        errors = []
        required_fields = [
            "source_region",
            "target_region",
            "source_cluster_id",
            "target_cluster_id",
            "state_table_name",
            "audit_table_name"
        ]
        
        for field in required_fields:
            if not config.get(field):
                errors.append(f"Missing required field: {field}")
        
        return errors
    
    @staticmethod
    def validate_function_config(config: Dict[str, Any], function_name: str) -> List[str]:
        """
        Validate function-specific configuration.
        
        Args:
            config: Configuration dictionary
            function_name: Function name
            
        Returns:
            List[str]: List of validation errors
        """
        errors = []
        required_fields = FUNCTION_REQUIRED_FIELDS.get(function_name, [])
        
        for field in required_fields:
            if not config.get(field):
                errors.append(f"Missing required field for {function_name}: {field}")
        
        return errors
    
    @staticmethod
    def validate_and_log(config: Dict[str, Any], function_name: str) -> bool:
        """
        Validate configuration and log errors.
        
        Args:
            config: Configuration dictionary
            function_name: Function name
            
        Returns:
            bool: True if validation passes, False otherwise
        """
        errors = ConfigValidator.validate_config(config)
        errors.extend(ConfigValidator.validate_function_config(config, function_name))
        
        if errors:
            for error in errors:
                logger.error(error)
            return False
        
        return True

class ConfigTemplateGenerator:
    """
    Generator for configuration templates.
    
    This class provides utilities for generating configuration templates
    and converting between different configuration formats.
    """
    
    @staticmethod
    def generate_template(output_file: str = None) -> Dict[str, Any]:
        """
        Generate a configuration template.
        
        Args:
            output_file: Optional file path to save the template
            
        Returns:
            Configuration template dictionary
        """
        template = DEFAULT_CONFIG_TEMPLATE.copy()
        
        if output_file:
            with open(output_file, 'w') as f:
                json.dump(template, f, indent=4)
            logger.info(f"Configuration template saved to {output_file}")
        
        return template
    
    @staticmethod
    def generate_env_vars_template(output_file: str = None) -> Dict[str, str]:
        """
        Generate an environment variables template.
        
        Args:
            output_file: Optional file path to save the template
            
        Returns:
            Environment variables dictionary
        """
        template = {
            "SOURCE_REGION": "us-east-1",
            "TARGET_REGION": "us-west-2",
            "SOURCE_CLUSTER_ID": "your-source-cluster",
            "TARGET_CLUSTER_ID": "your-target-cluster",
            "SNAPSHOT_PREFIX": "aurora-snapshot",
            "VPC_SECURITY_GROUP_IDS": "sg-xxxxxxxx,sg-yyyyyyyy",
            "DB_SUBNET_GROUP_NAME": "your-db-subnet-group",
            "KMS_KEY_ID": "arn:aws:kms:region:account:key/your-kms-key-id",
            "MASTER_CREDENTIALS_SECRET_ID": "aurora-restore/master-db-credentials",
            "APP_CREDENTIALS_SECRET_ID": "aurora-restore/app-db-credentials",
            "COPY_STATUS_RETRY_DELAY": "60",
            "RESTORE_STATUS_RETRY_DELAY": "60",
            "DELETE_STATUS_RETRY_DELAY": "60",
            "MAX_COPY_ATTEMPTS": "60",
            "COPY_CHECK_INTERVAL": "30",
            "MAX_RESTORE_ATTEMPTS": "60",
            "RESTORE_CHECK_INTERVAL": "30",
            "SKIP_FINAL_SNAPSHOT": "true",
            "PORT": "5432",
            "DELETION_PROTECTION": "false",
            "DB_CONNECTION_TIMEOUT": "30",
            "ARCHIVE_SNAPSHOT": "true",
            "ENVIRONMENT": "dev",
            "STATE_TABLE_NAME": "aurora-restore-state",
            "AUDIT_TABLE_NAME": "aurora-restore-audit",
            "LOG_LEVEL": "INFO",
            "SNS_TOPIC_ARN": "arn:aws:sns:region:account:aurora-restore-notifications"
        }
        
        if output_file:
            with open(output_file, 'w') as f:
                for key, value in template.items():
                    f.write(f"{key}={value}\n")
            logger.info(f"Environment variables template saved to {output_file}")
        
        return template
    
    @staticmethod
    def generate_ssm_template(output_file: str = None) -> Dict[str, Any]:
        """
        Generate an SSM Parameter Store template.
        
        Args:
            output_file: Optional file path to save the template
            
        Returns:
            SSM Parameter Store template dictionary
        """
        template = {
            "/aurora-restore/dev/config": {
                "source_region": "us-east-1",
                "target_region": "us-west-2",
                "source_cluster_id": "your-source-cluster",
                "target_cluster_id": "your-target-cluster",
                "snapshot_prefix": "aurora-snapshot",
                "vpc_security_group_ids": "sg-xxxxxxxx,sg-yyyyyyyy",
                "db_subnet_group_name": "your-db-subnet-group",
                "kms_key_id": "arn:aws:kms:region:account:key/your-kms-key-id",
                "master_credentials_secret_id": "aurora-restore/master-db-credentials",
                "app_credentials_secret_id": "aurora-restore/app-db-credentials",
                "copy_status_retry_delay": 60,
                "restore_status_retry_delay": 60,
                "delete_status_retry_delay": 60,
                "max_copy_attempts": 60,
                "copy_check_interval": 30,
                "max_restore_attempts": 60,
                "restore_check_interval": 30,
                "skip_final_snapshot": True,
                "port": 5432,
                "deletion_protection": False,
                "db_connection_timeout": 30,
                "archive_snapshot": True,
                "environment": "dev",
                "state_table_name": "aurora-restore-state",
                "audit_table_name": "aurora-restore-audit",
                "log_level": "INFO",
                "sns_topic_arn": "arn:aws:sns:region:account:aurora-restore-notifications"
            }
        }
        
        if output_file:
            with open(output_file, 'w') as f:
                json.dump(template, f, indent=4)
            logger.info(f"SSM Parameter Store template saved to {output_file}")
        
        return template
    
    @staticmethod
    def convert_config_to_env_vars(config: Dict[str, Any]) -> Dict[str, str]:
        """
        Convert a configuration dictionary to environment variables.
        
        Args:
            config: Configuration dictionary
            
        Returns:
            Environment variables dictionary
        """
        env_vars = {}
        
        # Map configuration keys to environment variable names
        key_mapping = {
            'source_region': 'SOURCE_REGION',
            'target_region': 'TARGET_REGION',
            'source_cluster_id': 'SOURCE_CLUSTER_ID',
            'target_cluster_id': 'TARGET_CLUSTER_ID',
            'snapshot_prefix': 'SNAPSHOT_PREFIX',
            'vpc_security_group_ids': 'VPC_SECURITY_GROUP_IDS',
            'db_subnet_group_name': 'DB_SUBNET_GROUP_NAME',
            'kms_key_id': 'KMS_KEY_ID',
            'master_credentials_secret_id': 'MASTER_CREDENTIALS_SECRET_ID',
            'app_credentials_secret_id': 'APP_CREDENTIALS_SECRET_ID',
            'copy_status_retry_delay': 'COPY_STATUS_RETRY_DELAY',
            'restore_status_retry_delay': 'RESTORE_STATUS_RETRY_DELAY',
            'delete_status_retry_delay': 'DELETE_STATUS_RETRY_DELAY',
            'max_copy_attempts': 'MAX_COPY_ATTEMPTS',
            'copy_check_interval': 'COPY_CHECK_INTERVAL',
            'max_restore_attempts': 'MAX_RESTORE_ATTEMPTS',
            'restore_check_interval': 'RESTORE_CHECK_INTERVAL',
            'skip_final_snapshot': 'SKIP_FINAL_SNAPSHOT',
            'port': 'PORT',
            'deletion_protection': 'DELETION_PROTECTION',
            'db_connection_timeout': 'DB_CONNECTION_TIMEOUT',
            'archive_snapshot': 'ARCHIVE_SNAPSHOT',
            'environment': 'ENVIRONMENT',
            'state_table_name': 'STATE_TABLE_NAME',
            'audit_table_name': 'AUDIT_TABLE_NAME',
            'log_level': 'LOG_LEVEL',
            'sns_topic_arn': 'SNS_TOPIC_ARN'
        }
        
        for key, value in config.items():
            if key in key_mapping:
                env_vars[key_mapping[key]] = str(value)
        
        return env_vars
    
    @staticmethod
    def convert_env_vars_to_config(env_vars: Dict[str, str]) -> Dict[str, Any]:
        """
        Convert environment variables to a configuration dictionary.
        
        Args:
            env_vars: Environment variables dictionary
            
        Returns:
            Configuration dictionary
        """
        config = {}
        
        # Map environment variable names to configuration keys
        key_mapping = {
            'SOURCE_REGION': 'source_region',
            'TARGET_REGION': 'target_region',
            'SOURCE_CLUSTER_ID': 'source_cluster_id',
            'TARGET_CLUSTER_ID': 'target_cluster_id',
            'SNAPSHOT_PREFIX': 'snapshot_prefix',
            'VPC_SECURITY_GROUP_IDS': 'vpc_security_group_ids',
            'DB_SUBNET_GROUP_NAME': 'db_subnet_group_name',
            'KMS_KEY_ID': 'kms_key_id',
            'MASTER_CREDENTIALS_SECRET_ID': 'master_credentials_secret_id',
            'APP_CREDENTIALS_SECRET_ID': 'app_credentials_secret_id',
            'COPY_STATUS_RETRY_DELAY': 'copy_status_retry_delay',
            'RESTORE_STATUS_RETRY_DELAY': 'restore_status_retry_delay',
            'DELETE_STATUS_RETRY_DELAY': 'delete_status_retry_delay',
            'MAX_COPY_ATTEMPTS': 'max_copy_attempts',
            'COPY_CHECK_INTERVAL': 'copy_check_interval',
            'MAX_RESTORE_ATTEMPTS': 'max_restore_attempts',
            'RESTORE_CHECK_INTERVAL': 'restore_check_interval',
            'SKIP_FINAL_SNAPSHOT': 'skip_final_snapshot',
            'PORT': 'port',
            'DELETION_PROTECTION': 'deletion_protection',
            'DB_CONNECTION_TIMEOUT': 'db_connection_timeout',
            'ARCHIVE_SNAPSHOT': 'archive_snapshot',
            'ENVIRONMENT': 'environment',
            'STATE_TABLE_NAME': 'state_table_name',
            'AUDIT_TABLE_NAME': 'audit_table_name',
            'LOG_LEVEL': 'log_level',
            'SNS_TOPIC_ARN': 'sns_topic_arn'
        }
        
        for key, value in env_vars.items():
            if key in key_mapping:
                config_key = key_mapping[key]
                
                # Convert string values to appropriate types
                if config_key in ['copy_status_retry_delay', 'restore_status_retry_delay', 
                                 'delete_status_retry_delay', 'max_copy_attempts', 
                                 'copy_check_interval', 'max_restore_attempts', 
                                 'restore_check_interval', 'port', 'db_connection_timeout']:
                    try:
                        config[config_key] = int(value)
                    except ValueError:
                        config[config_key] = value
                
                elif config_key in ['skip_final_snapshot', 'deletion_protection', 'archive_snapshot']:
                    config[config_key] = value.lower() in ['true', '1', 'yes', 'y']
                
                else:
                    config[config_key] = value
        
        return config

def setup_parser():
    """Set up command-line argument parser"""
    parser = argparse.ArgumentParser(
        description='Aurora Restore Configuration CLI',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Command to execute')
    
    # Generate template command
    template_parser = subparsers.add_parser('generate-template', help='Generate configuration template')
    template_parser.add_argument('--output', '-o', help='Output file path')
    template_parser.add_argument('--format', '-f', choices=['json', 'env', 'ssm'], default='json',
                                help='Template format (default: json)')
    
    # Validate config command
    validate_parser = subparsers.add_parser('validate', help='Validate configuration')
    validate_parser.add_argument('--config', '-c', required=True, help='Configuration file path')
    validate_parser.add_argument('--function', '-f', help='Lambda function name')
    
    # Convert config command
    convert_parser = subparsers.add_parser('convert', help='Convert configuration format')
    convert_parser.add_argument('--input', '-i', required=True, help='Input file path')
    convert_parser.add_argument('--output', '-o', required=True, help='Output file path')
    convert_parser.add_argument('--from-format', '-f', choices=['json', 'env', 'ssm'], required=True,
                               help='Input format')
    convert_parser.add_argument('--to-format', '-t', choices=['json', 'env', 'ssm'], required=True,
                               help='Output format')
    
    # Deploy config command
    deploy_parser = subparsers.add_parser('deploy', help='Deploy configuration to SSM Parameter Store')
    deploy_parser.add_argument('--config', '-c', required=True, help='Configuration file path')
    deploy_parser.add_argument('--environment', '-e', default='dev', help='Environment name (default: dev)')
    
    return parser

def generate_template(args):
    """Generate configuration template"""
    if args.format == 'json':
        ConfigTemplateGenerator.generate_template(args.output)
    elif args.format == 'env':
        ConfigTemplateGenerator.generate_env_vars_template(args.output)
    elif args.format == 'ssm':
        ConfigTemplateGenerator.generate_ssm_template(args.output)
    
    logger.info(f"Template generated in {args.format} format")

def validate_config(args):
    """Validate configuration"""
    try:
        with open(args.config, 'r') as f:
            config = json.load(f)
        
        if args.function:
            is_valid = ConfigValidator.validate_and_log(config, args.function)
        else:
            errors = ConfigValidator.validate_config(config)
            is_valid = len(errors) == 0
            if not is_valid:
                for error in errors:
                    logger.error(error)
        
        if is_valid:
            logger.info("Configuration is valid")
        else:
            logger.error("Configuration is invalid")
            sys.exit(1)
    except Exception as e:
        logger.error(f"Error validating configuration: {str(e)}")
        sys.exit(1)

def convert_config(args):
    """Convert configuration format"""
    try:
        # Load input configuration
        if args.from_format == 'json':
            with open(args.input, 'r') as f:
                config = json.load(f)
        elif args.from_format == 'env':
            config = {}
            with open(args.input, 'r') as f:
                for line in f:
                    if '=' in line:
                        key, value = line.strip().split('=', 1)
                        config[key] = value
            config = ConfigTemplateGenerator.convert_env_vars_to_config(config)
        elif args.from_format == 'ssm':
            with open(args.input, 'r') as f:
                ssm_config = json.load(f)
            # Extract the first environment's config
            config = next(iter(ssm_config.values()))
        
        # Convert to output format
        if args.to_format == 'json':
            with open(args.output, 'w') as f:
                json.dump(config, f, indent=4)
        elif args.to_format == 'env':
            env_vars = ConfigTemplateGenerator.convert_config_to_env_vars(config)
            with open(args.output, 'w') as f:
                for key, value in env_vars.items():
                    f.write(f"{key}={value}\n")
        elif args.to_format == 'ssm':
            ssm_config = {f"/aurora-restore/{config.get('environment', 'dev')}/config": config}
            with open(args.output, 'w') as f:
                json.dump(ssm_config, f, indent=4)
        
        logger.info(f"Configuration converted from {args.from_format} to {args.to_format}")
    except Exception as e:
        logger.error(f"Error converting configuration: {str(e)}")
        sys.exit(1)

def deploy_config(args):
    """Deploy configuration to SSM Parameter Store"""
    try:
        with open(args.config, 'r') as f:
            config = json.load(f)
        
        # Validate configuration
        errors = ConfigValidator.validate_config(config)
        if errors:
            for error in errors:
                logger.error(error)
            logger.error("Configuration is invalid")
            sys.exit(1)
        
        # Create SSM client
        import boto3
        ssm_client = boto3.client('ssm')
        
        # Deploy to SSM Parameter Store
        ssm_path = f"/aurora-restore/{args.environment}/config"
        ssm_client.put_parameter(
            Name=ssm_path,
            Value=json.dumps(config),
            Type='String',
            Overwrite=True,
            Tags=[
                {'Key': 'Environment', 'Value': args.environment},
                {'Key': 'Project', 'Value': 'AuroraRestore'},
                {'Key': 'Service', 'Value': 'Configuration'}
            ]
        )
        
        logger.info(f"Configuration deployed to SSM Parameter Store: {ssm_path}")
    except Exception as e:
        logger.error(f"Error deploying configuration: {str(e)}")
        sys.exit(1)

def main():
    """Main entry point"""
    parser = setup_parser()
    args = parser.parse_args()
    
    if args.command == 'generate-template':
        generate_template(args)
    elif args.command == 'validate':
        validate_config(args)
    elif args.command == 'convert':
        convert_config(args)
    elif args.command == 'deploy':
        deploy_config(args)
    else:
        parser.print_help()

if __name__ == '__main__':
    main() 