import requests
import json
import datetime


def add_teams_message(message, message_tag, message_list):
    """
    Adds a time stamped message to a list to send to MS Teams.
    :param message: Message body
    :param message_tag: Message sub-title
    :param message_list: Python list to add the formatted Teams message
    """
    current_time = datetime.datetime.now().strftime('%d%b%Y %H:%M:%S')
    item = {
        'name': message_tag,
        'value': f"{current_time}:{message}"
    }
    message_list.append(item)


def send_teams_message(webhook_url, message_dict):
    """
    Sends message to given Microsoft Teams group channel.
    :param webhook_url: url of the Teams Incoming Webhook
    :param message_dict: a dictionary formatted for the teams message

    teams_message = {
            "@type": "MessageCard",
            "summary": 'python_message',
            "sections": [{
                "activityTitle": '*Teams Generic Message*',
                "activitySubtitle": None,
                "facts": list of messages,
                "markdown": True
            }],
        }

    :return: 200 = good, 400 = bad

    """
    headers = {"Content-Type": "application/json"}
    r = requests.post(webhook_url, headers=headers, data=json.dumps(message_dict))
    return r


if __name__ == '__main__':
    message_holder = []
    web_hook = f'https://outlook.office.com/webhook/ff133227-da6e-4397-aa17-be2e93e93009@b4dce27c-d088-4454-9965-2b59a23ea171/' \
        f'IncomingWebhook/40a538ed7c474ea98636d92edc0319bf/595e08fc-4e07-4b2a-9cb1-c867de64429c'
    teams_message = {
            "@type": "MessageCard",
            "summary": 'python_message',
            "sections": [{
                "activityTitle": '*Teams Generic Message*',
                "activitySubtitle": None,
                "facts": message_holder,
                "markdown": True
            }],
        }
    message1 = 'This is a message.'
    message2 = 'This is a second message.'
    add_teams_message(message1, 'U-235', message_holder)
    add_teams_message(message2, 'U-238', message_holder)
    test_message = send_teams_message(web_hook, teams_message)
    print(test_message)
