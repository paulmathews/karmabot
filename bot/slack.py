from collections import namedtuple
import logging
import os
from slack import RTMClient
from . import KARMA_BOT, SLACK_CLIENT, USERNAME_CACHE, CONFIG

# bot commands
from commands.ban import ban_user, unban_user, unban_all
from commands.help import create_commands_table
from commands.score import get_karma, top_karma
from commands.dice import roll

Message = namedtuple('Message', 'giverid channel text')
GENERAL_CHANNEL = CONFIG['GENERAL_CHANNEL_ID']
ADMINS = CONFIG['ADMINS']
TEXT_FILTER_REPLIES = CONFIG['TEXT_FILTER_REPLIES']
ADMIN_COMMANDS = {}
USER_COMMANDS = {}

for key, value in CONFIG['ADMIN_COMMANDS'].items():
    logging.debug("unpacking {0} admin command".format(key))
    ADMIN_COMMANDS[key] = eval(value)
for key, value in CONFIG['USER_COMMANDS'].items():
    logging.debug("unpacking {0} user command".format(key))
    USER_COMMANDS[key] = eval(value)
logging.debug(ADMIN_COMMANDS)
logging.debug(USER_COMMANDS)


def create_help_msg(is_admin):
    bot = KARMA_BOT
    help_msg = []
    help_msg.append('\nMessage commands (DM {0} typing `command`)'.format(
        bot))
    help_msg.append(create_commands_table(USER_COMMANDS))
    if is_admin:
        help_msg.append('\nAdmin commands')
        help_msg.append(create_commands_table(ADMIN_COMMANDS))
    return '\n'.join(help_msg)


def lookup_username(userid):
    user = userid.strip('<>@')
    username = USERNAME_CACHE.get(user)
    if not username:
        userinfo = SLACK_CLIENT.api_call("users.info", user=user)
        username = userinfo['user']['name']
        USERNAME_CACHE[user] = username
    return username


def post_msg(channel_or_user, text):
    logging.debug('posting to {}'.format(channel_or_user))
    logging.debug(text)
    SLACK_CLIENT.api_call("chat.postMessage",
                          channel=channel_or_user,
                          text=text,
                          link_names=True,  # convert # and @ in links
                          as_user=True,
                          unfurl_links=False,
                          unfurl_media=False)


def _get_cmd(text, private=True):
    if private:
        return text.split()[0].strip().lower()
    # TODO: Botname should be pulled from config
    if not text.strip('<>@').startswith(KARMA_BOT):
        return None
    if text.strip().count(' ') < 1:
        return None
    cmd = text.split()[1]
    if cmd.startswith(('+', '-')):
        return None
    return cmd.strip().lower()


def perform_bot_cmd(msg, private=True):
    """Parses message and perform valid bot commands"""
    user = msg.get('user')
    userid = user and user.strip('<>@')
    is_admin = userid and userid in ADMINS
    channel = msg.get('channel')
    text = msg.get('text')
    command_set = private and USER_COMMANDS
    cmd = text and _get_cmd(text, private=private)
    if not cmd:
        return None
    if cmd == 'help':
        return create_help_msg(is_admin)
    command = command_set.get(cmd)
    if private and is_admin and cmd in ADMIN_COMMANDS:
        command = ADMIN_COMMANDS.get(cmd)
    if not command:
        return None
    kwargs = dict(user=lookup_username(user),
                  channel=channel,
                  text=text)
    return command(**kwargs)


def perform_text_replacements(text):
    """Replace first matching word in text with a little easter egg"""
    words = text.lower().split()
    strip_chars = '?!'
    matching_words = [word.strip(strip_chars) for word in words
                      if word.strip(strip_chars) in TEXT_FILTER_REPLIES]
    if not matching_words:
        return None
    match_word = matching_words[0]
    replace_word = TEXT_FILTER_REPLIES.get(match_word)
    return 'To _{}_ I say: {}'.format(match_word, replace_word)


def parse_next_msg():
    """Parse next message posted on slack for actions todo by bot"""
    msg = SLACK_CLIENT.rtm_read()
    if not msg:
        return None
    msg = msg[0]
    user = msg.get('user')
    channel = msg.get('channel')
    text = msg.get('text')
    type_event = msg.get('type')
    if type_event == 'channel_created':
        bot_joins_new_channel(msg)
        return None
    # TODO: investigate issue with getting random dictionaries.
    if (not isinstance(channel, str) or
       not isinstance(user, str) or
       not isinstance(text, str)):
        return None
    # Karma bot cant issue its own commands, we are ignoring karmabot
    if user == KARMA_BOT:
        return None
    text_replace_output = text and perform_text_replacements(text)
    if text_replace_output:
        post_msg(channel, text_replace_output)
    private = channel and channel.startswith('D')
    cmd_output = perform_bot_cmd(msg, private)
    if cmd_output:
        post_msg(channel, cmd_output)
        return None
    if not channel or not text:
        return None
    return Message(giverid=user, channel=channel, text=text)
