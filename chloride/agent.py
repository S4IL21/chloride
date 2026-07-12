import pydantic_ai
from pydantic_ai import Agent, RunContext
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.common_tools.duckduckgo import duckduckgo_search_tool
from pydantic_ai.models import Model
from pydantic_ai.exceptions import ModelAPIError
from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import *
from datetime import datetime
import discord
import discord.http
import asyncio
from dataclasses import dataclass
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
from pathlib import Path
import subprocess as sp
from enum import Enum

from .utils import indent
from . import config as libcfg, prompts

@dataclass
class Deps:
    model: Model | str
    message: discord.Message = None
    client: discord.Client = None
    config: libcfg.Config = None
    is_summary: bool = False
    is_message: bool = True
    tier: Optional[libcfg.Tier] = None
    is_admin: bool = False

async def restrict_tools_by_tier(ctx: RunContext[Deps], tool_def: ToolDefinition):
    tier = getattr(ctx.deps, 'tier', None)
    if tier is None:
        return tool_def
    return tool_def if tier.can_use_tool(tool_def.name) else None

async def always_allow(ctx: RunContext[Deps], tool_def: ToolDefinition):
    return tool_def

_ddg_tool = duckduckgo_search_tool()
_ddg_tool.prepare = always_allow

agent = Agent(
    deps_type = Deps,
    tools=[_ddg_tool]
)

class JudgeVerdict(BaseModel):
    safe: bool
    reason: str = ''

judge_agent = Agent(
    output_type = JudgeVerdict,
)

async def judge_output(model: Model | str, user_message: str, bot_reply: str) -> JudgeVerdict:
    from . import safety
    result = await judge_agent.run(
        user_prompt = safety.build_judge_prompt(user_message, bot_reply),
        model = model,
    )
    return result.output

@agent.instructions
def system_prompt(ctx: RunContext[Deps]):
    if ctx.deps.is_summary:
        return prompts.SUMMARIZATION_PROMPT
    
    if ctx.deps.client and ctx.deps.config:
        return prompts.SYSTEM_PROMPT.render(client=ctx.deps.client, config=ctx.deps.config, is_admin=ctx.deps.is_admin)

    return ''

@agent.instructions
def add_message_details(ctx: RunContext[Deps] | discord.Message, indent=1):
    if isinstance(ctx, RunContext) and (not ctx.deps.is_message or not ctx.deps.message): return
    if not ctx: return 'Message not found.'
    msg = ctx.deps.message if isinstance(ctx, RunContext) else ctx
    data = f"""
Message Author: {msg.author.display_name} (ID: {msg.author.id}). (Use the `get_user_info` tool to get more information about the user.)
Message ID: {msg.id} - use this in code if you want to do something like download attachments from the message.
"""
    
    if len(msg.attachments) > 0:
        data += f"""
{len(msg.attachments)} attachments (if you want to view them, use code to analyse using message ID):
    {[a.filename for a in msg.attachments]}
"""

    if not msg.reference:
        data += "\n\nThe message is not replying to anything."
    else:
        data += f"""
Message Reference:
    {add_message_details(msg.reference.resolved, indent+1) if indent <= 2 else '...'}
"""
        
    lines = data.splitlines()
    data = ''.join([(' '* 4 * indent) + line for line in lines])

    return data

class User(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    discriminator: str
    global_name: Optional[str] = None
    bot: bool
    system: bool
    created_at: datetime
    
    mention: str
    display_name: str
    
    avatar_url: Optional[str] = Field(None, alias="avatar")
    banner_url: Optional[str] = Field(None, alias="banner")
    accent_color: Optional[int] = None

    @field_validator("avatar_url", "banner_url", mode="before")
    @classmethod
    def transform_asset(cls, v):
        if isinstance(v, discord.Asset):
            return v.url
        return v

    @field_validator("accent_color", mode="before")
    @classmethod
    def transform_color(cls, v):
        if isinstance(v, discord.Color):
            return v.value
        return v
    
class Member(User):
    nick: Optional[str] = None
    joined_at: Optional[datetime] = None
    premium_since: Optional[datetime] = None
    
    roles: List[str] = Field(default_factory=list)

    @field_validator("roles", mode="before")
    @classmethod
    def transform_roles(cls, v):
        if isinstance(v, list):
            return[role.name for role in v if getattr(role, 'name', '') != '@everyone']
        return v

class Message(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    content: str
    author: User
    created_at: datetime
    edited_at: Optional[datetime] = None

    mention_everyone: bool
    mentions: List[User] = Field(default_factory=list)
    role_mentions: List[str] = Field(default_factory=list)

    attachments: List[str] = Field(default_factory=list)
    embeds: List[dict] = Field(default_factory=list)

    pinned: bool
    tts: bool
    type: int

    @field_validator("mentions", mode="before")
    @classmethod
    def transform_mentions(cls, v):
        if isinstance(v, list):
            return [User.model_validate(user) for user in v]
        return v

    @field_validator("role_mentions", mode="before")
    @classmethod
    def transform_role_mentions(cls, v):
        if isinstance(v, list):
            return [role.name for role in v if getattr(role, "name", "") != "@everyone"]
        return v

    @field_validator("attachments", mode="before")
    @classmethod
    def transform_attachments(cls, v):
        if isinstance(v, list):
            return [attachment.url for attachment in v if isinstance(attachment, discord.Attachment)]
        return v

    @field_validator("embeds", mode="before")
    @classmethod
    def transform_embeds(cls, v):
        if isinstance(v, list):
            return [embed.to_dict() for embed in v if isinstance(embed, discord.Embed)]
        return v

class HasType(str, Enum):
    LINK = 'link'
    EMBED = 'embed'
    POLL = 'poll'
    FILE = 'file'
    VIDEO = 'video'
    IMAGE = 'image'
    SOUND = 'sound'
    STICKER = 'sticker'
    FORWARD = 'forward'

class SortOrder(str, Enum):
    ASCENDING = 'asc'
    DESCENDING = 'desc'

class SearchParams(BaseModel):
    author_id: Optional[str] = None
    mentions: Optional[str] = None
    has: Optional[HasType] = None
    channel_id: Optional[str] = None
    pinned: Optional[bool] = None
    sort_by: str = 'timestamp'
    sort_order: Optional[SortOrder] = SortOrder.DESCENDING
    offset: int = 0

class SearchResponse(BaseModel):
    messages: list[Message]
    total_results: int

@agent.tool(prepare=restrict_tools_by_tier)
async def search_discord(
    ctx: RunContext[Deps],
    search_params: SearchParams
):
    try:
        return await ctx.deps.client.http.request(
            discord.http.Route(
                method = 'GET',
                path = f'/guilds/{ctx.deps.message.guild.id}/messages/search'
            ),
            params = search_params.model_dump(mode='json', exclude_none=True),
        )
    except Exception as e:
        return {"error": str(e)}

@agent.tool(prepare=restrict_tools_by_tier)
async def get_user_info(ctx: RunContext[Deps], user_id: Optional[str] = None) -> Union[Member, User, dict]:
    if user_id is None:
        target = ctx.deps.message.author
        if isinstance(target, discord.Member):
            return Member.model_validate(target)
        return User.model_validate(target)

    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return {'error': f'Invalid user id: {user_id!r}'}

    guild = getattr(ctx.deps.message, 'guild', None)
    if guild is not None:
        member = guild.get_member(uid)
        if member is None:
            try:
                member = await guild.fetch_member(uid)
            except discord.HTTPException:
                member = None
        if member is not None:
            return Member.model_validate(member)

    try:
        user = ctx.deps.client.get_user(uid) or await ctx.deps.client.fetch_user(uid)
    except discord.HTTPException as e:
        return {'error': f'Could not find a user with id {uid}: {e}'}

    return User.model_validate(user)

class ConfirmView(discord.ui.View):
    def __init__(self, allowed_ids: set[int], timeout: float = 120):
        super().__init__(timeout=timeout)
        self.allowed_ids = allowed_ids
        self.value = None

    async def _resolve_ids(self, interaction: discord.Interaction) -> set[int]:
        ids = {interaction.user.id}
        ids.update(role.id for role in getattr(interaction.user, 'roles', []))
        return ids

    @discord.ui.button(label='Approve', style=discord.ButtonStyle.danger)
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not (await self._resolve_ids(interaction)).intersection(self.allowed_ids):
            await interaction.response.send_message("Only an admin can approve this.", ephemeral=True)
            return
        self.value = True
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content="Approved.", view=self)
        self.stop()

    @discord.ui.button(label='Deny', style=discord.ButtonStyle.secondary)
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not (await self._resolve_ids(interaction)).intersection(self.allowed_ids):
            await interaction.response.send_message("Only an admin can deny this.", ephemeral=True)
            return
        self.value = False
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content="Denied.", view=self)
        self.stop()

async def _require_confirmation(ctx: RunContext[Deps], tool_name: str, preview: str) -> Optional[str]:
    config = getattr(ctx.deps, 'config', None)
    if config is None or not config.CONFIRM_DANGEROUS_TOOLS:
        return None
    if tool_name not in (config.CONFIRM_TOOLS or []):
        return None
    if getattr(ctx.deps, 'is_admin', False):
        return None
    if ctx.deps.message is None:
        return 'Execution blocked: dangerous tools require admin confirmation, which is unavailable here.'

    allowed_ids = set(config.ADMIN_ROLE_OR_USER_IDS or [])
    if not allowed_ids:
        return 'Execution blocked: no admins are configured to approve dangerous tools.'

    snippet = preview if len(preview) <= 500 else preview[:500] + '...'
    embed = discord.Embed(
        title=f"Approval required: {tool_name}",
        description=f"Requested by {ctx.deps.message.author.mention}.\n```\n{snippet}\n```",
        timestamp=datetime.now(),
    )
    view = ConfirmView(allowed_ids)
    prompt_msg = await ctx.deps.message.channel.send(embed=embed, view=view)
    await view.wait()

    try:
        if view.value is None:
            await prompt_msg.edit(content="Approval timed out.", view=None)
    except discord.HTTPException:
        pass

    if view.value is True:
        return None
    if view.value is False:
        return 'An admin denied this action.'
    return 'The approval request timed out; the action was not run.'

@agent.tool(prepare=restrict_tools_by_tier)
async def run_shell(ctx: RunContext[Deps], command: str, timeout: int = 10) -> str:
    denial = await _require_confirmation(ctx, 'run_shell', command)
    if denial is not None:
        return {'error': denial}

    print(f"Agent running shell command: {command}")

    try:
        result = sp.run(command, shell=True, text=True, capture_output=True, timeout=timeout)
        print(result.stdout + result.stderr)
        return {
            'exit_code': result.returncode,
            'stdout': result.stdout,
            'stderr': result.stderr,
        }
    except sp.TimeoutExpired:
        return f'Command timed out after {timeout}s.'
    except Exception as e:
        import traceback
        traceback.print_exc()
        return traceback.format_exc()

@agent.tool(prepare=restrict_tools_by_tier)
async def run_code(ctx: RunContext[Deps], code: str, timeout: int = 10):
    denial = await _require_confirmation(ctx, 'run_code', code)
    if denial is not None:
        return {'error': denial}

    warnings = []

    if not code.strip().startswith('async def main(message, discord, client):') or not 'async def main(message, discord, client):' in code:
        warnings.append("Your code didn't start with `async def main(message, discord, client):`. So the system added it for you and indented your code appropriately. If you don't receive any output / receive None, it's because you didn't have a `return` statement. You should try again and format the code properly within the function and return properly.")

        code = f"""
async def main(message, discord, client):
{indent(code, 4)}
        """

    locals = {}
    globals = { '__builtins__': __builtins__ }

    stdout_buffer = StringIO()
    stderr_buffer = StringIO()

    print("Agent attempted to run code:")
    print(code)
    print("Running...")

    stdout = ''
    stderr = ''
    try:
        with redirect_stdout(stdout_buffer), redirect_stderr(stderr_buffer):
            exec(code, globals, locals)
            func = locals['main']

            result = await asyncio.wait_for(
                func(ctx.deps.message, discord, ctx.deps.client),
                timeout = timeout,
            )

        stdout = stdout_buffer.getvalue()
        stderr = stderr_buffer.getvalue()

        print(f"Result: {result}")
        print(stdout + stderr)

        return {'warnings': warnings, 'result': result, 'stdout': stdout, 'stderr': stderr}
    except asyncio.TimeoutError:
        print("Execution timed out.")
        return {'warnings': warnings, 'result': "Execution timed out.", 'stdout': stdout, 'stderr': stderr}
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {'warnings': warnings, 'result': traceback.format_exc(), 'stdout': stdout, 'stderr': stderr}
    
class FileType(str, Enum):
    IMAGE = 'image'
    VIDEO = 'video'
    AUDIO = 'audio'
    DOCUMENT = 'document'

@agent.tool(prepare=restrict_tools_by_tier)
async def analyse_file(ctx: RunContext[Deps], url: str, file_type: FileType, query: Optional[str] = None) -> str:
    if url.startswith('http'):
        match file_type:
            case FileType.IMAGE:
                part = pydantic_ai.ImageUrl(url=url, force_download=True)
            case FileType.AUDIO:
                part = pydantic_ai.AudioUrl(url=url, force_download=True)
            case FileType.VIDEO:
                part = pydantic_ai.VideoUrl(url=url, force_download=True)
            case FileType.DOCUMENT:
                part = pydantic_ai.DocumentUrl(url=url, force_download=True)

    else:
        url = url.removeprefix('file://')
        path = Path(url)
        part = pydantic_ai.BinaryContent(path.read_bytes())

    try:
        response = await agent.run(
            user_prompt = [
                part,
                prompts.CONTENT_SUMMARIZATION_PROMPT.render(query=query),
            ],
            model = ctx.deps.model,
            deps = Deps(is_message=False, model=ctx.deps.model),
        )
        return response.output
    except ModelAPIError as e:
        return f"There was an API error during the file parsing. See details: {e.message}"
    except Exception as e:
        return f"There was an unknown error during the operation. {e}"
    
@agent.tool(prepare=restrict_tools_by_tier)
async def get_channel_info(ctx: RunContext[Deps], channel_id: Optional[str] = None) -> dict:
    guild = getattr(ctx.deps.message, 'guild', None)
    if channel_id is None:
        channel = ctx.deps.message.channel
    else:
        try:
            cid = int(channel_id)
        except (TypeError, ValueError):
            return {'error': f'Invalid channel id: {channel_id!r}'}
        channel = ctx.deps.client.get_channel(cid)
        if channel is None:
            try:
                channel = await ctx.deps.client.fetch_channel(cid)
            except discord.HTTPException as e:
                return {'error': f'Could not find channel {cid}: {e}'}

    return {
        'id': channel.id,
        'name': getattr(channel, 'name', None),
        'type': str(getattr(channel, 'type', 'unknown')),
        'topic': getattr(channel, 'topic', None),
        'nsfw': getattr(channel, 'nsfw', None),
        'category': getattr(getattr(channel, 'category', None), 'name', None),
        'position': getattr(channel, 'position', None),
        'guild_id': getattr(guild, 'id', None),
    }

@agent.tool(prepare=restrict_tools_by_tier)
async def get_server_info(ctx: RunContext[Deps]) -> dict:
    guild = getattr(ctx.deps.message, 'guild', None)
    if guild is None:
        return {'error': 'This message is not in a server.'}

    return {
        'id': guild.id,
        'name': guild.name,
        'description': guild.description,
        'member_count': guild.member_count,
        'owner_id': guild.owner_id,
        'created_at': guild.created_at.isoformat(),
        'channel_count': len(guild.channels),
        'role_count': len(guild.roles),
        'roles': [role.name for role in guild.roles if role.name != '@everyone'],
        'emoji_count': len(guild.emojis),
        'boost_level': guild.premium_tier,
        'boost_count': guild.premium_subscription_count,
    }

@agent.tool(prepare=restrict_tools_by_tier)
async def read_channel_history(ctx: RunContext[Deps], limit: int = 20, channel_id: Optional[str] = None) -> Union[list, dict]:
    limit = max(1, min(limit, 100))

    if channel_id is None:
        channel = ctx.deps.message.channel
    else:
        try:
            cid = int(channel_id)
        except (TypeError, ValueError):
            return {'error': f'Invalid channel id: {channel_id!r}'}
        channel = ctx.deps.client.get_channel(cid)
        if channel is None:
            try:
                channel = await ctx.deps.client.fetch_channel(cid)
            except discord.HTTPException as e:
                return {'error': f'Could not find channel {cid}: {e}'}

    try:
        out = []
        async for msg in channel.history(limit=limit):
            out.append({
                'id': msg.id,
                'author': msg.author.display_name,
                'author_id': msg.author.id,
                'content': msg.content,
                'created_at': msg.created_at.isoformat(),
            })
        return out
    except discord.HTTPException as e:
        return {'error': str(e)}

@agent.tool(prepare=restrict_tools_by_tier)
async def get_time(ctx: RunContext[Deps]) -> str:
    return datetime.now().isoformat()

@agent.tool(prepare=restrict_tools_by_tier)
async def set_reminder(ctx: RunContext[Deps], duration: str, content: str, repeat: bool = False) -> dict:
    from .utils import parse_duration
    seconds = parse_duration(duration)
    if seconds <= 0:
        return {'error': f'Could not understand the duration {duration!r}. Try something like "10m" or "1h30m".'}

    client = ctx.deps.client
    if client is None or ctx.deps.message is None:
        return {'error': 'Reminders can only be set from a channel message.'}

    reminder_id = client.add_reminder(
        channel_id = ctx.deps.message.channel.id,
        user_id = ctx.deps.message.author.id,
        guild_id = getattr(ctx.deps.message.guild, 'id', None),
        content = content,
        seconds = seconds,
        repeat = repeat,
    )
    return {'ok': True, 'reminder_id': reminder_id, 'fires_in_seconds': seconds, 'repeat': repeat}

@agent.tool(prepare=restrict_tools_by_tier)
async def send_message(ctx: RunContext[Deps], content: str, channel_id: Optional[str] = None) -> dict:
    if channel_id is None:
        channel = ctx.deps.message.channel
    else:
        try:
            cid = int(channel_id)
        except (TypeError, ValueError):
            return {'error': f'Invalid channel id: {channel_id!r}'}
        channel = ctx.deps.client.get_channel(cid)
        if channel is None:
            try:
                channel = await ctx.deps.client.fetch_channel(cid)
            except discord.HTTPException as e:
                return {'error': f'Could not find channel {cid}: {e}'}

    try:
        sent = await channel.send(content, allowed_mentions=discord.AllowedMentions.none())
        return {'sent': True, 'message_id': sent.id, 'channel_id': channel.id}
    except discord.HTTPException as e:
        return {'error': str(e)}

@agent.tool(prepare=restrict_tools_by_tier)
async def set_channel_topic(ctx: RunContext[Deps], topic: str, channel_id: Optional[str] = None) -> dict:
    channel = ctx.deps.message.channel if channel_id is None else ctx.deps.client.get_channel(int(channel_id))
    if channel is None:
        return {'error': f'Could not find channel {channel_id}.'}
    try:
        await channel.edit(topic=topic)
        return {'ok': True, 'channel_id': channel.id, 'topic': topic}
    except discord.HTTPException as e:
        return {'error': str(e)}

async def _resolve_member(ctx: RunContext[Deps], user_id: str):
    guild = getattr(ctx.deps.message, 'guild', None)
    if guild is None:
        return None, {'error': 'This action requires a server.'}
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return None, {'error': f'Invalid user id: {user_id!r}'}
    member = guild.get_member(uid)
    if member is None:
        try:
            member = await guild.fetch_member(uid)
        except discord.HTTPException as e:
            return None, {'error': f'Could not find member {uid}: {e}'}
    return member, None

@agent.tool(prepare=restrict_tools_by_tier)
async def purge_messages(ctx: RunContext[Deps], limit: int = 10, channel_id: Optional[str] = None) -> dict:
    limit = max(1, min(limit, 100))
    channel = ctx.deps.message.channel if channel_id is None else ctx.deps.client.get_channel(int(channel_id))
    if channel is None:
        return {'error': f'Could not find channel {channel_id}.'}
    try:
        deleted = await channel.purge(limit=limit)
        return {'deleted': len(deleted), 'channel_id': channel.id}
    except discord.HTTPException as e:
        return {'error': str(e)}

@agent.tool(prepare=restrict_tools_by_tier)
async def kick_member(ctx: RunContext[Deps], user_id: str, reason: Optional[str] = None) -> dict:
    member, err = await _resolve_member(ctx, user_id)
    if err:
        return err
    try:
        await member.kick(reason=reason)
        return {'kicked': member.id}
    except discord.HTTPException as e:
        return {'error': str(e)}

@agent.tool(prepare=restrict_tools_by_tier)
async def ban_member(ctx: RunContext[Deps], user_id: str, reason: Optional[str] = None, delete_message_days: int = 0) -> dict:
    member, err = await _resolve_member(ctx, user_id)
    if err:
        return err
    try:
        await member.ban(reason=reason, delete_message_days=max(0, min(delete_message_days, 7)))
        return {'banned': member.id}
    except discord.HTTPException as e:
        return {'error': str(e)}

@agent.tool(prepare=restrict_tools_by_tier)
async def timeout_member(ctx: RunContext[Deps], user_id: str, minutes: int, reason: Optional[str] = None) -> dict:
    from datetime import timedelta
    member, err = await _resolve_member(ctx, user_id)
    if err:
        return err
    try:
        await member.timeout(timedelta(minutes=max(1, minutes)), reason=reason)
        return {'timed_out': member.id, 'minutes': minutes}
    except discord.HTTPException as e:
        return {'error': str(e)}

@agent.tool(prepare=restrict_tools_by_tier)
async def add_role(ctx: RunContext[Deps], user_id: str, role_id: str, reason: Optional[str] = None) -> dict:
    member, err = await _resolve_member(ctx, user_id)
    if err:
        return err
    role = member.guild.get_role(int(role_id))
    if role is None:
        return {'error': f'Could not find role {role_id}.'}
    try:
        await member.add_roles(role, reason=reason)
        return {'added_role': role.id, 'to': member.id}
    except discord.HTTPException as e:
        return {'error': str(e)}

@agent.tool(prepare=restrict_tools_by_tier)
async def remove_role(ctx: RunContext[Deps], user_id: str, role_id: str, reason: Optional[str] = None) -> dict:
    member, err = await _resolve_member(ctx, user_id)
    if err:
        return err
    role = member.guild.get_role(int(role_id))
    if role is None:
        return {'error': f'Could not find role {role_id}.'}
    try:
        await member.remove_roles(role, reason=reason)
        return {'removed_role': role.id, 'from': member.id}
    except discord.HTTPException as e:
        return {'error': str(e)}

@agent.tool(prepare=restrict_tools_by_tier)
async def trigger_reboot(ctx: RunContext[Deps]):
    if ctx.deps.message:
        await ctx.deps.message.channel.send(embed = discord.Embed(
            title = "Rebooting...",
            description = "Agent triggered a reboot of the container.",
            timestamp = datetime.now(),
        ))

    import sys
    sys.exit(0)