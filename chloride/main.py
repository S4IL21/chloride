import typer
from pathlib import Path
import yaml
import os
import subprocess as sp

from .config import load_config, Config, Tier, Mode, HistoryScope
from .prompts import DEFAULT_EXTRA_PROMPT

app = typer.Typer()

@app.command(name='create-docker')
def create_dockerfiles(path: Path = typer.Argument(Path('.')), force=False):
    path = path.resolve()
    if not (path / 'config.yaml').exists() and not force:
        return

    p_dockerfile = path / 'Dockerfile'
    p_compose = path / 'docker-compose.yml'

    if p_dockerfile.exists() and p_compose.exists() and not force:
        return
    
    repo = Path(__file__).resolve().parent.parent
    from_source = (repo / 'pyproject.toml').exists()

    dockerfile = """
FROM python:3.13

WORKDIR /workspace
"""
    if not from_source:
        dockerfile += """
RUN pip install git+https://github.com/s4il21/chloride.git
"""
    else: "Chloride is installed at runtime from a mounted volume. This is for easier development."

    dockerfile += """
CMD ["python", "-m", "chloride.core"]
"""

    compose = f"""
services:
    bot:
        build: .
        container_name: chloride-{path.name.lower().replace(' ', '-')}
        restart: unless-stopped
        volumes:
            - .:/workspace
"""
    
    if from_source:
        compose += f"""
            - {repo}:/opt/chloride:ro

        command: /bin/sh -c "mkdir -p /tmp/chloride && cp -au /opt/chloride/. /tmp/chloride && pip install /tmp/chloride && python -m chloride.core"
"""
        
    if not p_dockerfile.exists():
        typer.secho("[+] Writing Dockerfile...")
        p_dockerfile.write_text(dockerfile)

    if not p_compose.exists():
        typer.secho("[+] Writing docker-compose.yml...")
        p_compose.write_text(compose)



@app.command()
def create(path: Path = typer.Argument(Path('.'))):
    path = path.resolve()
    if (
        path.exists()
        and
        (
            path.is_file()
            or
            path.is_dir() and not any(path.iterdir())
        )
    ):
        typer.secho(f"Path {path} must be an empty folder.", fg='red')
        raise typer.Exit(1)
    
    if not path.exists():
        typer.secho(f"[+] Creating directory {path}...", fg='green')
        path.mkdir(parents=True, exist_ok=True)

    name = path.name

    base_config = Config(
        DISCORD_TOKEN = "Paste your Discord token here.",
        DISCORD_PREFIX = '--',

        tiers = {
            'admin': Tier(
                allowed_roles_or_user_ids = [123456789012345678],
                allowed_tools = ['*'],
                is_admin = True,
            ),
            'default': Tier(
                allowed_tools = [],
                allow_chat = True,
            ),
        },

        MODE = Mode.SERVER,
        ADMIN_ROLE_OR_USER_IDS = [123456789012345678],
        AUTO_REPLY_CHANNEL_IDS = [],

        HISTORY_SCOPE = HistoryScope.CHANNEL,
        PRIVATE_CHANNEL_IDS = [],
        SHARED_CHANNEL_IDS = [],
        SHARE_GROUPS = [],

        ENABLE_SAFETY = True,
        BLOCKED_USER_IDS = [],
        RATE_LIMIT_PER_MINUTE = 0,

        ENABLE_OUTPUT_JUDGE = False,
        CONFIRM_DANGEROUS_TOOLS = True,
        CONFIRM_TOOLS = ['run_shell', 'run_code'],

        WELCOME_CHANNEL_ID = None,
        WELCOME_MESSAGE = None,
        GOODBYE_MESSAGE = None,

        ENABLE_XP = False,
        XP_PER_MESSAGE = 15,
        XP_COOLDOWN_SECONDS = 60,
        XP_ANNOUNCE_LEVELUP = True,
        XP_LEVELUP_CHANNEL_ID = None,

        ENABLE_AUTOMOD = False,
        AUTOMOD_BANNED_WORDS = [],
        AUTOMOD_BLOCK_INVITES = True,
        AUTOMOD_MAX_MENTIONS = 0,
        AUTOMOD_MAX_CAPS_RATIO = 0.0,
        AUTOMOD_TIMEOUT_SECONDS = 0,

        DEFAULT_TIMEZONE = 'UTC',

        AI_MODEL_NAME = 'google-gla:gemini-flash-latest',
        AI_API_KEY = "Put your API key here.",
        AI_OPENAI_COMPATIBLE_BASE_URL = None,
        AI_EXTRA_CONTEXT_PATH = 'config.md.j2',

        DB_PATH = 'sqlite:///memory.db',
    )

    (path / 'config.yaml').write_text(yaml.dump(base_config.model_dump(mode='json')))
    (path / 'config.md.j2').write_text(DEFAULT_EXTRA_PROMPT.render(path=path))

    create_dockerfiles(path)

    typer.secho(f"[+] Success! All set up! Now go and customize your bot!", fg='green')

@app.command()
def clear(path: Path = typer.Argument(Path('.'))):
    os.chdir(path.resolve())

    config = load_config()

    from urllib.parse import urlparse, unquote

    parsed = urlparse(config.DB_PATH)

    if parsed.scheme != 'sqlite':
        typer.secho('The database is not a SQLite .db file. Chloride cannot find the database path to clear.', fg='red')
        raise typer.Exit(1)

    db_path: Path

    if parsed.path.startswith('/'):
        db_path = Path(unquote(parsed.path))
    else:
        db_path = Path(unquote(parsed.path.lstrip('/')))

    if not db_path: return

    confirm = (input(f"Clear memory file at {db_path}? [y/N]: ").strip().lower() or 'n')[0] == 'y'

    if confirm:
        db_path.unlink()
        typer.secho("Memory cleared successfully.", fg='green')

    if (path / 'docker-compose.yml').exists():
        typer.secho("Shutting down and removing container...")
        sp.run(['docker', 'compose', 'down', '-v'])
        typer.secho("Workspace cleared.", fg='green')


@app.command()
def gui(
    path: Path = typer.Argument(Path('.')),
    port: int = typer.Option(6767, help='Preferred port. Falls back to the next free port if taken.'),
    host: str = typer.Option('127.0.0.1', help='Host to bind the web server to.'),
):
    os.chdir(path.resolve())
    from .gui import serve
    serve(preferred_port=port, host=host)


@app.command()
def run(path: Path = typer.Argument(Path('.'))):
    os.chdir(path.resolve())

    create_dockerfiles(path)

    typer.secho("Booting Chloride...", fg='white')
    
    try:
        sp.run(['docker', 'compose', 'up', '--build'])
    except KeyboardInterrupt:
        typer.secho('\nStopping workspace...', fg='red')
        sp.run(["docker", "compose", "stop"])
        typer.secho("Stopped.", fg='white')

    

if __name__ == "__main__":
    app()