def chunk_string(s: str, size: int = 2000):
    return [s[i:i+size] for i in range(0, len(s), size)]

import re as _dre

_DURATION_RE = _dre.compile(r'(\d+)\s*(w|week|weeks|d|day|days|h|hr|hour|hours|m|min|mins|minute|minutes|s|sec|secs|second|seconds)', _dre.IGNORECASE)

_DURATION_UNITS = {
    'w': 604800, 'week': 604800, 'weeks': 604800,
    'd': 86400, 'day': 86400, 'days': 86400,
    'h': 3600, 'hr': 3600, 'hour': 3600, 'hours': 3600,
    'm': 60, 'min': 60, 'mins': 60, 'minute': 60, 'minutes': 60,
    's': 1, 'sec': 1, 'secs': 1, 'second': 1, 'seconds': 1,
}

def parse_duration(text: str) -> int:
    total = 0
    for amount, unit in _DURATION_RE.findall(text or ''):
        total += int(amount) * _DURATION_UNITS[unit.lower()]
    return total

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

_CLOCK_RE = _dre.compile(r'^\s*(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s*$', _dre.IGNORECASE)

def seconds_until(text: str, now_utc: datetime, tz_name: str = 'UTC') -> int:
    relative = parse_duration(text)
    if relative > 0:
        return relative

    match = _CLOCK_RE.match(text or '')
    if not match:
        return 0

    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    meridiem = (match.group(3) or '').lower()
    if meridiem == 'pm' and hour < 12:
        hour += 12
    elif meridiem == 'am' and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        return 0

    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo('UTC')

    local_now = now_utc.astimezone(tz)
    target = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= local_now:
        target += timedelta(days=1)

    return int((target - local_now).total_seconds())

import re as _re

_MASS_MENTION_RE = _re.compile(r'@(everyone|here)')

def neutralize_mass_mentions(text: str) -> str:
    return _MASS_MENTION_RE.sub(r'\1', text)

_ROLE_MENTION_RE = _re.compile(r'<@&([0-9]{15,20})>')

def sanitize_role_mentions(text: str, guild, channel, member, allow_everyone: bool = False):
    if guild is None or member is None:
        return text, []

    try:
        can_mention_any = channel.permissions_for(member).mention_everyone
    except Exception:
        can_mention_any = False

    allowed_roles = []

    def repl(match):
        rid = int(match.group(1))
        role = guild.get_role(rid)
        if role is None:
            return match.group(0)

        if rid == guild.id or getattr(role, 'is_default', lambda: False)():
            if allow_everyone:
                return match.group(0)
            return 'everyone'

        if role.mentionable or can_mention_any:
            allowed_roles.append(role)
            return match.group(0)
        return '@' + role.name

    return _ROLE_MENTION_RE.sub(repl, text), allowed_roles



def indent(text, spaces):
    prefix = " " * spaces
    return '\n'.join(prefix + line for line in text.splitlines())

import discord
import re

def clean(message: discord.Message):
    if message.guild:

        def resolve_member(id: int) -> str:
            m = message.guild.get_member(id) or discord.utils.get(message.mentions, id=id)
            return f'@{m.display_name}' if m else '@deleted-user'

        def resolve_role(id: int) -> str:
            r = message.guild.get_role(id) or discord.utils.get(message.role_mentions, id=id)
            return f'@{r.name}' if r else '@deleted-role'

        def resolve_channel(id: int) -> str:
            c = message.guild._resolve_channel(id)
            return f'#{c.name}' if c else '#deleted-channel'

    else:

        def resolve_member(id: int) -> str:
            m = discord.utils.get(message.mentions, id=id)
            return f'@{m.display_name}' if m else '@deleted-user'

        def resolve_role(id: int) -> str:
            return '@deleted-role'

        def resolve_channel(id: int) -> str:
            return '#deleted-channel'

    transforms = {
        '@': resolve_member,
        '@!': resolve_member,
        '#': resolve_channel,
        '@&': resolve_role,
    }

    def repl(match: re.Match) -> str:
        type = match[1]
        id = int(match[2])
        transformed = transforms[type](id) + f' (ID: {id})'
        return transformed

    result = re.sub(r'<(@[!&]?|#)([0-9]{15,20})>', repl, message.content)

    return discord.utils.escape_mentions(result)