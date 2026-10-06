# Chloride

Chloride is a persistent AI agent with Discord integration, configurable tool
permissions, memory, scheduled automations, authored capabilities, and managed
background services.

## Requirements

- Python 3.11 or newer
- Docker with Docker Compose
- A Discord bot token with the required gateway intents
- An API key for the configured model provider

## Installation

From a Chloride source checkout:

```console
python -m venv .venv
.venv\Scripts\activate
python -m pip install -e .
```

On macOS or Linux, activate the environment with `source .venv/bin/activate`.

## Create A Workspace

```console
chloride create my-bot
cd my-bot
```

Edit `config.yaml` and `config.md.j2` before starting the bot. Keep
`config.yaml` private because it contains credentials. The generated workspace
`.gitignore` excludes credentials, databases, memories, services, capabilities,
and other runtime state.

## Run

```console
chloride run
```

The command generates Docker deployment files on first use and starts the bot
through Docker Compose. Docker generation currently requires a local Chloride
source checkout. Use `chloride create-docker --force` to deliberately replace
existing generated deployment files.

## Updating

Update the source checkout, reinstall dependencies, and rebuild the workspace:

```console
git pull
python -m pip install -e . -U
chloride run
```

## Development

```console
python -m pip install -e . pytest
pytest
```
