from pydantic import BaseModel
from pathlib import Path
from typing import *
from enum import Enum
import yaml


SAFE_TOOLS = ['duckduckgo_search', 'search_discord', 'get_user_info', 'get_channel_info', 'get_server_info', 'read_channel_history', 'get_time']

ADMIN_TOOLS = SAFE_TOOLS + ['run_shell', 'run_code', 'analyse_file', 'trigger_reboot', 'purge_messages', 'kick_member', 'ban_member', 'timeout_member', 'add_role', 'remove_role', 'send_message', 'set_channel_topic']


class Mode(str, Enum):
    SERVER = 'server'
    MANAGEMENT = 'management'


class HistoryScope(str, Enum):
    CHANNEL = 'channel'
    USER = 'user'
    CHANNEL_USER = 'channel_user'
    GLOBAL = 'global'


class Tier(BaseModel):
    allowed_roles_or_user_ids: Optional[List[int]] = None
    allowed_tools: List[str] = []
    allow_chat: bool = True
    allow_ping_everyone: bool = False
    is_admin: bool = False

    def can_use_tool(self, tool_name: str) -> bool:
        return '*' in self.allowed_tools or tool_name in self.allowed_tools


class Config(BaseModel):
    DISCORD_TOKEN: Optional[str] = None
    DISCORD_PREFIX: str = '-- '
    DISCORD_ALLOWED_USER_OR_ROLE_IDS: Optional[List[int]] = None
    tiers: Optional[Dict[str, Tier]] = None

    MODE: Mode = Mode.SERVER
    ADMIN_ROLE_OR_USER_IDS: Optional[List[int]] = None
    AUTO_REPLY_CHANNEL_IDS: List[int] = []

    HISTORY_SCOPE: HistoryScope = HistoryScope.CHANNEL
    PRIVATE_CHANNEL_IDS: List[int] = []
    SHARED_CHANNEL_IDS: List[int] = []
    SHARE_GROUPS: List[List[int]] = []

    ENABLE_SAFETY: bool = True
    BLOCKED_USER_IDS: List[int] = []
    RATE_LIMIT_PER_MINUTE: int = 0
    ENABLE_OUTPUT_JUDGE: bool = False
    CONFIRM_DANGEROUS_TOOLS: bool = True
    CONFIRM_TOOLS: List[str] = ['run_shell', 'run_code']

    WELCOME_CHANNEL_ID: Optional[int] = None
    WELCOME_MESSAGE: Optional[str] = None
    GOODBYE_MESSAGE: Optional[str] = None

    ENABLE_XP: bool = False
    XP_PER_MESSAGE: int = 15
    XP_COOLDOWN_SECONDS: int = 60
    XP_ANNOUNCE_LEVELUP: bool = True
    XP_LEVELUP_CHANNEL_ID: Optional[int] = None

    ENABLE_AUTOMOD: bool = False
    AUTOMOD_BANNED_WORDS: List[str] = []
    AUTOMOD_BLOCK_INVITES: bool = True
    AUTOMOD_MAX_MENTIONS: int = 0
    AUTOMOD_MAX_CAPS_RATIO: float = 0.0
    AUTOMOD_TIMEOUT_SECONDS: int = 0

    DEFAULT_TIMEZONE: str = 'UTC'

    AI_MODEL_NAME: str
    AI_API_KEY: Optional[str] = None
    AI_OPENAI_COMPATIBLE_BASE_URL: Optional[str] = None
    AI_EXTRA_CONTEXT_PATH: str = 'config.md.j2'
    AI_EXTRA_CONFIG: dict[str, Any] = {}

    DB_PATH: str = 'sqlite:///memory.db'

    def is_admin_user(self, user_id: int, role_ids: Optional[Iterable[int]] = None) -> bool:
        ids = set(self.ADMIN_ROLE_OR_USER_IDS or [])
        if not ids:
            return False
        candidate_ids = {user_id, *(role_ids or [])}
        return bool(candidate_ids.intersection(ids))

    def level_for_xp(self, xp: int) -> int:
        level = 0
        while xp >= self.xp_for_level(level + 1):
            level += 1
        return level

    def xp_for_level(self, level: int) -> int:
        return 5 * level * level + 50 * level

    def is_blocked(self, user_id: int, role_ids: Optional[Iterable[int]] = None) -> bool:
        ids = set(self.BLOCKED_USER_IDS or [])
        if not ids:
            return False
        return bool({user_id, *(role_ids or [])}.intersection(ids))

    def _share_group_key(self, user_id: int) -> Optional[str]:
        for index, group in enumerate(self.SHARE_GROUPS or []):
            if user_id in group:
                return f'group:{index}'
        return None

    def resolve_history_key(self, channel_id: int, user_id: int) -> str:
        if channel_id in (self.PRIVATE_CHANNEL_IDS or []):
            return f'channel:{channel_id}:user:{user_id}'

        if channel_id in (self.SHARED_CHANNEL_IDS or []):
            return f'channel:{channel_id}'

        group = self._share_group_key(user_id)
        if group is not None:
            return group

        scope = self.HISTORY_SCOPE
        if scope == HistoryScope.USER:
            return f'user:{user_id}'
        if scope == HistoryScope.CHANNEL_USER:
            return f'channel:{channel_id}:user:{user_id}'
        if scope == HistoryScope.GLOBAL:
            return 'global'
        return f'channel:{channel_id}'

    def resolve_tier(self, user_id: int, role_ids: Optional[Iterable[int]] = None) -> Optional[Tier]:
        if not self.tiers:
            return None

        candidate_ids = {user_id, *(role_ids or [])}

        for name, tier in self.tiers.items():
            if name == 'default':
                continue
            ids = tier.allowed_roles_or_user_ids
            if ids and candidate_ids.intersection(ids):
                return tier

        return self.tiers.get('default') or Tier()

    def access_for(self, user_id: int, role_ids: Optional[Iterable[int]] = None, legacy_allowed: Optional[bool] = None) -> 'Access':
        is_admin = self.is_admin_user(user_id, role_ids)
        tier = self.resolve_tier(user_id, role_ids)
        admin_tier = Tier(allowed_tools=ADMIN_TOOLS, allow_chat=True, is_admin=True)

        if self.MODE == Mode.MANAGEMENT:
            return Access(allowed=is_admin, tier=admin_tier if is_admin else tier, is_admin=is_admin)

        if is_admin:
            return Access(allowed=True, tier=admin_tier, is_admin=True)

        if tier is None:
            allowed = True if legacy_allowed is None else legacy_allowed
            return Access(allowed=allowed, tier=None, is_admin=False)

        return Access(allowed=tier.allow_chat, tier=tier, is_admin=tier.is_admin)

    def save(self, path: str | Path = 'config.yaml') -> None:
        Path(path).write_text(yaml.dump(self.model_dump(mode='json'), sort_keys=False))


class Access(BaseModel):
    allowed: bool
    tier: Optional[Tier] = None
    is_admin: bool = False


def load_config(path: str | Path = 'config.yaml') -> Config:
    path = Path(path)

    if not path.exists():
        raise FileNotFoundError(f"'{path}' does not exist. Please created it and add the required fields. Quickstart: `chloride create {path.parent}`")

    return Config.model_validate(yaml.full_load(path.read_text()))
