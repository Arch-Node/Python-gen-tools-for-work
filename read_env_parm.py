#!/usr/bin/env python3

# This script reads environment variables and prints their values.
# if no environment variables are set, it will log a warning and look for a default file

# =============================================================================
# PSEUDOCODE — HOW TO USE THIS MODULE
# =============================================================================
#
# PURPOSE:
#   Utility module for safely reading environment variables and parameter files
#   in UC4-scheduled Python jobs. Provides masked logging for sensitive values
#   and produces a JSON diagnostics snapshot for job troubleshooting.
#
# TYPICAL USAGE IN A JOB SCRIPT:
#
#   1. CHECK THE PYTHON ENVIRONMENT
#      ---------------------------------------------------------
#      from read_env_parm import check_virtual_env
#
#      env_info = check_virtual_env()
#      # Logs: running user, hostname, OS, Python executable/version,
#      #       VIRTUAL_ENV, PATH, PYTHONPATH, PYTHONHOME, UC4/Automic vars.
#      # Returns: dictionary of all captured environment details.
#
#   2. READ A SINGLE ENVIRONMENT VARIABLE
#      ---------------------------------------------------------
#      from read_env_parm import read_env_parm
#
#      value = read_env_parm('MY_VAR')
#      # Returns the value of MY_VAR, or None if not set.
#
#      value = read_env_parm('MY_VAR', default_file_path='/path/to/default.txt')
#      # If MY_VAR is not set, falls back to reading the value from the file.
#
#   3. READ A PARAMETER FILE INTO A DICTIONARY
#      ---------------------------------------------------------
#      from read_env_parm import read_par_file
#
#      params = read_par_file('/path/to/job.par')
#      # Supports KEY=VALUE and KEY: VALUE formats.
#      # Lines starting with # or ; are treated as comments and ignored.
#      # Sensitive keys (names containing 'pass' or 'key') are masked in logs.
#      # Returns: dictionary of all key/value pairs from the file.
#
#   4. WRITE A JSON DIAGNOSTICS SNAPSHOT FOR THE JOB LOG
#      ---------------------------------------------------------
#      from read_env_parm import json_output_for_log
#
#      json_output_for_log('/path/to/job_runtime_snapshot.json')
#      # Writes timestamp, Python details, runtime identity, and environment
#      # variables to a JSON file. Sensitive values are masked.
#      # Pass include_full_env=False to omit the full environment variable dump.
#
# SENSITIVE VALUE MASKING:
#   Any variable whose name contains 'pass' or 'key' (case-insensitive) will
#   have its value shown in logs as:  first_char + _redatcted_ + last_char
#   The actual value is always returned unchanged for use in your code.
#
#   5. RUN BUILT-IN UNIT TESTS
#      ---------------------------------------------------------
#      Run this file directly from the command line to execute all unit tests:
#
#        python read_env_parm.py
#
#      Tests cover all four public functions (31 tests total):
#        - _masked_for_log        : sensitive key detection and masking formats
#        - _mask_sensitive_values : whole-dict masking including None handling
#        - read_env_parm          : env var lookup and default file fallback
#        - read_par_file          : KEY=VALUE / KEY: VALUE parsing, comments,
#                                   blank lines, malformed lines, missing file
#        - check_virtual_env      : return type and required runtime keys
#        - json_output_for_log    : JSON file creation, include_full_env flag,
#                                   graceful failure on bad path
#
#      When importing this module in another script the tests do NOT run —
#      they are gated by  if __name__ == '__main__'  at the bottom of the file.
#
# =============================================================================

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

def read_par_file(par_file_path):
    """
    Reads a parameter file (e.g. .par, .env, .cfg, .properties) and returns its
    contents as a dictionary. Each non-blank, non-comment line is expected to be in
    KEY=VALUE or KEY: VALUE format. Lines starting with '#' or ';' are treated as
    comments and ignored. Sensitive values are masked in log output only; the
    returned dictionary always contains the original values.

    :param par_file_path: Path to the parameter file to read.
    :return: Dictionary of parameter key/value pairs, or empty dict on failure.
    """
    params = {}

    if not par_file_path or not os.path.isfile(par_file_path):
        logging.error(f'Parameter file not found: {par_file_path}')
        return params

    logging.info(f'Reading parameter file: {par_file_path}')

    try:
        with open(par_file_path, 'r', encoding='utf-8') as par_file:
            for line_number, raw_line in enumerate(par_file, start=1):
                line = raw_line.strip()

                # Skip blank lines and comments.
                if not line or line.startswith(('#', ';')):
                    continue

                # Support both KEY=VALUE and KEY: VALUE formats.
                if '=' in line:
                    key, _, value = line.partition('=')
                elif ':' in line:
                    key, _, value = line.partition(':')
                else:
                    logging.warning(
                        f'Line {line_number} in {par_file_path} is not in KEY=VALUE '
                        f'or KEY: VALUE format — skipped.'
                    )
                    continue

                key = key.strip()
                value = value.strip()

                if not key:
                    logging.warning(f'Line {line_number} in {par_file_path} has an empty key — skipped.')
                    continue

                params[key] = value
                logging.info(f'Parameter loaded — {key}: {_masked_for_log(key, value)}')

    except OSError as error:
        logging.error(f'Failed to read parameter file {par_file_path}: {error}')
        return {}

    logging.info(f'Loaded {len(params)} parameter(s) from {par_file_path}')
    return params


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


# =============================================================================
# UNIT TESTS — run this file directly to execute: python read_env_parm.py
# =============================================================================

if __name__ == '__main__':
    import unittest
    import tempfile

    class TestMaskedForLog(unittest.TestCase):

        def test_non_sensitive_key_returned_unchanged(self):
            self.assertEqual(_masked_for_log('DB_HOST', 'server01'), 'server01')

        def test_none_value_returned_as_none(self):
            self.assertIsNone(_masked_for_log('DB_PASSWORD', None))

        def test_password_key_masked(self):
            result = _masked_for_log('DB_PASSWORD', 'secret123')
            self.assertEqual(result, 's_redatcted_3')

        def test_api_key_masked(self):
            result = _masked_for_log('API_KEY', 'abcdefgh')
            self.assertEqual(result, 'a_redatcted_h')

        def test_single_char_sensitive_value(self):
            result = _masked_for_log('MY_PASSWORD', 'x')
            self.assertEqual(result, '_redatcted_')

        def test_two_char_sensitive_value(self):
            result = _masked_for_log('MY_PASSWORD', 'ab')
            self.assertEqual(result, 'a_redatcted_b')

        def test_case_insensitive_key_matching(self):
            result = _masked_for_log('db_passWORD', 'secret123')
            self.assertEqual(result, 's_redatcted_3')


    class TestMaskSensitiveValues(unittest.TestCase):

        def test_sensitive_keys_are_masked(self):
            data = {'DB_PASSWORD': 'secret99', 'DB_HOST': 'server01'}
            result = _mask_sensitive_values(data)
            self.assertEqual(result['DB_PASSWORD'], 's_redatcted_9')
            self.assertEqual(result['DB_HOST'], 'server01')

        def test_none_value_becomes_empty_string_masked(self):
            data = {'API_KEY': None}
            result = _mask_sensitive_values(data)
            # None becomes '' which is length 0 — masked as _redatcted_
            self.assertEqual(result['API_KEY'], '_redatcted_')

        def test_returns_new_dict_not_original(self):
            data = {'DB_HOST': 'server01'}
            result = _mask_sensitive_values(data)
            self.assertIsNot(result, data)


    class TestReadEnvParm(unittest.TestCase):

        def test_existing_env_var_returned(self):
            os.environ['_TEST_READ_ENV_VAR'] = 'hello'
            self.assertEqual(read_env_parm('_TEST_READ_ENV_VAR'), 'hello')
            del os.environ['_TEST_READ_ENV_VAR']

        def test_missing_var_no_default_returns_none(self):
            os.environ.pop('_TEST_MISSING_VAR', None)
            self.assertIsNone(read_env_parm('_TEST_MISSING_VAR'))

        def test_missing_var_with_default_file_returns_file_content(self):
            os.environ.pop('_TEST_MISSING_VAR', None)
            with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as tmp:
                tmp.write('  default_value  ')
                tmp_path = tmp.name
            try:
                result = read_env_parm('_TEST_MISSING_VAR', default_file_path=tmp_path)
                self.assertEqual(result, 'default_value')
            finally:
                os.remove(tmp_path)

        def test_missing_var_with_missing_default_file_returns_none(self):
            os.environ.pop('_TEST_MISSING_VAR', None)
            result = read_env_parm('_TEST_MISSING_VAR', default_file_path='/nonexistent/path/file.txt')
            self.assertIsNone(result)


    class TestReadParFile(unittest.TestCase):

        def _write_temp_par(self, content):
            tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.par', delete=False)
            tmp.write(content)
            tmp.close()
            return tmp.name

        def test_key_equals_value_format(self):
            path = self._write_temp_par('DB_HOST=server01\nDB_PORT=5432\n')
            try:
                result = read_par_file(path)
                self.assertEqual(result['DB_HOST'], 'server01')
                self.assertEqual(result['DB_PORT'], '5432')
            finally:
                os.remove(path)

        def test_key_colon_value_format(self):
            path = self._write_temp_par('DB_HOST: server01\n')
            try:
                result = read_par_file(path)
                self.assertEqual(result['DB_HOST'], 'server01')
            finally:
                os.remove(path)

        def test_hash_comment_lines_skipped(self):
            path = self._write_temp_par('# this is a comment\nDB_HOST=server01\n')
            try:
                result = read_par_file(path)
                self.assertNotIn('# this is a comment', result)
                self.assertEqual(result['DB_HOST'], 'server01')
            finally:
                os.remove(path)

        def test_semicolon_comment_lines_skipped(self):
            path = self._write_temp_par('; another comment\nDB_HOST=server01\n')
            try:
                result = read_par_file(path)
                self.assertEqual(len(result), 1)
            finally:
                os.remove(path)

        def test_blank_lines_skipped(self):
            path = self._write_temp_par('\n\nDB_HOST=server01\n\n')
            try:
                result = read_par_file(path)
                self.assertEqual(len(result), 1)
            finally:
                os.remove(path)

        def test_sensitive_value_present_in_returned_dict(self):
            # Masking is only for logs; returned dict must have the original value.
            path = self._write_temp_par('DB_PASSWORD=secret123\n')
            try:
                result = read_par_file(path)
                self.assertEqual(result['DB_PASSWORD'], 'secret123')
            finally:
                os.remove(path)

        def test_missing_file_returns_empty_dict(self):
            result = read_par_file('/nonexistent/path/job.par')
            self.assertEqual(result, {})

        def test_none_path_returns_empty_dict(self):
            result = read_par_file(None)
            self.assertEqual(result, {})

        def test_malformed_line_skipped_rest_parsed(self):
            path = self._write_temp_par('GOOD_KEY=good_value\nBAD LINE NO DELIMITER\n')
            try:
                result = read_par_file(path)
                self.assertIn('GOOD_KEY', result)
                self.assertNotIn('BAD LINE NO DELIMITER', result)
            finally:
                os.remove(path)


    class TestCheckVirtualEnv(unittest.TestCase):

        def test_returns_dict(self):
            result = check_virtual_env()
            self.assertIsInstance(result, dict)

        def test_contains_runtime_keys(self):
            result = check_virtual_env()
            for key in ('RUNNING_USER', 'HOSTNAME', 'OS_NAME', 'OS_RELEASE', 'OS_VERSION'):
                self.assertIn(key, result)

        def test_running_user_is_non_empty(self):
            result = check_virtual_env()
            self.assertTrue(result['RUNNING_USER'])

        def test_hostname_is_non_empty(self):
            result = check_virtual_env()
            self.assertTrue(result['HOSTNAME'])


    class TestJsonOutputForLog(unittest.TestCase):

        def test_creates_valid_json_file(self):
            with tempfile.TemporaryDirectory() as tmp_dir:
                output_path = os.path.join(tmp_dir, 'snapshot.json')
                result = json_output_for_log(output_path, include_full_env=False)
                self.assertTrue(result)
                self.assertTrue(os.path.isfile(output_path))
                with open(output_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self.assertIn('timestamp_utc', data)
                self.assertIn('python_executable', data)
                self.assertIn('runtime_summary', data)

        def test_full_env_included_when_requested(self):
            with tempfile.TemporaryDirectory() as tmp_dir:
                output_path = os.path.join(tmp_dir, 'snapshot.json')
                json_output_for_log(output_path, include_full_env=True)
                with open(output_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self.assertIn('all_environment_variables', data)

        def test_full_env_excluded_when_not_requested(self):
            with tempfile.TemporaryDirectory() as tmp_dir:
                output_path = os.path.join(tmp_dir, 'snapshot.json')
                json_output_for_log(output_path, include_full_env=False)
                with open(output_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self.assertNotIn('all_environment_variables', data)

        def test_returns_false_on_bad_path(self):
            result = json_output_for_log('/root/no_permission_here/snapshot.json')
            self.assertFalse(result)


    unittest.main(verbosity=2)

