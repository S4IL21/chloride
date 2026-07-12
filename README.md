# chloride

Chloride is a deep AI agent, with a Discord integration.

## Installation

```
$ gh repo clone S4IL21/chloride
$ cd chloride
$ pip install -e . -U
```

### Updating

```
$ cd chloride
$ git pull
```

## Usage

```
$ chloride create my-bot
$ cd my-bot
$ # Edit the `config.yaml` and `config.md.j2` files in a text editor.
$ chloride run
```

### Web GUI

```
$ chloride gui
$ # opens a control panel on http://127.0.0.1:6767 (falls back to the next free port)
$ chloride gui --port 8080
```

The GUI lets you create bots, edit their config and context, toggle the safety settings (safety, output judge, dangerous-tool confirmation) from checkboxes on the Safety tab, view live logs, and start/stop bots from the browser.

### Reminders and stats

- `/remind 1h30m take a break` schedules a reminder (add `repeat:true` to recur). The agent can also set reminders itself via the `set_reminder` tool. Reminders persist across restarts and fire late with a "(delayed)" tag if the bot was offline when they were due.
- `/reminders` lists your pending reminders and `/cancel_reminder <id>` cancels one.
- `/stats` shows stored message volume, distinct conversations, pending reminders, and the most active channels.
- `/timezone America/New_York` sets your timezone so `/remind 9am standup` fires at your local 9am. Reminders also support opt-in topics: `/subscribe events`, then `/remind 1h event starting topic:events` pings every subscriber. Add `rsvp:true` for Going / Not going / Maybe buttons with attendance tracking.

### Leveling

Turn on `ENABLE_XP` and members earn XP per message (once per `XP_COOLDOWN_SECONDS`), leveling up as they go. `/rank` shows your level and `/leaderboard` shows the top members. Level-up messages can be routed to `XP_LEVELUP_CHANNEL_ID`.

### Auto-moderation

Turn on `ENABLE_AUTOMOD` to screen every message before the AI ever sees it. Rules: `AUTOMOD_BANNED_WORDS`, `AUTOMOD_BLOCK_INVITES`, `AUTOMOD_MAX_MENTIONS`, and `AUTOMOD_MAX_CAPS_RATIO`. Offending messages are deleted and the author optionally timed out for `AUTOMOD_TIMEOUT_SECONDS`. Admins are exempt.

### Scheduled announcements

Admins can post recurring announcements with a cron expression: `/announce_add "0 9 * * *" "Good morning!"` (9am daily). `/announce_list` and `/announce_remove` manage them.

### Command usage

`/command_stats` shows a leaderboard of the most-used slash commands.

The GUI Settings tab exposes the full safety, leveling, auto-moderation, and reminder tuning: the on/off toggles plus editable fields for XP-per-message, XP cooldown, level-up channel, the banned-words list, invite/mention/caps thresholds, violation timeout, and the default timezone. It validates the timezone and caps ratio before saving.

### Modes and access

- `MODE: server` lets everyone chat with the bot, subject to per-tier tool restrictions.
- `MODE: management` locks the bot down so only admins can talk to it.
- `ADMIN_ROLE_OR_USER_IDS` get the full admin toolset and the `/autoreply` and `/mode` slash commands.
- `AUTO_REPLY_CHANNEL_IDS` are channels where the bot always replies without being pinged.
- `/search` is available to everyone.

### Conversation history scoping

`HISTORY_SCOPE` controls how history is partitioned:

- `channel` (default) - everyone in a channel shares one history.
- `user` - each user has one private history that follows them across channels.
- `channel_user` - each user has a private history per channel.
- `global` - one shared history for the whole server.

Per-channel overrides win over the global scope: `PRIVATE_CHANNEL_IDS` (per-user private) and `SHARED_CHANNEL_IDS` (everyone shared). `SHARE_GROUPS` lets listed users pool a single shared history. Admins can toggle these live with `/history_scope`, `/private`, and `/shared`, and anyone can clear their own conversation with `/reset`.

### Safety

With `ENABLE_SAFETY` on (default), the bot resists jailbreak and prompt-injection attempts, treats every non-admin message as untrusted data, refuses to disclose its system prompt, and redacts credentials from its replies. Admins are trusted operators and bypass the user-facing guardrails and rate limit. `BLOCKED_USER_IDS` are ignored entirely, and `RATE_LIMIT_PER_MINUTE` throttles per-user message rate (0 disables it).

`ENABLE_OUTPUT_JUDGE` adds a second-pass model review of each non-admin reply and swaps it for a refusal if it leaks secrets, discloses the system prompt, or is unsafe (one extra model call per message; fails open to the redaction net if the judge is unavailable).

`CONFIRM_DANGEROUS_TOOLS` makes non-admin-triggered `CONFIRM_TOOLS` calls (`run_shell` / `run_code` by default) wait for an admin to press Approve on a confirmation prompt before they execute. Admin-triggered runs are never gated. The final guarantee is the tool gate itself: even a fully jailbroken conversation cannot invoke a tool the user's tier does not allow, because that is enforced in code, not in the prompt.

### Welcome and goodbye

Set `WELCOME_MESSAGE` / `GOODBYE_MESSAGE` (and optionally `WELCOME_CHANNEL_ID`) to greet joining and departing members. Messages support `{mention}`, `{user}`, `{server}`, and `{count}` placeholders.
