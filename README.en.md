
## v0.7.1 / CLI v0.5.7 — single primary probe + Regional media

22 native checks (6 access / 12 services / 4 AI) + all134 extra IDs. Twelve duplicate raw IDs are truly removed; normal platforms have one primary state, not Web/API/Geo sub-states. ChatGPT/Claude/Gemini retain Web; Netflix catalogue, Prime access; DeepSeek/Qwen Intl/Kimi/GLM are explicitly API. Region only comes from that retained probe, otherwise empty. Spotify's conservative Legacy signup endpoint and Google captcha semantics remain.

Restore `Regional media — <English region>` for selected regional Video/Music extras using original sample names/order. Global + one auto-exit region only; no all-region scan. B-Global/Sky/HuluJP/RakutenJP/Bilibili copyright samples remain independent, and non-media stay in their proper purpose. Same font, single rounded frame, three columns and styles. Raw deletion is a breaking catalogue change; no aliases or fabricated results. Old history is replayed unchanged. See CHANGELOG for exact removals/limits; official source offer is this version's complete release ZIP. Publishing alone does not switch SG production or the CLI short link.

> **v0.7.1:** task-scoped official latest tools and read-only Kat SS/AnyTLS, explicit confirmed new installs, VLESS history only, Snell unchanged. Publication never deploys to an operator instance.

# GUKO

[![Docker Image](https://img.shields.io/badge/ghcr.io-guko-blue?logo=docker)](https://github.com/shui1iao/GUKO/pkgs/container/guko)
[![License: MIT + AGPL](https://img.shields.io/badge/License-MIT%20%2B%20AGPL-blue.svg)](NOTICE-STREAM.md)

[中文](README.md) | **English**

**A lightweight VPS / server management Telegram Bot: server status dashboard, SSH login management, common diagnostics, and protocol management entries.**

> Open a private chat with the Bot to view server lists, status details, traffic, and resource usage. Add servers, test SSH, and run IP quality, NodeQuality, TCPQuality, streaming unlock, NextTrace, GB5, Kat SS, Kat AnyTLS, Snell, and other common checks from Telegram.
> Whitelist mode is enabled by default, making it suitable for self-hosting.

---

## 🎯 Features

- **Server dashboard**: View online count, CPU / memory / disk usage, traffic, realtime network speed, and system information.
- **Add servers from Telegram**: Supports single-server add, batch import, edit, delete, and SSH connectivity tests.
- **Flexible SSH authentication**: Supports inherited default keys, per-server keys, existing key paths, uploaded / pasted private keys, and password login.
- **Common test shortcuts**: Supports IP quality, NodeQuality, TCPQuality, streaming unlock checks, NextTrace, GB5, and more.
- **IP / domain tools**: Supports IPPure official images and bgp.tools BGP route images.
- **Safe defaults**: Whitelist mode is required; GUKO focuses on common tests and does not provide a general remote command execution feature.
- **Docker-friendly deployment**: Includes Docker Compose, Makefile, and initialization script.

---

## 🚀 Quick Start

Prepare first:

1. Create a Bot via [@BotFather](https://t.me/BotFather) and get `BOT_TOKEN`.
2. Use [@userinfobot](https://t.me/userinfobot) or [@RawDataBot](https://t.me/RawDataBot) to get your numeric Telegram user ID.

Two deployment methods are available. **Docker Compose is recommended**.

### Method 1: Docker Compose (recommended, no git clone)

```bash
mkdir -p guko/keys guko/media guko/results guko/tmp
cd guko

curl -Lo docker-compose.yml https://github.com/shui1iao/GUKO/releases/latest/download/docker-compose.example.yml

cat > .env <<'EOF'
BOT_TOKEN=replace-me
ALLOWED_USERS=123456789
ADMIN_USERS=123456789
DATA_DIR=/data
GUKO_INV=/data/servers.json
MEDIA_DIR=/data/media
TMP_DIR=/data/tmp
KEYS_DIR=/data/keys
GUKO_DEFAULT_USER=root
GUKO_DEFAULT_PORT=22
GUKO_DEFAULT_KEY=/data/keys/id_ed25519
# Optional: prefer Kulin/Komari panel GeoIP results for region detection
KULIN_BASE_URL=
KULIN_USERNAME=
KULIN_PASSWORD=
KULIN_API_CACHE_TTL=300
ENABLE_BGP=true
ENABLE_IPPURE=true
ENABLE_IPQ=true
ENABLE_NQ=true
ENABLE_TCPQ=true
ENABLE_GB5=true
ENABLE_STREAM=true
ENABLE_NEXTTRACE=true
ALLOW_INSECURE_STARTUP=false
EOF

cat > servers.json <<'EOF'
{
  "defaults": {
    "ssh": {
      "user": "root",
      "port": 22,
      "key": "/data/keys/id_ed25519"
    }
  },
  "servers": []
}
EOF

nano .env
docker compose pull
docker compose up -d
docker compose logs -f
```

`docker-compose.yml` explicitly sets `name: guko`, so Docker / DockUP and other management panels show the project as `guko` instead of deriving a random name from the deployment directory.

Only these values need to be changed in the minimal config first:

```env
BOT_TOKEN=replace-me
ALLOWED_USERS=123456789
ADMIN_USERS=123456789
```

After startup, send `/addserver` to the Bot to add your first server.


### Method 2: Source build (development)

```bash
git clone https://github.com/shui1iao/GUKO.git
cd GUKO
cp .env.example .env
cp servers.example.json servers.json
mkdir -p keys media tmp
nano .env
docker build -f telegram-bot/Dockerfile -t guko:local .
docker run -d --name guko-bot --restart unless-stopped \
  --env-file .env \
  -v ./servers.json:/data/servers.json \
  -v ./keys:/data/keys \
  -v ./media:/data/media \
  -v ./tmp:/data/tmp \
  guko:local
docker logs -f guko-bot
```

---

## 💬 Usage

### Open dashboard

Send this to the Bot in a private chat:

```text
/start
```

The Bot will show the GUKO dashboard. Tap a server to view details.

### Add servers

Tap **➕ Add Server**, or send:

```text
/addserver
```

#### Add one server

Choose **Add single server**, then send:

```text
name IP [port] [user]
```

Examples:

```text
hk-01 203.0.113.10 22 root
jp-01 203.0.113.20:2222 debian
```

Then the Bot will ask for the login method:

- **Use default key / config**: Use `GUKO_DEFAULT_KEY` or `defaults.ssh.key` from `servers.json`.
- **Use existing key path**: Send a path such as `/data/keys/id_ed25519`.
- **Upload / paste a new private key**: Send SSH private key text, or upload a private key file. The Bot saves it to `/data/keys/`, sets permission to `600`, and tries an SSH login test.
- **Use password**: Send SSH password. The Bot saves the config and tries a login test.
- **Save only, skip test**: Only write the server record. You can add authentication later.

After adding, test with buttons or commands:

```text
/testssh hk-01
/testall
```

The server detail page also supports **Edit** and **Delete**. Delete requires confirmation and only removes local Bot configuration; it does not touch the remote machine.

#### Batch import

Choose **Batch import**. The Bot will ask:

1. Whether all servers use the same SSH port, or each line includes its own port.
2. Whether all servers use the same key, same password, per-line auth, or import without testing.

Common batch format:

```text
hk-01 203.0.113.10 root
jp-01 203.0.113.20 debian
sg-01 203.0.113.30 root
```

If choosing per-line ports:

```text
hk-01 203.0.113.10 22 root
jp-01 203.0.113.20 2222 debian
sg-01 203.0.113.30:53580 root
```

If choosing per-line auth:

```text
hk-01 203.0.113.10 22 root key:/data/keys/hk_ed25519
jp-01 203.0.113.20 2222 debian password:your-password
```

> Passwords / private keys sent through Telegram pass through Telegram cloud. Use a private Bot and restrict `ALLOWED_USERS`.

### Commands

- `/start` — Open GUKO dashboard
- `/list` — Show server list
- `/status` — Show overview status
- `/addserver` — Add / batch import servers
- `/testssh <name/IP/ID/alias>` — Test SSH for one server
- `/testall` — Batch test SSH
- `/exportconfig` — Export sanitized config
- `/info <name/IP/ID/alias>` — Show single-server details
- `/health` — Read-only health check
- `/jobs` — Show background jobs
- `/ip <IPv4 or domain>` — IPPure / BGP tools
- `/nexttrace <server> <target>` — Route tracing

---

## ⚙️ Configuration

`.env` example:

```env
BOT_TOKEN=replace-me
ALLOWED_USERS=123456789
ADMIN_USERS=123456789
DATA_DIR=/data
GUKO_INV=/data/servers.json
MEDIA_DIR=/data/media
TMP_DIR=/data/tmp
KEYS_DIR=/data/keys
GUKO_DEFAULT_USER=root
GUKO_DEFAULT_PORT=22
GUKO_DEFAULT_KEY=/data/keys/id_ed25519
ENABLE_BGP=true
ENABLE_IPPURE=true
ENABLE_IPQ=true
ENABLE_NQ=true
ENABLE_TCPQ=true
ENABLE_GB5=true
ENABLE_STREAM=true
ENABLE_NEXTTRACE=true
ALLOW_INSECURE_STARTUP=false
```

| Variable | Required | Default | Description |
|---|---:|---|---|
| `BOT_TOKEN` | Yes | - | Telegram Bot Token |
| `ALLOWED_USERS` | Yes | - | Allowed Telegram numeric user IDs, comma-separated |
| `ADMIN_USERS` | No | `ALLOWED_USERS` | Admin IDs; can add / delete servers and use high-risk features |
| `DATA_DIR` | No | `/data` | Container data directory |
| `GUKO_INV` | No | `/data/servers.json` | Server inventory path |
| `MEDIA_DIR` | No | `/data/media` | Image and report output directory |
| `TMP_DIR` | No | `/data/tmp` | Temporary directory |
| `KEYS_DIR` | No | `/data/keys` | SSH private key storage directory |
| `GUKO_DEFAULT_USER` | No | `root` | Default SSH user |
| `GUKO_DEFAULT_PORT` | No | `22` | Default SSH port |
| `GUKO_DEFAULT_KEY` | No | `/data/keys/id_ed25519` | Default SSH private key path |
| `ENABLE_BGP` | No | `true` | Enable BGP image feature |
| `ENABLE_IPPURE` | No | `true` | Enable IPPure image feature |
| `ENABLE_IPQ` | No | `true` | Enable IP quality feature |
| `ENABLE_NQ` | No | `true` | Enable NodeQuality feature |
| `ENABLE_TCPQ` | No | `true` | Enable TCPQuality carrier quality, return-path, international, and speed-test entries |
| `ENABLE_GB5` | No | `true` | Enable GB5 feature |
| `ENABLE_STREAM` | No | `true` | Enable streaming unlock checks |
| `ENABLE_NEXTTRACE` | No | `true` | Enable NextTrace |
| `BGP_FETCH` | No | `/data/tools/bgp_fetch.py` | BGP image helper script path |
| `IPPURE_DOWNLOAD` | No | `/data/tools/download_ippure.js` | IPPure download script path |
| `ALLOW_INSECURE_STARTUP` | No | `false` | Skip security startup checks for development / migration |

> `BOT_TOKEN` and `ALLOWED_USERS` are required. Do not commit real `.env` files.

---

## 🛠 Operations

Persistent data lives in the installation directory:

```text
GUKO/
├── docker-compose.example.yml
├── .env
├── servers.json       # private server inventory
├── keys/              # SSH private keys
├── media/             # report images / output files
└── tmp/               # temporary files
```

Common commands:

```bash
cd <install-dir>
docker compose ps
docker compose logs -f
docker compose restart
docker compose down
```

Upgrade:

```bash
cd <install-dir>
git pull
docker compose pull
docker compose up -d
```

Or use Makefile:

```bash
make up
make logs
make restart
make down
```

---

## 🧾 Batch add via config file

It is recommended to put shared defaults under `defaults.ssh`, and only override differences per server:

```json
{
  "defaults": {
    "ssh": {
      "user": "root",
      "port": 22,
      "key": "~/.ssh/id_ed25519"
    }
  },
  "servers": [
    {
      "name": "hk-01",
      "host": "203.0.113.10"
    },
    {
      "name": "jp-01",
      "host": "203.0.113.20",
      "ssh": {
        "user": "debian",
        "port": 2222,
        "key": "~/.ssh/jp_ed25519"
      }
    },
    {
      "name": "sg-password",
      "host": "203.0.113.30",
      "ssh": {
        "auth": "password",
        "password": "change-me"
      }
    }
  ]
}
```

Legacy format is still supported:

```json
{
  "name": "legacy",
  "host": "203.0.113.40",
  "user": "root",
  "port": 53580,
  "key": "/data/keys/server_key"
}
```

Test after batch import:

```bash
./guko.py list
./guko.py run hk-01 'hostname'
```

You can also export sanitized config from the Bot:

```text
/exportconfig
```

---

## 🧩 Optional tools

IPQuality and NodeQuality default to IPv4 only. Add/import detects IPv6 once and persists the address, availability, reason, and timestamp. Menus, selection, and start callbacks read saved state without SSH probes. Saved availability enables dual-stack; saved unavailability hides it with a reason. Actual tests refresh capability within the same SSH invocation. If IPv6 is confirmed disabled or no global address remains, the stale address is cleared and the result explicitly reports missing IPv6 and the updated server state. IPv4 tests can rediscover restored IPv6; SSH/probe command failures, timeouts, and invalid responses never erase known addresses. IPQuality retains both independent reports, including URL-less IPv6 Lite, and preserves partial results on timeout.

GUKO can enable IP quality, NodeQuality, TCPQuality, streaming unlock checks, NextTrace, GB5, BGP images, IPPure images, and other tools as needed. The streaming entry uploads and SHA256-verifies the official latest Service Unlock standalone binary frozen with same-release checksums and full source through existing SSH authentication, then runs it once with default actual-exit-country auto selection. Failure/unmapped country selects global with a reason. Its single-frame PNG and JSON are from one measurement; no legacy RRC/supplement tasks or remote runtime installation. Native34 remain system-selected; only extra probes use their resolved family. Complete exit1/Unknown reports are valid, with renderer/storage/delivery errors separate from probe results. Legacy two-image history is retained. TCPQuality is organized into five task-focused entries: carrier quality, return path, international connectivity, carrier speed test, and complete test. Carrier quality and return-path checks support IPv4 or IPv6 when configured; international connectivity uses IPv4 as supported upstream. Speed-test and complete-test entries show a traffic warning and require confirmation to prevent accidental runs. The complete test runs carrier IPv4/IPv6, international connectivity, and carrier speed tests; CERNET checks are excluded. Report-producing modes upload results to `tcpquality.ibsgss.uk`, while return-path mode sends text directly. Related buttons can be disabled with environment variables.

---

## 🧩 Source run (development)

```bash
git clone https://github.com/shui1iao/GUKO.git
cd GUKO
python3 -m venv .venv
. .venv/bin/activate
pip install -r telegram-bot/requirements.txt
cp .env.example .env
cp servers.example.json servers.json
nano .env
python3 telegram-bot/bot.py
```

Syntax check:

```bash
make check
```

---

## 🔐 Privacy

- The repository does not contain any Bot Token, real user ID, server password, or private key.
- `.env`, `servers.json`, `keys/`, `media/`, and `tmp/` are ignored by Git. Do not commit real configuration.
- Whitelist mode is enabled by default. The Bot refuses to start when allowed users are not configured.
- IPPure, bgp.tools, NodeQuality, TCPQuality, Service Unlock streaming checks, and similar features will access corresponding third-party services. Streaming uses fixed anonymous probes and at most two HTTPS country sources for auto scheduling; no account credentials or old upstream script execution. TCPQuality report-producing modes upload results to `tcpquality.ibsgss.uk` to generate a public report; route-only mode does not upload a report.
- Deleting a server only removes local Bot configuration. It does not delete or reinstall the remote machine.

## License

Original portions: MIT. Unified integration modifications: AGPL-3.0-only; the combined image is not MIT-only. See NOTICE-STREAM.md.

---

## Stream integration distribution

The public Dockerfile builds linux/amd64 and linux/arm64 independently of private
local images. Every new task resolves official latest metadata and freezes its
binary, hashes and complete source; failures never fall back to old cache.
The explicit v0.5.7 raw156/single-probe-regional contract is supported; unknown future
contracts stop. Existing history is not rerun or relabelled.

`python scripts/build-source.py` creates tracked exact GUKO Corresponding Source;
per-task CLI complete source is offered independently at its frozen release.
No inventory, credentials, private fonts or recursive generated archives are
included. MIT/AGPL obligations and third-party notices remain intact.

## Kat proxy integration (v0.7.1)

SS and AnyTLS each have one entry reading all supported Kat instances through
a bounded POSIX/systemd/proc snapshot, parsed inside GUKO. Existing nodes never
run the Manager, require remote Python or change files/services. Unknown or
conflicting authority fails closed. VLESS new actions and executors are removed;
old callbacks explicitly reject, while historical records/URI display and remote
VLESS services stay untouched. Snell is unchanged.

Only a separate, expiring, user/chat/server/protocol-bound confirmation may install
a genuinely absent protocol. Missing prerequisites stop; dependencies and existing
shared kernels are never upgraded. The same-commit Kat-Manager wrapper/helpers
and actual reused/new Kat-Server identity are recorded. Readback is file evidence,
not connectivity or effective-credential verification. Unknown TLS export is marked
unsupported, never silently insecure. Release verification uses offline regressions and isolated containers, not live
measurements, installations or Telegram messages. Publishing does not deploy.

Exact Corresponding Source: https://github.com/shui1iao/GUKO/releases/download/v0.7.1/guko-v0.7.1-source.zip ; verify SHA256SUMS in the same Release. OCI revision identifies the source commit. MIT/AGPL and third-party notices remain applicable.
