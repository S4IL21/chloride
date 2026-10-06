import typer
from pathlib import Path
import yaml
import os
import subprocess as sp
import logging

from .config import load_config, Config, Tier, TOOL_GROUPS
from .prompts import DEFAULT_EXTRA_PROMPT
from . import log

app = typer.Typer()

logger = logging.getLogger(__name__)

@app.callback()
def main(
    ctx: typer.Context,
    quiet: bool = typer.Option(
        False,
        "--quiet",
        "-q",
        help="Disable verbose output.",
    ),
):
    log.setup(not quiet)

@app.command(name='create-docker')
def create_dockerfiles(
    path: Path = typer.Argument(Path('.')),
    force: bool = typer.Option(False, '--force', help='Replace existing Docker files.'),
):
    path = path.resolve()
    if not (path / 'config.yaml').is_file():
        logger.error("%s does not contain config.yaml. Run `chloride create` first.", path)
        raise typer.Exit(1)

    p_dockerfile = path / 'Dockerfile'
    p_compose    = path / 'docker-compose.yml'

    existing = [p.name for p in (p_dockerfile, p_compose) if p.exists()]
    if existing and not force:
        logger.error("Deployment files already exist: %s. Pass --force to replace them.", ', '.join(existing))
        raise typer.Exit(1)
    
    repo = Path(__file__).resolve().parent.parent
    from_source = (repo / 'pyproject.toml').exists()
    if not from_source:
        logger.error("Docker generation currently requires a Chloride source checkout.")
        raise typer.Exit(1)

    dockerfile = """\
FROM python:3.13-slim

WORKDIR /workspace
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
    
    compose += f"""
            - {repo}:/opt/chloride:ro
        
        command: /bin/sh -c "mkdir -p /tmp/chloride && cp -au /opt/chloride/. /tmp/chloride && pip install /tmp/chloride && python -m chloride.core"
"""

    logger.debug("Writing Docker deployment files...")
    p_dockerfile.write_text(dockerfile)
    p_compose.write_text(compose)
    (path / '.dockerignore').write_text('*\n')



@app.command()
def create(path: Path = typer.Argument(Path('.'))):
    path = path.resolve()
    if path.exists() and (not path.is_dir() or any(path.iterdir())):
        logger.error("Path %s must be an empty folder.", str(path))
        raise typer.Exit(1)
    
    if not path.exists():
        logger.debug("Creating directory %s...", str(path))
        # typer.secho(f"[+] Creating directory {path}...", fg='green')
        path.mkdir(parents=True, exist_ok=True)

    base_config = Config(
        DISCORD_TOKEN  = "Paste your Discord token here.",
        DISCORD_PREFIX = '--',

        TIERS = {
            'admin': Tier(
                allowed_roles_or_user_ids = [1234],
                allowed_tools = ['*'],
                ratelimit = None,
            ),
            'default': Tier(
                allowed_tools = ['@memory', '@discord', '@web', '@media'],
                allow_chat = True,
                ratelimit = '6/m'
            ),
        },

        AI_MODEL_NAME = 'google-gla:gemini-flash-latest',
        AI_API_KEY = "Put your API key here.",
        AI_OPENAI_RESPONSES_COMPATIBLE_BASE_URL = None,
        AI_OPENAI_COMPATIBLE_BASE_URL = None,
        AI_ANTHROPIC_COMPATIBLE_BASE_URL = None,
        AI_EXTRA_CONTEXT_PATH = 'config.md.j2',

        DB_PATH = 'sqlite:///memory.db',
    )

    config = yaml.dump(base_config.model_dump(mode='json'), sort_keys=False)

    auto_lines = ["These are the available tools that you can write:"]
    for group, tools in TOOL_GROUPS.items():
        auto_lines.append(f'  @{group} --------------')
        for tool in tools:
            auto_lines.append(f'    > {tool}')
        auto_lines.append('')

    auto_lines += ['', '', 'You can also do things like ["*", "!search_discord"], or ["@web", "!web_fetch"], or even ["*", "!@media"], or even ["!*", "get_user_info"]']
    comment = "\n".join(f"# {l}" for l in auto_lines)


    out = []
    for line in config.splitlines():
        if line.startswith("TIERS:"):
            out.append(comment)
        out.append(line)

    config = '\n'.join(out)

    (path / 'config.yaml').write_text(config)
    (path / 'config.md.j2').write_text(DEFAULT_EXTRA_PROMPT.render(path=path))
    (path / '.gitignore').write_text(
        'config.yaml\n*.db\nMEMORY/\nservices/\ncapabilities/\nautomations/\n.pending\n'
    )

    create_dockerfiles(path, force=False)

    logger.info("Success! All set up! Now go and customize your bot!")

@app.command()
def clear(path: Path = typer.Argument(Path('.'))):
    os.chdir(path.resolve())

    config = load_config()

    from urllib.parse import urlparse, unquote

    parsed = urlparse(config.DB_PATH)

    if parsed.scheme != 'sqlite':
        logger.error('The database is not a SQLite .db file. Chloride cannot find the database path to clear.')
        raise typer.Exit(1)

    db_path: Path

    if parsed.path.startswith('/'):
        db_path = Path(unquote(parsed.path))
    else:
        db_path = Path(unquote(parsed.path.lstrip('/')))

    if not db_path: return

    confirm = (input(f"Clear memory file at {db_path}? [y/N]: ").strip().lower() or 'n')[0] == 'y'

    if confirm:
        if db_path.exists():
            db_path.unlink()
            logger.info("Memory cleared successfully.")
        else:
            logger.info("Memory file does not exist; nothing to clear.")

    reminders = path / 'reminders.db'
    if reminders.exists():
        if (input(f"Clear reminders at {reminders}? [y/N]: ").strip().lower() or 'n')[0] == 'y':
            reminders.unlink()
            logger.info("Reminders cleared successfully.")

    if (path / 'docker-compose.yml').exists():
        logger.debug("Shutting down and removing container...")
        try:
            sp.run(['docker', 'compose', 'down', '-v'], check=True)
        except (FileNotFoundError, sp.CalledProcessError) as exc:
            logger.error("Could not stop the Docker workspace: %s", exc)
            raise typer.Exit(1) from exc
        logger.info("Workspace cleared.")


@app.command()
def run(path: Path = typer.Argument(Path('.'))):
    os.chdir(path.resolve())

    docker_files = (path / 'Dockerfile', path / 'docker-compose.yml')
    if not all(p.exists() for p in docker_files):
        create_dockerfiles(path, force=False)

    logger.info("Booting Chloride...")
    
    try:
        sp.run(['docker', 'compose', 'up', '--build'], check=True)
    except KeyboardInterrupt:
        logger.error('\nStopping workspace...')
        sp.run(["docker", "compose", "stop"], check=False)
        logger.info("Stopped.")
    except (FileNotFoundError, sp.CalledProcessError) as exc:
        logger.error("Could not run the Docker workspace: %s", exc)
        raise typer.Exit(1) from exc

    

if __name__ == "__main__":
    app()
