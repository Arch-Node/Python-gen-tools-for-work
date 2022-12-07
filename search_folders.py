import os
import fnmatch
import datetime

search_item = '2223'  # the string you are searching for

location = '//itbpjs01/GDrive/sct/PROD/Dataload/'
fileType = '*6867812.l*'
fileContent = []


def locate(pattern, root=os.curdir):
    """Locate all files matching supplied filename pattern in and below supplied root directory."""
    for path, dirs, files in os.walk(os.path.abspath(root)):
        for filename in fnmatch.filter(files, pattern):
            ret = os.path.join(path, filename)
            yield ret


print('search item: ' + search_item)
for filename in locate(fileType, location):
    print(filename)
    try:
        with open(filename) as f:
            content = f.read().splitlines()
            with open('search.txt', 'a+') as isirCombined:
                for line_number, line in enumerate(content, 1):
                    if search_item in line:
                        isirCombined.write('File: ' + str(filename) + ' Looking for: ' + search_item + '\n')
                        isirCombined.write(str(line_number) + ' - ' + str(line) + '\n')
                        print(filename + ' - ' + line)
            fileContent.append(content)
    except UnicodeDecodeError:
        print(f'Cannot read file: {filename}')
        pass
with open('search.txt', 'a+') as writeLine:
    now = datetime.datetime.now().strftime('%d%b%Y %H:%M:%S')
    writeLine.write(f'---------Finished Search: {location} {now} ---------' + '\n')
