# python 3.7

# =============================================================================
# PSEUDOCODE - HOW TO USE THIS MODULE
# =============================================================================
#
# PURPOSE:
#   Shared utility helpers for Windows/UNC style job automation tasks:
#     - build rotating log file names
#     - map/remove network drives
#     - move/rename files safely
#     - delete old files by extension and age
#     - create zip archives
#     - run shell commands and capture output
#     - check free disk space in GB
#
# TYPICAL FLOW IN A JOB:
#   1) logfile_name = splitlog('job_name', daysplit=6)
#   2) mapdrive('\\server\\share', 'Z', username='DOMAIN\\user', passwd='***')
#   3) movefile(start_dir, end_dir, 'input.txt', 'output.txt')
#   4) delete_old_files(log_dir, delete_older_days=14, file_extension='.log')
#   5) zip_writer(['/path/a.log', '/path/b.log'], '/path/archive.zip', delete_old=False)
#   6) free_gb = free_space_gb('Z:\\')
#   7) removedrive('Z')
#
# NOTES:
#   - This module uses built-in Python logging/prints only.
#   - mapdrive/removedrive and run_win_cmd return shell command exit codes or
#     outputs so callers can react to failures.
#
# =============================================================================

import shutil
import subprocess
import datetime
import os
import logging
# non-standard
import zipfile

try:
    import config
except ModuleNotFoundError:
    config = None

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

if config is not None:
    logfile = config.log.get('logfile', 'unc_util.log')
    logpath = config.log.get('logpath', '.')
else:
    logfile = 'unc_util.log'
    logpath = '.'


# creates a logfile name variable to track the messages used in the log script
# breaks it up by number of days in daysplit
def splitlog(logname=None, daysplit=6):
    """Build a time-windowed log filename.

    Why: Jobs that run frequently need deterministic log naming so operators can
    quickly locate logs by week/day boundaries.
    """
    day = datetime.datetime.now().strftime('%d%b%Y')
    dt = datetime.datetime.strptime(day, '%d%b%Y')
    start1 = dt - datetime.timedelta(days=dt.weekday())
    end1 = start1 + datetime.timedelta(days=daysplit)
    if daysplit == 0:
        startday = datetime.datetime.strftime(start1, '%d%b%Y')
        logfile_name = f'{logname}_{startday}.log'
    else:
        startday = datetime.datetime.strftime(start1, '%d%b%Y')
        endday = datetime.datetime.strftime(end1, '%d%b%Y')
        logfile_name = f'{logname}_{startday}_to_{endday}.log'
    return logfile_name


# maps a drive to the needed path to allow for moving of files and logs the action
def mapdrive(path, driveletter, username=None, passwd=None):
    """Map a Windows drive letter to a UNC/network path.

    Why: Some downstream tooling expects drive letters rather than UNC paths.
    Returns the shell exit code from `net use`.
    """
    if username is None and passwd is None:
        result_code = subprocess.call(f'net use {driveletter}: {path}', shell=True)
        message_no_pass = f'Mapping {driveletter}: as {path}.'
        print(message_no_pass)
        logger.info(message_no_pass)
    else:
        result_code = subprocess.call(f'net use {driveletter}: {path} /user:{username} {passwd}', shell=True)
        message_pass = f'Mapping {driveletter}: as {path} using {username}.'
        print(message_pass)
        logger.info(message_pass)
    return result_code


# deletes a drive after it is no longer needed
def removedrive(driveletter):
    """Remove a mapped Windows drive letter.

    Why: Jobs should clean up mapped drives to avoid stale mappings and conflicts.
    Returns the shell exit code from `net use /delete`.
    """
    result_code = subprocess.call(f'net use {driveletter}: /delete', shell=True)
    message_remove = f'Deleting {driveletter}: drive.'
    print(message_remove)
    logger.info(message_remove)
    return result_code


# moves/renames a file and writes a message to a log file
def movefile(file_start_path, file_end_path, filename_start, filename_end=None):
    """Move a file, optionally renaming it.

    Why: Prevent accidental overwrite by timestamp-renaming if destination exists.
    """
    filename_start_path = os.path.join(file_start_path, filename_start)
    if filename_end is None:
        filename_end = filename_start
    filename_end_path = os.path.join(file_end_path, filename_end)
    try:
        if os.path.isfile(filename_end_path):
            filename_end_new = f"{datetime.datetime.strftime(datetime.datetime.now(), '%dT%H%M_%S')} {filename_end}"
            filename_end_path_new = os.path.join(file_end_path, filename_end_new)
            shutil.move(filename_start_path, filename_end_path_new)
            message_rename = f'Renaming {filename_start_path} and moving to {filename_end_path_new}.'
            print(message_rename)
            logger.info(message_rename)
        else:
            shutil.move(filename_start_path, filename_end_path)
            message_move = f'Moving {filename_start_path} to {filename_end_path}.'
            print(message_move)
            logger.info(message_move)
    except FileNotFoundError:
        message_none = f'File {filename_start} not found.'
        print(message_none)
        logger.error(message_none)


def delete_old_files(delete_path, delete_older_days, file_extension):
    """
    Will look at the modified date on a file and delete files older then old_older_days number by file type.\
    Will log to log file.
    :param delete_path: Location of where to delete files
    :param delete_older_days: Number of days that
    :param file_extension: file type to be deleted
    :return: returns to the logs if a matched file is deleted or not deleted"""
    deleted_count = 0
    kept_count = 0
    delete_files = [file_name for file_name in os.listdir(delete_path) if file_name.endswith(file_extension)]
    for file_name in delete_files:
        file_path_name_delete = os.path.join(delete_path, file_name)
        modified_date = datetime.datetime.fromtimestamp(os.path.getmtime(file_path_name_delete))
        duration = datetime.datetime.today() - modified_date
        if duration.days > delete_older_days:
            os.remove(file_path_name_delete)
            deleted_count += 1
            message_delete = f'{file_name} deleted'
            print(message_delete)
            logger.info(message_delete)
        else:
            kept_count += 1
            message_keep = f'{file_name} not deleted'
            print(message_keep)
            logger.info(message_keep)
    return {'deleted': deleted_count, 'kept': kept_count, 'checked': len(delete_files)}


def zip_writer(to_zip, zip_filename, delete_old=True):
    """Write a zip archive from input files.

    Why: Job outputs are often easier to ship/retain as one archive.
    """
    if to_zip:
        with zipfile.ZipFile(zip_filename, 'w') as zipper:
            zip_message = f'Files to zip: {to_zip} creating {zip_filename}'
            print(zip_message)
            logger.info(zip_message)
            for file_path in to_zip:
                zipper.write(file_path, arcname=os.path.basename(file_path), compress_type=zipfile.ZIP_DEFLATED)
                if delete_old:
                    delete_message = f'{file_path} deleted.'
                    print(delete_message)
                    logger.info(delete_message)
                    os.remove(file_path)
    else:
        zip_message = 'No files found'
        print(zip_message)
        logger.info(zip_message)


def run_win_cmd(cmd):
    """Run a shell command and return stdout lines.

    Why: Centralized execution gives consistent failure behavior for automation
    jobs and avoids silent command failures.
    """
    process = subprocess.Popen(
        cmd,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    stdout_text, stderr_text = process.communicate()
    stdout_lines = stdout_text.splitlines()
    stderr_lines = stderr_text.splitlines()

    for output_line in stdout_lines:
        print(output_line)
        logger.debug(output_line)

    if process.returncode != 0:
        for error_line in stderr_lines:
            print(error_line)
            logger.error(error_line)
        cmd_message = 'Command failed'
        print(cmd_message)
        logger.error(cmd_message)
        raise Exception(f'cmd {cmd} failed, see above for details')

    return stdout_lines


def free_space_gb(path):
    """
    This retuns the amount of free space from a location in gigabytes
    :param path: the location to check
    :return: the amount of free space in gigabytes
    """
    normalized_path = os.path.join(path)
    total_bytes, used_bytes, free_bytes = shutil.disk_usage(os.path.realpath(normalized_path))
    free_gb = round(free_bytes / 1073741824, 2)
    return free_gb


def _run_self_tests():
    """Run lightweight local tests for core utility behavior.

    Why: Quick validation in job-host environments helps catch regressions when
    no external test runner is configured.
    """
    import tempfile
    import unittest

    class UncUtilTests(unittest.TestCase):
        def test_splitlog_daily_format(self):
            log_name = splitlog('testjob', daysplit=0)
            self.assertTrue(log_name.startswith('testjob_'))
            self.assertTrue(log_name.endswith('.log'))
            self.assertNotIn('_to_', log_name)

        def test_splitlog_range_format(self):
            log_name = splitlog('testjob', daysplit=6)
            self.assertTrue(log_name.startswith('testjob_'))
            self.assertIn('_to_', log_name)
            self.assertTrue(log_name.endswith('.log'))

        def test_movefile_moves_file(self):
            with tempfile.TemporaryDirectory() as start_dir, tempfile.TemporaryDirectory() as end_dir:
                source_name = 'source.txt'
                source_path = os.path.join(start_dir, source_name)
                with open(source_path, 'w', encoding='utf-8') as source_handle:
                    source_handle.write('hello')

                movefile(start_dir, end_dir, source_name)

                self.assertFalse(os.path.exists(source_path))
                self.assertTrue(os.path.exists(os.path.join(end_dir, source_name)))

        def test_delete_old_files_summary(self):
            with tempfile.TemporaryDirectory() as temp_dir:
                old_file = os.path.join(temp_dir, 'old.log')
                new_file = os.path.join(temp_dir, 'new.log')

                with open(old_file, 'w', encoding='utf-8') as old_handle:
                    old_handle.write('old')
                with open(new_file, 'w', encoding='utf-8') as new_handle:
                    new_handle.write('new')

                ten_days_ago = datetime.datetime.now() - datetime.timedelta(days=10)
                os.utime(old_file, (ten_days_ago.timestamp(), ten_days_ago.timestamp()))

                summary = delete_old_files(temp_dir, delete_older_days=7, file_extension='.log')

                self.assertEqual(summary['checked'], 2)
                self.assertEqual(summary['deleted'], 1)
                self.assertEqual(summary['kept'], 1)
                self.assertFalse(os.path.exists(old_file))
                self.assertTrue(os.path.exists(new_file))

        def test_zip_writer_keeps_source_when_delete_old_false(self):
            with tempfile.TemporaryDirectory() as temp_dir:
                source_file = os.path.join(temp_dir, 'sample.txt')
                zip_file = os.path.join(temp_dir, 'sample.zip')

                with open(source_file, 'w', encoding='utf-8') as source_handle:
                    source_handle.write('zip me')

                zip_writer([source_file], zip_file, delete_old=False)

                self.assertTrue(os.path.exists(zip_file))
                self.assertTrue(os.path.exists(source_file))
                with zipfile.ZipFile(zip_file, 'r') as zip_handle:
                    self.assertEqual(zip_handle.namelist(), ['sample.txt'])

        def test_run_win_cmd_success(self):
            output_lines = run_win_cmd('python -c "print(12345)"')
            self.assertIn('12345', output_lines)

        def test_free_space_gb_returns_number(self):
            free_gb = free_space_gb('.')
            self.assertIsInstance(free_gb, float)
            self.assertGreaterEqual(free_gb, 0.0)

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(UncUtilTests)
    return unittest.TextTestRunner(verbosity=2).run(suite)


if __name__ == '__main__':
    if '--run-tests' in os.sys.argv:
        test_result = _run_self_tests()
        raise SystemExit(0 if test_result.wasSuccessful() else 1)

    print('unc_util module loaded. Use --run-tests to execute built-in tests.')

