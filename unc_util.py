# python 3.7
import shutil
import subprocess
import datetime
import os
# non-standard
import zipfile
import config

# bear-lib
# from bearlib.logging import core, webhooks
# logging stuff

logfile = config.log["logfile"]
logpath = config.log['logpath']
teamsURL = config.teams['webhook']
# bearLogger = core.Logger(level="DEBUG", echo=True, write=True, directory=logpath, filename=logfile)
'''teams = webhooks.Teams(
    hook_url=teamsURL,
    summary="Oracle Connection",
    notify_only=False,
    subtitle="Logs are in Appworx"
    )
bearLogger.add_webhook(teams)'''
# bearLogger.change_path(directory=logpath, filename=logfile)


# creates a logfile name variable to track the messages used in the log script
# breaks it up by number of days in daysplit
def splitlog(logname=None, daysplit=6):
    day = datetime.datetime.now().strftime('%d%b%Y')
    dt = datetime.datetime.strptime(day, '%d%b%Y')
    start1 = dt - datetime.timedelta(days=dt.weekday())
    end1 = start1 + datetime.timedelta(days=daysplit)
    if daysplit is 0:
        startday = datetime.datetime.strftime(start1, '%d%b%Y')
        logfile_name = f'{logname}_{startday}.log'
    else:
        startday = datetime.datetime.strftime(start1, '%d%b%Y')
        endday = datetime.datetime.strftime(end1, '%d%b%Y')
        logfile_name = f'{logname}_{startday}_to_{endday}.log'
    return logfile_name


# maps a drive to the needed path to allow for moving of files and logs the action
def mapdrive(path, driveletter, username=None, passwd=None):
    if username is None and passwd is None:
        subprocess.call(f'net use {driveletter}: {path}')
        message_no_pass = f'Mapping {driveletter}: as {path}.'
        # bearLogger.log('INFO', message_no_pass)
    else:
        subprocess.call(f'net use {driveletter}: {path} /user:{ username} {passwd}')
        message_pass = f'Mapping {driveletter}: as {path} using {username}.'
        # bearLogger.log('INFO', message_pass)


# deletes a drive after it is no longer needed
def removedrive(driveletter):
    subprocess.call(f'net use {driveletter}: /delete')
    message_remove = f'Deleting {driveletter}: drive.'
    # bearLogger.log('INFO', message_remove)


# moves/renames a file and writes a message to a log file
def movefile(file_start_path, file_end_path, filename_start, filename_end=None):
    filename_start_path = os.path.join(file_start_path, filename_start)
    if filename_end is None:
        filename_end = filename_start
    else:
        pass
    filename_end_path = os.path.join(file_end_path, filename_end)
    try:
        if os.path.isfile(filename_end_path):
            filename_end_new = f"{datetime.datetime.strftime(datetime.datetime.now(), '%dT%H%M_%S')} {filename_end}"
            filename_end_path_new = os.path.join(file_end_path, filename_end_new)
            shutil.move(filename_start_path, filename_end_path_new)
            message_rename = f'Renaming {filename_start_path} and moving to {filename_end_path_new}.'
            try:
                print(message_rename)
                # bearLogger.log('INFO', message_rename)
            except NameError:
                print(message_rename)
        else:
            shutil.move(filename_start_path, filename_end_path)
            message_move = f'Moving {filename_start_path} to {filename_end_path}.'
            try:
                print(message_move)
                # bearLogger.log('INFO', message_move)
            except NameError:
                print(message_move)
    except FileNotFoundError:
        message_none = f'File {filename_start} not found.'
        try:
            print(message_none)
            # bearLogger.log('INFO', message_none)
        except NameError:
            print(message_none)


def delete_old_files(delete_path, delete_older_days, file_extension):
    """
    Will look at the modified date on a file and delete files older then old_older_days number by file type.\
    Will log to log file.
    :param delete_path: Location of where to delete files
    :param delete_older_days: Number of days that
    :param file_extension: file type to be deleted
    :return: returns to the logs if a matched file is deleted or not deleted"""
    delete_files = [f for f in os.listdir(delete_path) if f.endswith(file_extension)]
    for file in delete_files:
        file_path_name_delete = os.path.join(delete_path, file)
        modified_date = datetime.datetime.fromtimestamp(os.path.getmtime(file_path_name_delete))
        duration = datetime.datetime.today() - modified_date
        if duration.days > delete_older_days:
            os.remove(file_path_name_delete)
            message_delete = f'{file} + deleted'
            # bearLogger.log('INFO', message_delete)
        else:
            message_keep = f'{file} not deleted'
            # bearLogger.log('INFO', message_keep)


def zip_writer(to_zip, zip_filename, delete_old=True):
    if to_zip:
        with zipfile.ZipFile(zip_filename, 'w') as zipper:
            zip_message = f'Files to zip: {to_zip} creating {zip_filename}'
            # bearLogger.log('INFO', zip_message)
            for file in to_zip:
                zipper.write(file, compress_type=zipfile.ZIP_DEFLATED)
                if delete_old:
                    delete_message = f'{file} deleted.'
                    # bearLogger.log('INFO', delete_message)
                    os.remove(file)
                else:
                    pass
    else:
        zip_message = 'No files found'
        # bearLogger.log('INFO', zip_message)


def run_win_cmd(cmd):
    result = []
    process = subprocess.Popen(cmd,
                               shell=True,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE)
    for line in process.stdout:
        result.append(line)
    errcode = process.returncode
    for line in result:
        print('Error')
        # bearLogger.log('DEBUG', line)
    if errcode is not None:
        cmd_message = 'Command failed'
        # bearLogger.log('ERROR', cmd_message)
        raise Exception(f'cmd {cmd} failed, see above for details')


def free_space_gb(path):
    """
    This retuns the amount of free space from a location in gigabytes
    :param path: the location to check
    :return: the amount of free space in gigabytes
    """
    path = os.path.join(path)
    total_bytes, used_bytes, free_bytes = shutil.disk_usage(os.path.realpath(path))
    free_gb = round(free_bytes / 1073741824, 2)
    return free_gb

