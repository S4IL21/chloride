import re

_INVITE_RE = re.compile(r'(discord\.gg/|discord(app)?\.com/invite/|discord\.me/)', re.IGNORECASE)
_MENTION_RE = re.compile(r'<@[!&]?\d+>')


def _caps_ratio(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    if len(letters) < 8:
        return 0.0
    uppers = sum(1 for c in letters if c.isupper())
    return uppers / len(letters)


def check(config, message) -> dict | None:
    content = message.content or ''
    lowered = content.lower()

    for word in (config.AUTOMOD_BANNED_WORDS or []):
        if word and word.lower() in lowered:
            return {'reason': 'banned word', 'delete': True, 'timeout_seconds': config.AUTOMOD_TIMEOUT_SECONDS}

    if config.AUTOMOD_BLOCK_INVITES and _INVITE_RE.search(content):
        return {'reason': 'invite link', 'delete': True, 'timeout_seconds': config.AUTOMOD_TIMEOUT_SECONDS}

    if config.AUTOMOD_MAX_MENTIONS and len(_MENTION_RE.findall(content)) > config.AUTOMOD_MAX_MENTIONS:
        return {'reason': 'mention spam', 'delete': True, 'timeout_seconds': config.AUTOMOD_TIMEOUT_SECONDS}

    if config.AUTOMOD_MAX_CAPS_RATIO and _caps_ratio(content) > config.AUTOMOD_MAX_CAPS_RATIO:
        return {'reason': 'excessive caps', 'delete': False, 'timeout_seconds': 0}

    return None
