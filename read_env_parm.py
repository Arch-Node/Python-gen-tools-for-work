#!/usr/bin/env python3

# This script reads environment variables and prints their values.
# if no environment variables are set, it will log a warning and look for a default file
import os
import sys
import logging
import getpass
import socket
import platform
import json
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def _masked_for_log(var_name, value):
    if value is None:
        return value

    # Mask values for variables whose names suggest credentials.
    lowered_name = var_name.lower()
    if 'pass' in lowered_name or 'key' in lowered_name:
        if len(value) <= 1:
            return '_redatcted_'
        return f'{value[0]}_redatcted_{value[-1]}'

    return value


def _mask_sensitive_values(data):
    masked = {}
    for key, value in data.items():
        text_value = str(value) if value is not None else ''
        masked[key] = _masked_for_log(key, text_value)
    return masked

def check_virtual_env():
    # Check for a virtual python environment and if it exists create a dictionary of the environment variables and their values.
    # If no virtual environment is detected, log a warning. If a virtual environment is detected, log the path to the virtual environment.
    if sys.prefix == sys.base_prefix:
        logging.warning('No virtual environment detected. It is recommended to use a virtual environment for this script.')
    else:
        logging.info('Virtual environment detected.')
    if os.environ.get('VIRTUAL_ENV'):
        logging.info(f'Virtual environment path: {os.environ["VIRTUAL_ENV"]}')

    # Log the active interpreter details so it is clear which Python installation
    # is running — important when the server has a second Python alongside the OS one.
    logging.info(f'Python executable: {sys.executable}')
    logging.info(f'Python version: {sys.version}')
    logging.info(f'sys.prefix (active env): {sys.prefix}')
    logging.info(f'sys.base_prefix (base install): {sys.base_prefix}')

    # Capture execution identity details for auditability in UC4 jobs.
    runtime_info = {
        'RUNNING_USER': getpass.getuser(),
        'HOSTNAME': socket.gethostname(),
        'OS_NAME': platform.system(),
        'OS_RELEASE': platform.release(),
        'OS_VERSION': platform.version(),
    }
    for key, value in runtime_info.items():
        logging.info(f'{key}: {value}')

    # Collect all environment variables relevant to Python resolution.
    python_relevant_keys = ('VIRTUAL_ENV', 'PYTHONPATH', 'PYTHONHOME', 'PATH')
    env_info = dict(runtime_info)

    for key in python_relevant_keys:
        value = os.environ.get(key)
        if value:
            env_info[key] = value
            logging.info(f'{key}: {_masked_for_log(key, value)}')
        else:
            logging.debug(f'{key} is not set.')

    # Capture any UC4/automation variables that may influence the Python environment.
    uc4_vars = {key: value for key, value in os.environ.items()
                if key.startswith(('UC4', 'AUTOMIC', 'AE_'))}
    if uc4_vars:
        env_info.update(uc4_vars)
        for key, value in uc4_vars.items():
            logging.info(f'UC4/Automic variable {key}: {_masked_for_log(key, value)}')
    else:
        logging.debug('No UC4/Automic environment variables detected.')

    return env_info


def json_output_for_log(json_file_path, include_full_env=True):
    """
    Writes runtime/environment diagnostics to a JSON file for job troubleshooting.
    Sensitive values are masked when variable names contain 'pass' or 'key'.

    :param json_file_path: Destination JSON file path.
    :param include_full_env: Include masked copy of all environment variables.
    :return: True if written successfully, otherwise False.
    """
    env_info = check_virtual_env()

    snapshot = {
        'timestamp_utc': datetime.now(timezone.utc).isoformat(),
        'python_executable': sys.executable,
        'python_version': sys.version,
        'sys_prefix': sys.prefix,
        'sys_base_prefix': sys.base_prefix,
        'runtime_summary': _mask_sensitive_values(env_info),
    }

    if include_full_env:
        snapshot['all_environment_variables'] = _mask_sensitive_values(dict(os.environ))

    try:
        output_dir = os.path.dirname(os.path.abspath(json_file_path))
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)

        with open(json_file_path, 'w', encoding='utf-8') as json_file:
            json.dump(snapshot, json_file, indent=2, sort_keys=True)

        logging.info(f'Wrote runtime snapshot to {json_file_path}')
        return True
    except OSError as error:
        logging.error(f'Failed to write runtime snapshot to {json_file_path}: {error}')
        return False

def read_env_parm(env_var_name, default_file_path=None):
    """
    Reads an environment variable and returns its value. If the environment variable is not set, it will log a warning and look for a default file.
    :param env_var_name: The name of the environment variable to read.
    :param default_file_path: The path to the default file to read if the environment variable is not set.
    :return: The value of the environment variable or the contents of the default file.
    """
    env_var_value = os.getenv(env_var_name)
    
    if env_var_value is not None:
        logging.info(
            f'Environment variable {env_var_name} found with value: '
            f'{_masked_for_log(env_var_name, env_var_value)}'
        )
        return env_var_value
    else:
        logging.warning(f'Environment variable {env_var_name} not found.')
        if default_file_path and os.path.isfile(default_file_path):
            with open(default_file_path, 'r') as file:
                default_value = file.read().strip()
                logging.info(f'Read default value from {default_file_path}: {default_value}')
                return default_value
        else:
            logging.error(f'Default file {default_file_path} not found.')
            return None

