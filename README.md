# Personal Assistant

A modular, local-first personal AI assistant built in Python.

## Initial goals

- Run a local model through Ollama
- Store canonical personal data in SQLite
- Keep model, memory, tools, browser, and interface replaceable
- Require explicit approval before external or sensitive actions
- Keep personal runtime data, browser state, secrets, logs, and databases out of Git
- Begin as a single-agent assistant, with a future path to bounded multi-agent coordination

## Project status

Module 0 and its Module 0.1 hardening gate are complete: a tested local chat
foundation with replaceable components and deterministic safety boundaries.
The Module 1 encrypted persistent-memory implementation is complete. It includes
redacted auditing, verified SQLCipher storage, checksummed migrations, typed
revisioned records, bounded retrieval, quarantined automatic suggestions,
portable recovery, encrypted backup and guided restore, and a bounded chat-
context adapter. A new installation stays session-only until the owner completes
the trusted local setup. A lean native Module 1.5 interface now provides local
setup, recovery unlock, session-only use, and streaming chat without a browser
or UI web server. A verified recovery entry can enroll protected automatic
unlock for later native-app launches. Tools are not enabled.

## Set up the project

The project uses `uv` 0.12.5 for locked, cross-platform dependency management.
After installing that pinned version of
[`uv`](https://docs.astral.sh/uv/getting-started/installation/), run:

```bash
uv sync --locked
```

The committed `uv.lock` records package hashes and compatible SQLCipher wheels
for the supported Python 3.11–3.14 range. Do not edit it manually. `setuptools`
remains the package build backend; `uv` manages resolution, installation,
environments, and project commands.

## Run the native app

From the project folder:

```bash
uv run --locked personal-assistant-ui
```

The native app guides first-run encrypted-memory setup or recovery unlock, then
starts Ollama and opens streaming chat. After one verified recovery entry, later
native launches use the operating system's protected credential store and do
not show a startup passphrase field. Unlock is attempted before Ollama is loaded,
and model output is displayed only as inert local text.
Completed answers receive code-defined native formatting for headings, lists,
bold emphasis, and inline code. Model content is never interpreted as HTML and
cannot create active links or remote resources.

The command-line interface remains a developer and recovery fallback:

```bash
uv run --locked python -m personal_assistant
```

### Set up persistent memory

Persistent memory requires a recovery passphrase and a different high-risk
passcode. The native app collects both through masked local fields. Never enter
either secret in chat or as a command-line argument. The fallback administration
commands use hidden trusted prompts:

```bash
uv run --locked python -m personal_assistant.memory_admin setup
uv run --locked python -m personal_assistant.memory_admin verify-recovery
```

The recovery passphrase derives the SQLCipher key. The portable security
manifest and database never contain it. After a successful native-app unlock,
the app stores it in the operating system's protected credential store so later
native launches can unlock automatically. Keep a separate copy: the credential
store entry is machine-local and may be lost during account, operating-system,
or computer recovery. Without either that entry or the recovery passphrase, the
database and its backups are unrecoverable.
The high-risk passcode authorizes one exact sensitive operation at a time; it
cannot override a prohibited action. Failed attempts are audited and the
lockout survives command restarts.

On macOS, the native app requires Touch ID or the Mac login password through
Apple Local Authentication before it reads the stored Keychain passphrase.
macOS may also accept a paired Apple Watch when that owner-authentication method
is enabled in System Settings.
The unsigned development process cannot attach that rule directly to the
Keychain item, so malicious code already running as the same OS user remains
inside the current trust boundary. Binding user presence directly to the item
is a signed-package release gate. Automatic unlock never bypasses the separate
high-risk passcode, and copying only the data directory to another machine does
not copy the protected credential. The command-line recovery interface
continues to request the recovery passphrase explicitly.

By default, persistent files use one stable local directory:
`~/.personal-assistant/`. The encrypted database is always
`~/.personal-assistant/memory.db`; security metadata and the redacted audit log
sit beside it. Ordinary startup must reopen that existing database and refuses
to create a replacement if it is missing. Database creation is enabled only
inside the explicit first-run setup transaction. Set an absolute
`PERSONAL_ASSISTANT_DATA_DIR` before first setup to choose another location.

For an existing installation with an enrolled Keychain credential, native
launches now request Touch ID or the Mac login password before automatic unlock.
If the credential is absent or stale, the app asks for the recovery passphrase
once, verifies the encrypted database, and re-enrolls automatic unlock. Use
`/remember <information>` or `remember that <information>` for an explicit
ordinary memory. Automatic analysis runs after the visible answer. An exact
low-risk declarative sentence copied from your current message may become
confirmed memory. The model may identify an exact phrase, but deterministic code
expands it to the complete current-user sentence and stores only that sentence—
not the model's subject or paraphrase. Questions, mismatched or inferred text,
sensitive content, conflicts, and credential-like material remain rejected or
enter the expiring candidate inbox. Review candidates through the trusted
commands:

```bash
uv run --locked python -m personal_assistant.memory_admin candidates
uv run --locked python -m personal_assistant.memory_admin confirm RECORD_ID
uv run --locked python -m personal_assistant.memory_admin reject RECORD_ID
```

In native chat, Enter sends the current prompt and Shift+Enter inserts a new
line. The Settings page persists a model context window, default response limit,
and response ceiling for the next launch. The context window is bounded to
2,048–131,072 tokens and must retain at least 1,024 tokens for input; the
response ceiling cannot exceed the code-enforced 2,000-token maximum. Settings
changes are stored as non-secret versioned JSON and audited without chat or
personal-memory content.

Candidate lists show metadata only; sensitive candidate content stays hidden
until the high-risk passcode is verified. The trusted interface also provides
bounded owner controls without exposing these operations to the model:

```bash
uv run --locked python -m personal_assistant.memory_admin memories
uv run --locked python -m personal_assistant.memory_admin inspect RECORD_ID
uv run --locked python -m personal_assistant.memory_admin history RECORD_ID
uv run --locked python -m personal_assistant.memory_admin correct RECORD_ID
uv run --locked python -m personal_assistant.memory_admin controls RECORD_ID
uv run --locked python -m personal_assistant.memory_admin archive RECORD_ID
uv run --locked python -m personal_assistant.memory_admin restore-record RECORD_ID
uv run --locked python -m personal_assistant.memory_admin delete RECORD_ID
uv run --locked python -m personal_assistant.memory_admin purge RECORD_ID
uv run --locked python -m personal_assistant.memory_admin profile EXACT_ALIAS
```

History, sensitive content, profile assembly, privacy-control changes, and
permanent purge use the passcode gate. Purge also requires an exact typed
confirmation and leaves only a suppression-ledger identifier so restores do
not resurrect the deleted content. In chat, `ask before mentioning` memories
are withheld until a natural yes/no clarification, `only when directly asked`
memories require a direct memory question, and restricted memories never enter
model context.

Natural recall removes conversational scaffolding such as “what do you know”
before indexed matching. It first requires all meaningful terms, then uses a
bounded partial-match fallback only when that strict search finds nothing.
Explicit questions about a saved subject count as consent to use an applicable
`ask before mentioning` record; incidental relevance still requires a natural
clarification.

To use encrypted daily backups, create an external destination first and set
its absolute path before setup and every relevant run:

```bash
PERSONAL_ASSISTANT_BACKUP_DIR=/absolute/external/path \
  uv run --locked python -m personal_assistant.memory_admin backup
uv run --locked python -m personal_assistant.memory_admin list-backups
uv run --locked python -m personal_assistant.memory_admin restore SNAPSHOT_NAME
```

Restore displays and binds approval to the snapshot name, byte count, digest,
and target, requires typed confirmation plus the high-risk passcode, creates a
pre-restore snapshot, and reapplies the permanent-deletion ledger.

Model output is treated as untrusted terminal text. Control and invisible
formatting characters are displayed as escaped code points instead of being
executed by the terminal. Expected Ollama, model, response, configuration, and
interruption failures produce short user-safe messages without exposing raw
service details.

- Type `quit` or `exit` to close the app.
- Type `/long <question>` for up to 1,200 response tokens.
- Type `/max <question>` for up to 2,000 response tokens.
- Type `/limit <1-2000> <question>` to choose a custom response budget.

Recent chat turns are referenced in application RAM only while the app is open.
Complete turns are evicted from oldest to newest when they exceed the configured
history budget. Closing the app drops the application's references and the app
does not deliberately save this conversation to a file or database. Python,
Ollama, macOS, swap, crash reports, or other system facilities may retain bytes
temporarily; this is not a claim of secure physical memory erasure.

Conversation roles remain structurally separate when sent to the model, so
user text cannot become a trusted system or assistant message. The context
budget conservatively counts the system instruction, current message, recent
turns, message framing, and reserved response space. An individual message
that cannot fit is rejected with a request to shorten it.

The model uses a 400-token normal response budget and an application-wide hard
ceiling of 2,000 response tokens. Commands and future UI settings may choose a
value up to that ceiling, but prompts and model adapters cannot exceed it.

## Settings

Safe shared defaults are in `src/personal_assistant/config.py`.

For a machine-local temporary override, set an environment variable before running the app:

```bash
PERSONAL_ASSISTANT_MODEL_NAME=qwen3:8b uv run --locked python -m personal_assistant
```

The shared default context window is 16,384 tokens. It can be changed
independently of the 2,000-token response ceiling; for example, a machine with
more model capacity can use 32K:

```bash
PERSONAL_ASSISTANT_CONTEXT_TOKENS=32768 uv run --locked python -m personal_assistant
```

Available overrides include:

- `PERSONAL_ASSISTANT_OLLAMA_URL`
- `PERSONAL_ASSISTANT_MODEL_NAME`
- `PERSONAL_ASSISTANT_CONTEXT_TOKENS`
- `PERSONAL_ASSISTANT_RESPONSE_TOKENS`
- `PERSONAL_ASSISTANT_KEEP_ALIVE`
- `PERSONAL_ASSISTANT_HISTORY_TOKENS`
- `PERSONAL_ASSISTANT_LONG_RESPONSE_TOKENS`
- `PERSONAL_ASSISTANT_MAX_RESPONSE_TOKENS`
- `PERSONAL_ASSISTANT_MEMORY_ENABLED`
- `PERSONAL_ASSISTANT_DATA_DIR`
- `PERSONAL_ASSISTANT_BACKUP_DIR`
- `PERSONAL_ASSISTANT_MEMORY_TOKENS`
- `PERSONAL_ASSISTANT_AUTOMATIC_MEMORY`

The Ollama URL must be an explicit numeric loopback HTTP address with a port,
such as `http://127.0.0.1:11434` or `http://[::1]:11434`. Hostnames and remote
addresses are rejected. Ollama requests ignore environment proxy settings and
refuse HTTP redirects, so the local adapter cannot be redirected through a
remote service. A future remote-model adapter must be separate and opt-in.

`.env` variants, private-key containers, credential exports, cookie exports,
token files, password databases, and the local `secrets/` directory are ignored
by Git. The initial version does not automatically read an `.env` file. Ignore
rules reduce accidental commits but are not a secret manager or a substitute
for reviewing staged changes.

## Safety principles

The complete project doctrine and review checklist live in
[`docs/security-principles.md`](docs/security-principles.md). These assumptions
govern future model, memory, browser, tool, data, interface, and audit choices.

- The model never receives unrestricted permission to act.
- Sensitive actions require an opaque, one-use approval receipt bound to the
  exact action and arguments. Receipts expire after at most five minutes and
  can be issued only by trusted local passcode handling, not by the model.
- Credentials are entered manually and are never stored in memory or logs.
- Recovery and high-risk secrets are hidden from command arguments, model
  context, memory, and logs. Derived key bytes are cleared on normal shutdown
  on a best-effort basis.
- Runtime personal data stays local and is excluded from Git.
- The Ollama adapter can connect only to an explicit loopback address.
- Every model request is limited to at most 2,000 response tokens.
- The model has no web, browser, file, raw database, key, or tool access. The
  application exposes only the bounded memory adapter described above.

A local passcode meaningfully reduces accidental or conversational misuse, but
it is not a defense against an attacker who already controls the same operating-
system account and can modify the program or read its running process. Full-disk
security, account security, updates, physical control, and offline encrypted
backups remain separate layers. Windows runtime behavior is not yet verified.
