import os
import socket
import signal
import subprocess as sp
import threading
import collections
from pathlib import Path
from typing import Optional, List

import yaml
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from .config import Config, Tier, Mode, HistoryScope
from .prompts import DEFAULT_EXTRA_PROMPT


class Runner:
    def __init__(self, path: Path):
        self.path = path
        self.process = None
        self.logs = collections.deque(maxlen=2000)
        self.thread = None

    @property
    def running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def _pump(self):
        for line in iter(self.process.stdout.readline, ''):
            if line == '':
                break
            self.logs.append(line.rstrip('\n'))

    def start(self):
        if self.running:
            return
        self.logs.append(f'[chloride] starting bot in {self.path}')
        self.process = sp.Popen(
            ['python', '-m', 'chloride.core'],
            cwd=str(self.path),
            stdout=sp.PIPE,
            stderr=sp.STDOUT,
            text=True,
            bufsize=1,
            env={**os.environ, 'PYTHONUNBUFFERED': '1'},
        )
        self.thread = threading.Thread(target=self._pump, daemon=True)
        self.thread.start()

    def stop(self):
        if not self.running:
            return
        self.logs.append('[chloride] stopping bot')
        self.process.send_signal(signal.SIGINT)
        try:
            self.process.wait(timeout=10)
        except sp.TimeoutExpired:
            self.process.kill()


runners: dict[str, Runner] = {}
BASE = Path('.').resolve()


def _workspace_dir(name: str) -> Path:
    path = (BASE / name).resolve()
    if BASE not in path.parents and path != BASE:
        raise HTTPException(status_code=400, detail='Invalid workspace path.')
    return path


def _runner(name: str) -> Runner:
    path = _workspace_dir(name)
    if name not in runners:
        runners[name] = Runner(path)
    return runners[name]


def list_workspaces() -> list[str]:
    out = []
    for child in sorted(BASE.iterdir()):
        if child.is_dir() and (child / 'config.yaml').exists():
            out.append(child.name)
    return out


class CreateBody(BaseModel):
    name: str


class TextBody(BaseModel):
    content: str


class SettingsBody(BaseModel):
    ENABLE_SAFETY: bool
    ENABLE_OUTPUT_JUDGE: bool
    CONFIRM_DANGEROUS_TOOLS: bool
    ENABLE_XP: bool
    XP_PER_MESSAGE: int
    XP_COOLDOWN_SECONDS: int
    XP_ANNOUNCE_LEVELUP: bool
    XP_LEVELUP_CHANNEL_ID: Optional[int] = None
    ENABLE_AUTOMOD: bool
    AUTOMOD_BANNED_WORDS: List[str] = []
    AUTOMOD_BLOCK_INVITES: bool
    AUTOMOD_MAX_MENTIONS: int
    AUTOMOD_MAX_CAPS_RATIO: float
    AUTOMOD_TIMEOUT_SECONDS: int
    DEFAULT_TIMEZONE: str


def build_app() -> FastAPI:
    app = FastAPI(title='Chloride GUI')

    @app.get('/', response_class=HTMLResponse)
    async def index():
        return PAGE

    @app.get('/api/workspaces')
    async def api_workspaces():
        return [
            {'name': name, 'running': (name in runners and runners[name].running)}
            for name in list_workspaces()
        ]

    @app.post('/api/workspaces')
    async def api_create(body: CreateBody):
        name = body.name.strip()
        if not name or '/' in name or name.startswith('.'):
            raise HTTPException(status_code=400, detail='Invalid name.')
        path = _workspace_dir(name)
        if path.exists() and any(path.iterdir()):
            raise HTTPException(status_code=400, detail='A non-empty folder with that name already exists.')
        path.mkdir(parents=True, exist_ok=True)

        base_config = Config(
            DISCORD_TOKEN='Paste your Discord token here.',
            DISCORD_PREFIX='--',
            MODE=Mode.SERVER,
            ADMIN_ROLE_OR_USER_IDS=[123456789012345678],
            AUTO_REPLY_CHANNEL_IDS=[],
            HISTORY_SCOPE=HistoryScope.CHANNEL,
            ENABLE_SAFETY=True,
            ENABLE_OUTPUT_JUDGE=False,
            CONFIRM_DANGEROUS_TOOLS=True,
            tiers={
                'admin': Tier(allowed_roles_or_user_ids=[123456789012345678], allowed_tools=['*'], is_admin=True),
                'default': Tier(allowed_tools=[], allow_chat=True),
            },
            AI_MODEL_NAME='google-gla:gemini-flash-latest',
            AI_API_KEY='Put your API key here.',
            AI_OPENAI_COMPATIBLE_BASE_URL=None,
            AI_EXTRA_CONTEXT_PATH='config.md.j2',
            DB_PATH='sqlite:///memory.db',
        )
        base_config.save(path / 'config.yaml')
        (path / 'config.md.j2').write_text(DEFAULT_EXTRA_PROMPT.render(path=path))
        return {'ok': True, 'name': name}

    @app.get('/api/workspaces/{name}/config')
    async def api_get_config(name: str):
        path = _workspace_dir(name) / 'config.yaml'
        if not path.exists():
            raise HTTPException(status_code=404, detail='config.yaml not found.')
        return {'content': path.read_text()}

    @app.put('/api/workspaces/{name}/config')
    async def api_put_config(name: str, body: TextBody):
        try:
            yaml.full_load(body.content)
        except yaml.YAMLError as e:
            raise HTTPException(status_code=400, detail=f'Invalid YAML: {e}')
        (_workspace_dir(name) / 'config.yaml').write_text(body.content)
        return {'ok': True}

    @app.get('/api/workspaces/{name}/context')
    async def api_get_context(name: str):
        path = _workspace_dir(name) / 'config.md.j2'
        return {'content': path.read_text() if path.exists() else ''}

    @app.put('/api/workspaces/{name}/context')
    async def api_put_context(name: str, body: TextBody):
        (_workspace_dir(name) / 'config.md.j2').write_text(body.content)
        return {'ok': True}

    @app.get('/api/workspaces/{name}/settings')
    async def api_get_settings(name: str):
        from .config import load_config
        config = load_config(_workspace_dir(name) / 'config.yaml')
        return {
            'ENABLE_SAFETY': config.ENABLE_SAFETY,
            'ENABLE_OUTPUT_JUDGE': config.ENABLE_OUTPUT_JUDGE,
            'CONFIRM_DANGEROUS_TOOLS': config.CONFIRM_DANGEROUS_TOOLS,
            'ENABLE_XP': config.ENABLE_XP,
            'XP_PER_MESSAGE': config.XP_PER_MESSAGE,
            'XP_COOLDOWN_SECONDS': config.XP_COOLDOWN_SECONDS,
            'XP_ANNOUNCE_LEVELUP': config.XP_ANNOUNCE_LEVELUP,
            'XP_LEVELUP_CHANNEL_ID': config.XP_LEVELUP_CHANNEL_ID,
            'ENABLE_AUTOMOD': config.ENABLE_AUTOMOD,
            'AUTOMOD_BANNED_WORDS': config.AUTOMOD_BANNED_WORDS,
            'AUTOMOD_BLOCK_INVITES': config.AUTOMOD_BLOCK_INVITES,
            'AUTOMOD_MAX_MENTIONS': config.AUTOMOD_MAX_MENTIONS,
            'AUTOMOD_MAX_CAPS_RATIO': config.AUTOMOD_MAX_CAPS_RATIO,
            'AUTOMOD_TIMEOUT_SECONDS': config.AUTOMOD_TIMEOUT_SECONDS,
            'DEFAULT_TIMEZONE': config.DEFAULT_TIMEZONE,
        }

    @app.put('/api/workspaces/{name}/settings')
    async def api_put_settings(name: str, body: SettingsBody):
        from .config import load_config
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(body.DEFAULT_TIMEZONE)
        except (ZoneInfoNotFoundError, ValueError):
            raise HTTPException(status_code=400, detail=f'Unknown timezone: {body.DEFAULT_TIMEZONE}')

        if not (0.0 <= body.AUTOMOD_MAX_CAPS_RATIO <= 1.0):
            raise HTTPException(status_code=400, detail='AUTOMOD_MAX_CAPS_RATIO must be between 0 and 1.')

        path = _workspace_dir(name) / 'config.yaml'
        config = load_config(path)
        config.ENABLE_SAFETY = body.ENABLE_SAFETY
        config.ENABLE_OUTPUT_JUDGE = body.ENABLE_OUTPUT_JUDGE
        config.CONFIRM_DANGEROUS_TOOLS = body.CONFIRM_DANGEROUS_TOOLS
        config.ENABLE_XP = body.ENABLE_XP
        config.XP_PER_MESSAGE = max(0, body.XP_PER_MESSAGE)
        config.XP_COOLDOWN_SECONDS = max(0, body.XP_COOLDOWN_SECONDS)
        config.XP_ANNOUNCE_LEVELUP = body.XP_ANNOUNCE_LEVELUP
        config.XP_LEVELUP_CHANNEL_ID = body.XP_LEVELUP_CHANNEL_ID
        config.ENABLE_AUTOMOD = body.ENABLE_AUTOMOD
        config.AUTOMOD_BANNED_WORDS = [w.strip() for w in body.AUTOMOD_BANNED_WORDS if w.strip()]
        config.AUTOMOD_BLOCK_INVITES = body.AUTOMOD_BLOCK_INVITES
        config.AUTOMOD_MAX_MENTIONS = max(0, body.AUTOMOD_MAX_MENTIONS)
        config.AUTOMOD_MAX_CAPS_RATIO = body.AUTOMOD_MAX_CAPS_RATIO
        config.AUTOMOD_TIMEOUT_SECONDS = max(0, body.AUTOMOD_TIMEOUT_SECONDS)
        config.DEFAULT_TIMEZONE = body.DEFAULT_TIMEZONE
        config.save(path)
        return {'ok': True}

    @app.post('/api/workspaces/{name}/start')
    async def api_start(name: str):
        _runner(name).start()
        return {'ok': True, 'running': True}

    @app.post('/api/workspaces/{name}/stop')
    async def api_stop(name: str):
        _runner(name).stop()
        return {'ok': True, 'running': False}

    @app.get('/api/workspaces/{name}/status')
    async def api_status(name: str):
        return {'running': _runner(name).running}

    @app.get('/api/workspaces/{name}/logs')
    async def api_logs(name: str):
        return JSONResponse({'lines': list(_runner(name).logs)})

    return app


def find_free_port(preferred: int, attempts: int = 50) -> int:
    for offset in range(attempts):
        candidate = preferred + offset
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            if sock.connect_ex(('127.0.0.1', candidate)) != 0:
                return candidate
    raise RuntimeError('Could not find a free port.')


def serve(preferred_port: int = 6767, host: str = '127.0.0.1'):
    import uvicorn

    port = find_free_port(preferred_port)
    if port != preferred_port:
        print(f'Port {preferred_port} is busy, using {port} instead.')
    print(f'Chloride GUI running at http://{host}:{port}')
    uvicorn.run(build_app(), host=host, port=port, log_level='warning')


PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Chloride</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin: 0; font-family: ui-sans-serif, system-ui, sans-serif; background: #0d1117; color: #e6edf3; }
  header { padding: 16px 24px; border-bottom: 1px solid #21262d; display: flex; align-items: center; gap: 12px; }
  header h1 { font-size: 18px; margin: 0; font-weight: 600; }
  header .tag { font-size: 12px; color: #7d8590; }
  .wrap { display: flex; height: calc(100vh - 57px); }
  .sidebar { width: 260px; border-right: 1px solid #21262d; padding: 16px; overflow-y: auto; }
  .main { flex: 1; padding: 24px; overflow-y: auto; }
  .ws { padding: 8px 10px; border-radius: 6px; cursor: pointer; display: flex; justify-content: space-between; align-items: center; }
  .ws:hover { background: #161b22; }
  .ws.active { background: #1f6feb33; }
  .dot { width: 8px; height: 8px; border-radius: 50%; background: #484f58; }
  .dot.on { background: #3fb950; }
  input, textarea, select { width: 100%; background: #0d1117; color: #e6edf3; border: 1px solid #30363d; border-radius: 6px; padding: 8px; font-family: inherit; }
  textarea { min-height: 320px; font-family: ui-monospace, monospace; font-size: 13px; resize: vertical; }
  button { background: #238636; color: #fff; border: 0; border-radius: 6px; padding: 8px 14px; cursor: pointer; font-size: 14px; }
  button.secondary { background: #21262d; border: 1px solid #30363d; }
  button.danger { background: #da3633; }
  .row { display: flex; gap: 8px; align-items: center; margin-bottom: 16px; flex-wrap: wrap; }
  .tabs { display: flex; gap: 4px; margin-bottom: 16px; border-bottom: 1px solid #21262d; }
  .tab { padding: 8px 14px; cursor: pointer; border-bottom: 2px solid transparent; color: #7d8590; }
  .tab.active { color: #e6edf3; border-bottom-color: #f78166; }
  .logs { background: #010409; border: 1px solid #21262d; border-radius: 6px; padding: 12px; font-family: ui-monospace, monospace; font-size: 12px; white-space: pre-wrap; height: 480px; overflow-y: auto; }
  .muted { color: #7d8590; font-size: 13px; }
  .check { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; font-size: 14px; cursor: pointer; }
  .check input { width: auto; }
  h2 { font-size: 16px; }
  h3 { font-size: 14px; color: #7d8590; margin: 20px 0 10px; text-transform: uppercase; letter-spacing: 0.5px; }
  .field { margin-bottom: 12px; }
  .field label { display: block; font-size: 13px; margin-bottom: 4px; color: #adbac7; }
  .field.narrow input { max-width: 220px; }
  .hidden { display: none; }
</style>
</head>
<body>
<header>
  <h1>Chloride</h1>
  <span class="tag">bot control panel</span>
</header>
<div class="wrap">
  <div class="sidebar">
    <div class="row">
      <input id="newName" placeholder="new-bot-name">
    </div>
    <div class="row">
      <button onclick="createWs()">Create bot</button>
    </div>
    <div id="wsList"></div>
  </div>
  <div class="main">
    <div id="empty" class="muted">Select or create a bot to begin.</div>
    <div id="editor" class="hidden">
      <div class="row">
        <h2 id="wsTitle"></h2>
        <span style="flex:1"></span>
        <button id="startBtn" onclick="startWs()">Start</button>
        <button id="stopBtn" class="danger" onclick="stopWs()">Stop</button>
      </div>
      <div class="tabs">
        <div class="tab active" data-tab="config" onclick="switchTab('config')">Config</div>
        <div class="tab" data-tab="context" onclick="switchTab('context')">Context</div>
        <div class="tab" data-tab="settings" onclick="switchTab('settings')">Safety</div>
        <div class="tab" data-tab="logs" onclick="switchTab('logs')">Logs</div>
      </div>
      <div id="tab-config">
        <textarea id="configText"></textarea>
        <div class="row" style="margin-top:12px"><button onclick="saveConfig()">Save config</button></div>
      </div>
      <div id="tab-context" class="hidden">
        <textarea id="contextText"></textarea>
        <div class="row" style="margin-top:12px"><button onclick="saveContext()">Save context</button></div>
      </div>
      <div id="tab-settings" class="hidden">
        <h3>Safety</h3>
        <label class="check"><input type="checkbox" id="setSafety"> Enable safety (anti-jailbreak, untrusted-input wrapping, secret redaction)</label>
        <label class="check"><input type="checkbox" id="setJudge"> Enable output judge (second-pass review of non-admin replies)</label>
        <label class="check"><input type="checkbox" id="setConfirm"> Confirm dangerous tools (admin must approve run_shell / run_code)</label>

        <h3>Leveling</h3>
        <label class="check"><input type="checkbox" id="setXp"> Enable XP / leveling</label>
        <div class="field narrow"><label>XP per message</label><input type="number" id="setXpAmount" min="0"></div>
        <div class="field narrow"><label>XP cooldown (seconds)</label><input type="number" id="setXpCooldown" min="0"></div>
        <label class="check"><input type="checkbox" id="setXpAnnounce"> Announce level-ups</label>
        <div class="field narrow"><label>Level-up channel ID (blank = same channel)</label><input type="number" id="setXpChannel"></div>

        <h3>Auto-moderation</h3>
        <label class="check"><input type="checkbox" id="setAutomod"> Enable auto-moderation (runs before the AI replies)</label>
        <div class="field"><label>Banned words (one per line)</label><textarea id="setBannedWords" style="min-height:120px"></textarea></div>
        <label class="check"><input type="checkbox" id="setBlockInvites"> Block invite links</label>
        <div class="field narrow"><label>Max mentions per message (0 = off)</label><input type="number" id="setMaxMentions" min="0"></div>
        <div class="field narrow"><label>Max caps ratio 0-1 (0 = off)</label><input type="number" id="setMaxCaps" min="0" max="1" step="0.05"></div>
        <div class="field narrow"><label>Timeout on violation (seconds, 0 = none)</label><input type="number" id="setTimeout" min="0"></div>

        <h3>Reminders</h3>
        <div class="field narrow"><label>Default timezone (IANA)</label><input type="text" id="setTimezone" placeholder="UTC"></div>

        <p class="muted">Admins always bypass safety, XP, and auto-moderation. Changes take effect the next time the bot loads its config.</p>
        <div class="row" style="margin-top:12px"><button onclick="saveSettings()">Save settings</button></div>
      </div>
      <div id="tab-logs" class="hidden">
        <div class="logs" id="logBox"></div>
      </div>
    </div>
  </div>
</div>
<script>
let current = null;
let tab = 'config';
let logTimer = null;

async function api(path, opts) {
  const res = await fetch(path, opts);
  if (!res.ok) {
    const err = await res.json().catch(() => ({detail: res.statusText}));
    alert(err.detail || 'Error');
    throw new Error(err.detail);
  }
  return res.json();
}

async function loadList() {
  const list = await api('/api/workspaces');
  const el = document.getElementById('wsList');
  el.innerHTML = '';
  list.forEach(ws => {
    const div = document.createElement('div');
    div.className = 'ws' + (ws.name === current ? ' active' : '');
    div.onclick = () => select(ws.name);
    div.innerHTML = '<span>' + ws.name + '</span><span class="dot ' + (ws.running ? 'on' : '') + '"></span>';
    el.appendChild(div);
  });
}

async function createWs() {
  const name = document.getElementById('newName').value.trim();
  if (!name) return;
  await api('/api/workspaces', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({name})});
  document.getElementById('newName').value = '';
  await loadList();
  select(name);
}

async function select(name) {
  current = name;
  document.getElementById('empty').classList.add('hidden');
  document.getElementById('editor').classList.remove('hidden');
  document.getElementById('wsTitle').textContent = name;
  const cfg = await api('/api/workspaces/' + name + '/config');
  document.getElementById('configText').value = cfg.content;
  const ctx = await api('/api/workspaces/' + name + '/context');
  document.getElementById('contextText').value = ctx.content;
  await loadList();
  refreshStatus();
  switchTab('config');
}

function switchTab(name) {
  tab = name;
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.tab === name));
  ['config', 'context', 'settings', 'logs'].forEach(t => document.getElementById('tab-' + t).classList.toggle('hidden', t !== name));
  if (name === 'logs') {
    pollLogs();
    logTimer = setInterval(pollLogs, 2000);
  } else if (logTimer) {
    clearInterval(logTimer);
    logTimer = null;
  }
  if (name === 'settings') {
    loadSettings();
  }
}

async function loadSettings() {
  const s = await api('/api/workspaces/' + current + '/settings');
  document.getElementById('setSafety').checked = s.ENABLE_SAFETY;
  document.getElementById('setJudge').checked = s.ENABLE_OUTPUT_JUDGE;
  document.getElementById('setConfirm').checked = s.CONFIRM_DANGEROUS_TOOLS;
  document.getElementById('setXp').checked = s.ENABLE_XP;
  document.getElementById('setXpAmount').value = s.XP_PER_MESSAGE;
  document.getElementById('setXpCooldown').value = s.XP_COOLDOWN_SECONDS;
  document.getElementById('setXpAnnounce').checked = s.XP_ANNOUNCE_LEVELUP;
  document.getElementById('setXpChannel').value = s.XP_LEVELUP_CHANNEL_ID == null ? '' : s.XP_LEVELUP_CHANNEL_ID;
  document.getElementById('setAutomod').checked = s.ENABLE_AUTOMOD;
  document.getElementById('setBannedWords').value = (s.AUTOMOD_BANNED_WORDS || []).join('\\n');
  document.getElementById('setBlockInvites').checked = s.AUTOMOD_BLOCK_INVITES;
  document.getElementById('setMaxMentions').value = s.AUTOMOD_MAX_MENTIONS;
  document.getElementById('setMaxCaps').value = s.AUTOMOD_MAX_CAPS_RATIO;
  document.getElementById('setTimeout').value = s.AUTOMOD_TIMEOUT_SECONDS;
  document.getElementById('setTimezone').value = s.DEFAULT_TIMEZONE;
}

function intOrNull(id) {
  const v = document.getElementById(id).value.trim();
  return v === '' ? null : parseInt(v, 10);
}

async function saveSettings() {
  await api('/api/workspaces/' + current + '/settings', {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({
    ENABLE_SAFETY: document.getElementById('setSafety').checked,
    ENABLE_OUTPUT_JUDGE: document.getElementById('setJudge').checked,
    CONFIRM_DANGEROUS_TOOLS: document.getElementById('setConfirm').checked,
    ENABLE_XP: document.getElementById('setXp').checked,
    XP_PER_MESSAGE: parseInt(document.getElementById('setXpAmount').value || '0', 10),
    XP_COOLDOWN_SECONDS: parseInt(document.getElementById('setXpCooldown').value || '0', 10),
    XP_ANNOUNCE_LEVELUP: document.getElementById('setXpAnnounce').checked,
    XP_LEVELUP_CHANNEL_ID: intOrNull('setXpChannel'),
    ENABLE_AUTOMOD: document.getElementById('setAutomod').checked,
    AUTOMOD_BANNED_WORDS: document.getElementById('setBannedWords').value.split('\\n').map(w => w.trim()).filter(w => w),
    AUTOMOD_BLOCK_INVITES: document.getElementById('setBlockInvites').checked,
    AUTOMOD_MAX_MENTIONS: parseInt(document.getElementById('setMaxMentions').value || '0', 10),
    AUTOMOD_MAX_CAPS_RATIO: parseFloat(document.getElementById('setMaxCaps').value || '0'),
    AUTOMOD_TIMEOUT_SECONDS: parseInt(document.getElementById('setTimeout').value || '0', 10),
    DEFAULT_TIMEZONE: document.getElementById('setTimezone').value.trim() || 'UTC',
  })});
  alert('Settings saved.');
}

async function pollLogs() {
  if (!current) return;
  const data = await api('/api/workspaces/' + current + '/logs');
  const box = document.getElementById('logBox');
  box.textContent = data.lines.join('\\n');
  box.scrollTop = box.scrollHeight;
}

async function saveConfig() {
  await api('/api/workspaces/' + current + '/config', {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({content: document.getElementById('configText').value})});
}

async function saveContext() {
  await api('/api/workspaces/' + current + '/context', {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({content: document.getElementById('contextText').value})});
}

async function startWs() {
  await api('/api/workspaces/' + current + '/start', {method: 'POST'});
  refreshStatus();
  loadList();
}

async function stopWs() {
  await api('/api/workspaces/' + current + '/stop', {method: 'POST'});
  refreshStatus();
  loadList();
}

async function refreshStatus() {
  if (!current) return;
  const s = await api('/api/workspaces/' + current + '/status');
  document.getElementById('startBtn').disabled = s.running;
  document.getElementById('stopBtn').disabled = !s.running;
}

loadList();
setInterval(loadList, 5000);
</script>
</body>
</html>"""
