from sqlmodel import SQLModel, Field, create_engine
from sqlalchemy import text, inspect
from pydantic_ai import ModelMessage
from pydantic import TypeAdapter
from typing import *
from datetime import datetime, timezone

adapter = TypeAdapter(ModelMessage)

class Message(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    channel_id: int = Field(index=True)
    scope_key: str = Field(default='', index=True)

    data: str

    created_at: datetime = Field(default_factory = lambda: datetime.now(timezone.utc))

class Reminder(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    channel_id: int = Field(index=True)
    user_id: int = Field(index=True)
    guild_id: Optional[int] = None

    content: str
    due_at: datetime = Field(index=True)
    interval_seconds: Optional[int] = None
    topic: Optional[str] = Field(default=None, index=True)
    rsvp: bool = False

    created_at: datetime = Field(default_factory = lambda: datetime.now(timezone.utc))

class UserXP(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    guild_id: int = Field(index=True)
    user_id: int = Field(index=True)

    xp: int = 0
    level: int = 0
    last_awarded: datetime = Field(default_factory = lambda: datetime.fromtimestamp(0, timezone.utc))

class Subscription(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    guild_id: int = Field(index=True)
    topic: str = Field(index=True)
    user_id: int = Field(index=True)

class CommandUsage(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    guild_id: Optional[int] = Field(default=None, index=True)
    command: str = Field(index=True)
    user_id: int = Field(index=True)

    used_at: datetime = Field(default_factory = lambda: datetime.now(timezone.utc))

class Announcement(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    channel_id: int = Field(index=True)
    guild_id: Optional[int] = None

    cron: str
    content: str
    last_run: Optional[datetime] = None
    created_at: datetime = Field(default_factory = lambda: datetime.now(timezone.utc))

class RSVP(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    reminder_id: int = Field(index=True)
    user_id: int = Field(index=True)
    response: str

class UserPrefs(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True, unique=True)
    timezone: str = 'UTC'

def _add_column(conn, table, column, ddl):
    conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {ddl}'))

def _migrate(engine):
    inspector = inspect(engine)
    tables = inspector.get_table_names()

    if 'message' in tables:
        columns = [col['name'] for col in inspector.get_columns('message')]
        if 'scope_key' not in columns:
            with engine.begin() as conn:
                _add_column(conn, 'message', 'scope_key', 'scope_key VARCHAR')
                conn.execute(text("UPDATE message SET scope_key = 'channel:' || channel_id WHERE scope_key IS NULL OR scope_key = ''"))
                conn.execute(text('CREATE INDEX IF NOT EXISTS ix_message_scope_key ON message (scope_key)'))

    if 'reminder' in tables:
        columns = [col['name'] for col in inspector.get_columns('reminder')]
        with engine.begin() as conn:
            if 'topic' not in columns:
                _add_column(conn, 'reminder', 'topic', 'topic VARCHAR')
            if 'rsvp' not in columns:
                _add_column(conn, 'reminder', 'rsvp', 'rsvp BOOLEAN DEFAULT 0')

def init_db(db_uri: str):
    engine = create_engine(db_uri)
    SQLModel.metadata.create_all(engine)
    _migrate(engine)
    return engine
