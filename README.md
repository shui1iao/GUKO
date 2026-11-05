## v0.7.2 / CLI v0.5.8 — 官方同平台辅助地区

仍然每平台一项目一主结果，22原生＋extra134/raw156和Regional原名/auto单地区保。ChatGPT/TikTok/YouTube/Spotify/Reddit/Google从其官方源补辅助国家；主成功失败/错误/detail/primary时间/退出码不改，已有Netflix/Claude/Gemini/Prime等地区不覆盖。YouTube不以Google/出口国家补值，Spotify地区不推出注册Yes。没有可信国家仍空，不保证登录播放。

六项目增加有界辅助请求，共用原direct/system-selected core Stack，不保证同实际IP/固定族；每项目辅助总预算≤--timeout，Google两步共享，可能增加墙钟耗时。services仅google_captcha/spotify_signup/reddit_guest新增可选ISO2 region，严格JSON消费者需同步0.5.8。旧history原图/JSON/sourceoffer不重测或补国家。短链/SG生产由主控另取当时空闲确认后切换，本版公开不代表已部署。


## v0.7.2 / CLI v0.5.8 — single primary probe + Regional media

22 native checks (6 access / 12 services / 4 AI) + all134 extra IDs. Twelve duplicate raw IDs are truly removed; normal platforms have one primary state, not Web/API/Geo sub-states. ChatGPT/Claude/Gemini retain Web; Netflix catalogue, Prime access; DeepSeek/Qwen Intl/Kimi/GLM are explicitly API. Region only comes from that retained probe, otherwise empty. Spotify's conservative Legacy signup endpoint and Google captcha semantics remain.

Restore `Regional media — <English region>` for selected regional Video/Music extras using original sample names/order. Global + one auto-exit region only; no all-region scan. B-Global/Sky/HuluJP/RakutenJP/Bilibili copyright samples remain independent, and non-media stay in their proper purpose. Same font, single rounded frame, three columns and styles. Raw deletion is a breaking catalogue change; no aliases or fabricated results. Old history is replayed unchanged. See CHANGELOG for exact removals/limits; official source offer is this version's complete release ZIP. Publishing alone does not switch SG production or the CLI short link.

> **v0.7.2：官方逐任务查新＋Kat SS/AnyTLS。** 查新失败/不兼容即停止；VLESS仅保历史，Snell不变。公开发布不自动切运营实例。GB5官方无法确认最新版5系时明确停止。

# GUKO

[![Docker Image](https://img.shields.io/badge/ghcr.io-guko-blue?logo=docker)](https://github.com/shui1iao/GUKO/pkgs/container/guko)
[![License: MIT + AGPL](https://img.shields.io/badge/License-MIT%20%2B%20AGPL-blue.svg)](NOTICE-STREAM.md)

**中文** | [English](README.en.md)

**轻量 VPS / 服务器管理 Telegram Bot：服务器状态面板、SSH 登录管理、常用测试脚本入口**

> 私聊打开 Bot 就能查看服务器列表、状态详情、流量与资源占用；支持在 Telegram 内添加服务器、测试 SSH、运行 IP 质量 / NodeQuality / TCPQuality / 流媒体 / NextTrace / GB5 等常用检测。
> 默认白名单模式，适合自托管。

---

## 🎯 核心特性

- **服务器状态面板**：展示在线数量、CPU / 内存 / 硬盘、流量、实时网速、系统信息等。
- **Telegram 内添加服务器**：支持单台添加、批量导入、编辑、删除和 SSH 连通性测试。
- **灵活 SSH 鉴权**：支持默认密钥继承、每台独立密钥、已有密钥路径、上传 / 粘贴私钥、密码登录。
- **常用测试与协议入口**：支持 IP 质量、NodeQuality、TCPQuality、流媒体解锁、NextTrace、GB5、Kat SS、Kat AnyTLS、Snell 等任务。
- **IP / 域名工具**：支持 IPPure 官方图片与 bgp.tools BGP 路由图。
- **适合 Docker 部署**：提供 Docker Compose、Makefile 和初始化脚本。

---

## 🚀 快速开始

先准备：

1. 到 [@BotFather](https://t.me/BotFather) 创建 Bot，拿到 `BOT_TOKEN`。
2. 用 [@userinfobot](https://t.me/userinfobot) 或 [@RawDataBot](https://t.me/RawDataBot) 获取你的 Telegram 数字用户 ID。

提供 2 种部署方式，**推荐 Docker Compose**。

### 方式一：Docker Compose（推荐，无需 git clone）

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
# 可选：对接 Kulin/Komari 后，地区识别优先使用面板 GeoIP 结果
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

`docker-compose.yml` 已显式设置 `name: guko`，因此在 Docker / DockUP 等管理面板里会显示为 `guko`，不会因为部署目录不同变成随机目录名。

最小配置里只需要先改：

```env
BOT_TOKEN=replace-me
ALLOWED_USERS=123456789
ADMIN_USERS=123456789
```

启动后在 Bot 里发送 `/addserver` 添加第一台服务器。


### 方式二：源码构建（开发用）

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

## 💬 使用方式

### 打开面板

私聊 Bot 发送：

```text
/start
```

Bot 会显示 GUKO 总览面板，可以点服务器查看详情。

### 添加服务器

点击 **➕ 添加服务器**，或者发送：

```text
/addserver
```

#### 单台添加

选择 **添加单台**，按提示发送：

```text
名称 IP [端口] [用户]
```

示例：

```text
hk-01 203.0.113.10 22 root
jp-01 203.0.113.20:2222 debian
```

然后 Bot 会询问登录方式，支持密钥路径、上传 / 粘贴私钥、密码或先保存后测试。

添加后可用按钮或命令测试：

```text
/testssh hk-01
/testall
```

服务器详情页也支持 **编辑** 和 **删除**；删除需要二次确认，只会删除本地配置，不会操作远端机器。

#### 批量导入

选择 **批量导入** 后，Bot 会先问：

1. 是否全部使用同一个 SSH 端口，还是每台自己写端口。
2. 是否全部使用同一把密钥、同一个密码、每台自己写认证，还是先只导入不测试。

常用批量格式：

```text
hk-01 203.0.113.10 root
jp-01 203.0.113.20 debian
sg-01 203.0.113.30 root
```

如果选择“每台自己写端口”：

```text
hk-01 203.0.113.10 22 root
jp-01 203.0.113.20 2222 debian
sg-01 203.0.113.30:53580 root
```

如果选择“每台自己写认证”：

```text
hk-01 203.0.113.10 22 root key:/data/keys/hk_ed25519
jp-01 203.0.113.20 2222 debian password:your-password
```

> Telegram 里发送密码 / 私钥会经过 Telegram 云端。建议使用私有 Bot，并限制 `ALLOWED_USERS`。

### 命令

- `/start` — 打开 GUKO 面板
- `/list` — 查看服务器列表
- `/status` — 查看总览状态
- `/addserver` — 添加 / 批量导入服务器
- `/testssh <名字/IP/ID/别名>` — 测试单台服务器 SSH
- `/testall` — 批量测试 SSH
- `/exportconfig` — 导出脱敏配置
- `/info <名字/IP/ID/别名>` — 查看单台详情
- `/health` — 只读巡检
- `/jobs` — 查看后台任务
- `/ip <IPv4 或域名>` — IPPure / BGP 工具
- `/nexttrace <服务器> <目标>` — 路由追踪

---

## ⚙️ 配置说明

`.env` 示例：

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

| 变量 | 是否必填 | 默认值 | 说明 |
|---|---:|---|---|
| `BOT_TOKEN` | 是 | - | Telegram Bot Token |
| `ALLOWED_USERS` | 是 | - | 允许使用 Bot 的 Telegram 数字 ID，多个用英文逗号分隔 |
| `ADMIN_USERS` | 否 | `ALLOWED_USERS` | 管理员 ID，能添加 / 删除服务器、执行高危功能 |
| `DATA_DIR` | 否 | `/data` | 容器内数据目录 |
| `GUKO_INV` | 否 | `/data/servers.json` | 服务器清单路径 |
| `MEDIA_DIR` | 否 | `/data/media` | 图片和报告输出目录 |
| `TMP_DIR` | 否 | `/data/tmp` | 临时文件目录 |
| `KEYS_DIR` | 否 | `/data/keys` | SSH 私钥保存目录 |
| `GUKO_DEFAULT_USER` | 否 | `root` | 默认 SSH 用户 |
| `GUKO_DEFAULT_PORT` | 否 | `22` | 默认 SSH 端口 |
| `GUKO_DEFAULT_KEY` | 否 | `/data/keys/id_ed25519` | 默认 SSH 私钥路径 |
| `ENABLE_BGP` | 否 | `true` | 是否启用 BGP 图功能 |
| `ENABLE_IPPURE` | 否 | `true` | 是否启用 IPPure 图功能 |
| `ENABLE_IPQ` | 否 | `true` | 是否启用 IP 质量功能 |
| `ENABLE_NQ` | 否 | `true` | 是否启用 NodeQuality 功能 |
| `ENABLE_TCPQ` | 否 | `true` | 是否启用 TCPQuality 三网质量、回程、国际互联和测速入口 |
| `ENABLE_GB5` | 否 | `true` | 是否启用 GB5 功能 |
| `ENABLE_SS` | 否 | `true` | 是否启用 Kat SS 读取/确认安装入口 |
| `ENABLE_ANYTLS` | 否 | `true` | 是否启用 Kat AnyTLS 读取/确认安装入口 |
| `ENABLE_SNELL` | 否 | `true` | 是否启用 Snell 管理入口 |
| `ENABLE_STREAM` | 否 | `true` | 是否启用流媒体检测 |
| `ENABLE_NEXTTRACE` | 否 | `true` | 是否启用 NextTrace |
| `BGP_FETCH` | 否 | `/data/tools/bgp_fetch.py` | BGP 图片工具脚本路径 |
| `IPPURE_DOWNLOAD` | 否 | `/data/tools/download_ippure.js` | IPPure 下载脚本路径 |
| `ALLOW_INSECURE_STARTUP` | 否 | `false` | 开发 / 迁移时跳过安全启动检查 |

> `BOT_TOKEN` 和 `ALLOWED_USERS` 必须填写；不要把真实 `.env` 提交到仓库。

---

## 🛠 运维

所有持久化数据在安装目录下：

```text
GUKO/
├── docker-compose.example.yml
├── .env
├── servers.json       # 私有服务器清单
├── keys/              # SSH 私钥
├── media/             # 报告图片 / 输出文件
└── tmp/               # 临时文件
```

常用命令：

```bash
cd <安装目录>
docker compose ps
docker compose logs -f
docker compose restart
docker compose down
```

升级：

```bash
cd <安装目录>
git pull
docker compose pull
docker compose up -d
```

也可以使用 Makefile：

```bash
make up
make logs
make restart
make down
```

---

## 🧾 直接写配置文件批量添加

推荐在 `defaults.ssh` 里写公共默认值，每台服务器只覆盖不同的部分：

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

兼容旧格式，下面这种仍然可用：

```json
{
  "name": "legacy",
  "host": "203.0.113.40",
  "user": "root",
  "port": 53580,
  "key": "/data/keys/server_key"
}
```

批量添加后可以测试：

```bash
./guko.py list
./guko.py run hk-01 'hostname'
```

Bot 内还可以导出脱敏配置：

```text
/exportconfig
```

---

## 🧩 可选工具

IP质量与 NodeQuality 均默认选择「仅 IPv4」。添加服务器（含批量导入）时检测一次 IPv6 并保存地址、可用状态、原因和检测时间；菜单、切换和开始按钮只读取已存状态，不重复 SSH 探测。已记录可用时可选「IPv4 + IPv6」，已记录不可用时隐藏双栈并显示原因。实际测试在同一次 SSH 执行中更新 IP 信息；确认 IPv6 后来被禁用或已无全局地址时，清除失效地址并在结果中明确提示“没有可用 IPv6，已更新服务器 IP 状态”。即使选 IPv4，实际测试也能更新后来恢复的 IPv6；SSH／探测命令失败、超时或无效响应不会误删已知地址。IP质量双栈保留两份独立报告，含无公开链接的 IPv6 Lite；超时保留已有结果并标记未完成。

GUKO 支持按需启用 IP 质量、NodeQuality、TCPQuality、流媒体、NextTrace、GB5、BGP 图、IPPure 图、Kat SS、Kat AnyTLS、Snell 等功能。流媒体入口逐次解析官方正式latest、冻结同发行binary/SUMS/完整源码的Service Unlock独立程序，经现有SSH传输并SHA256校验后只运行一次，默认实际出口自动选择global＋对应当地组，失败只跑global并说明原因。完整JSON与单框PNG来自同一次测量，不跑旧RRC/补充双图、不安装远端runtime；原生22项系统选族，新增项选族不冒标整个报告。完整exit1是含Unknown的有效报告，渲染/归档/发送失败不覆盖服务判据，旧双图历史保留。TCPQuality 按实际用途提供“三网质量 / 回程线路 / 国际互联 / 三网测速 / 完整检测”五个入口：三网质量和回程线路可按服务器配置选择 IPv4 或 IPv6；国际互联按上游能力使用 IPv4；三网测速和完整检测会先显示流量提示并要求确认，避免误触。完整检测运行三网 IPv4 / IPv6、国际互联和三网测速，不包含教育网检测。带报告的结果会上传至 `tcpquality.ibsgss.uk`，回程线路则直接返回文本结果。相关按钮可以通过环境变量关闭。

---

---

## 🧩 源码运行（开发用）

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

语法检查：

```bash
make check
```

---

## 🔐 隐私说明

- 仓库不包含任何 Bot Token、真实用户 ID、服务器密码或私钥。
- `.env`、`servers.json`、`keys/`、`media/`、`tmp/` 已加入 `.gitignore`，不要提交真实配置。
- 默认白名单模式，未配置允许用户时会拒绝启动。
- 使用 IPPure、bgp.tools、NodeQuality、TCPQuality、Service Unlock 流媒体检测等功能时，会访问对应第三方服务；流媒体通过固定匿名探针访问服务，自动选区最多查询两个固定HTTPS国家源，不提供账号凭据或执行旧上游脚本；TCPQuality 的报告模式会把检测结果上传至 `tcpquality.ibsgss.uk` 生成公开报告，纯回程识别不上传报告。
- 删除服务器只会删除 Bot 本地配置，不会删除或重装远端机器。

## License

原有部分MIT；统一流媒体接入修改AGPL-3.0-only，组合发行不是MIT-only。详见NOTICE-STREAM.md。

## 统一检测构建、来源与许可

- 默认不传`--region`，由检测程序在与extra相同族的direct/TLS路径识别出口国家；原生22项仍system-selected，不把整份报告冒标IPv4。无地区菜单/清单投票/额外信息报告。
- 自动读取目标机器uname，逐任务解析官方最新支持发行的对应架构CLI；以现有SSH认证同通道上传并SHA256核验，只执行一次完整`--machine`。不在远端装Go/Node/Python或下载执行脚本。超时/取消只清理该次独属PID/可执行文件/目录。
- 一次报告的JSON、ANSI、PNG独立存档；完整exit1/Unknown仍交付报告。渲染/存储/TG异常独立记录，必要时用同份报告完整分段文本，不改服务判据。新任务单图，历史旧两图仍能重发。
- 公开多架构构建：`docker buildx build --platform linux/amd64,linux/arm64 -f telegram-bot/Dockerfile .`。依赖版本沿v0.6.8（Python3.13、Node24、playwright1.59.1及原requirements），未升级字体/浏览器或改变网络/卷配置。`.github/workflows/docker-publish.yml`保留原精确mainCI门槛。
- CLI不再用镜像固定版本；每任务查`shui1iao/service-unlock`官方正式latest并冻结tag/commit/arch与同发行asset集合。binary/SHA256SUMS/完整source+vendor ZIP须都匹配发行digest；缓存按摘要复用且重新核hash，每任务仍查新，失败不退旧。实际版本与immutable source offer写入任务/history的`tool_source`；旧历史不重跑、不补新版本标签。
- 原GUKO MIT通知保留；统一接入修改为AGPL-3.0-only，组合image**不是MIT-only**。见`NOTICE-STREAM.md`、`LICENSES/AGPL-3.0.txt`。提供远程交互的部署须保留准确修改版本的对应源码提供义务。
- `python scripts/build-source.py`从准确tracked通用源码生成`dist/guko-v0.7.2-source.zip`和SHA256SUMS，含真实集成/构建/许可/测试源码，不含运行数据或递归生成归档。动态CLI完整对应源按本次真实发行单独提供，不复用旧嵌入ZIP。
- 离线回归：python -m unittest discover -s tests -v（使用镜像依赖；先构建tests/native_fixture.go到tests/native-fixture）。fixture为明确CLI版本的离线HTTPmock输出，不代表真实节点解锁。

## 本地最新工具策略（2026-11-05）

- Service Unlock：22原生+134extra，12重复探针真删；按CLI0.5.8严格核六用途加Regional媒体原名/Selected顺序、每主探针单状态及本探针真实地区/颜色/换行。未知目录/呈现变化拒绝，不跳过ANSI/raw一致性；extra134及安全守卫不改。
- TCP：每任务官方正式latest解析到commit，同commit下载wrapper/core并设RAW_BASE；保--no-rootfs/现有模式。上游无签名/hash时只称官方HTTPS固定commit+内容身份，不冒称独立签名真实性。
- NextTrace：每任务官方正式latest，按支持架构选发行资产，任务临时程序+PTY；不复用PATH旧版，不写/usr/local/bin。
- IPQ/NQ：每次读取当前官方入口并确认其真实仓库/commit同内容，随后只执行该commit/hash。真实来源是xykt/IPQuality及LloydAsp/NodeQuality；NQ内部BenchOS/NextTrace/GB5等跟上游，不修改。
- GB5：仅官方legacy页面明确列出的5系列Linux包；页面403/无可确认链接则明确停止，不复用5.5.1、不迁6、不扫描猜测CDN版本。原GB5名称、评分/CSV/临时低内存swap产品保持。
- Kat SS/AnyTLS：每协议一个入口，读取全部受支持Kat实例；只读完整确认所选协议未安装后另给限时、用户/chat/服务器/协议绑定的一次性安装确认。旧ensure/install按钮不构成确认。新装才冻结Kat-Manager官方main三组件及pins，已有共享内核只复用，无内核才冻结Kat-Server正式latest资产/hash。缺root/Linux amd64/systemd/Python3/下载工具即停止，不自动装依赖或升级已有内核。Snell维持原独立Manager渠道与行为。VLESS新任务/底层能力删除，旧回调明确失效，历史与远端既有VLESS原样保。
- BGP/IPPure/renderer及系统依赖随GUKO维护，不热替换、不自动升级节点。无后台更新器。
- 当前官方元数据/内容不可得、坏hash、缺必要资产/CLI对应源码或不兼容都停止。历史重发只用原报告/图片及原来源证据；没有证据的旧历史不伪造最新版。
- 正式完整对应源为同一Release的guko-v0.7.2-source.zip及SHA256SUMS；不以旧公共tag或local归档冒充。许可见NOTICE-STREAM.md。
- 公共镜像使用telegram-bot/Dockerfile独立构建，私有Dockerfile.local仅保历史运营配方；公开发布不自动部署任何实例。
- 离线fixture使用明确标注的CLI/HTTPmock来源，不代表真实服务器解锁结论；发行验证运行范围与结果见发布交付，不以构建冒充业务验收。

## Kat代理契约（本地修改，2026-11-05）

SS/AnyTLS读取仅用目标已有POSIX shell、systemctl/proc/coreutils作有界快照，GUKO侧解析；不运行远端Kat/Manager view/status/check，不需要远端Python，不访问节点API，不写配置或启停服务。标准和kat-*实例加实际Kat进程锚定的自定义unit可识别，多JSON/多inbound逐项保留；有限发现不完整、未知wrapper/drop-in/相对路径/替换exe、残缺或旧后端冲突一律停止，不当作未安装。完全任意名字且停止、无运行进程锚定的自定义unit，不能据本功能宣称全机不存在；若留下相关Kat配置痕迹则拒绝安装。

SS2022读取ss.key、2017读取ss.password；SS/AnyTLS每inbound单身份，非空users拒绝。AnyTLS省略tls用已知随机内存证书语义；明确匹配legacy-insecure的单cert/key仅核文件元信息、不读私钥。其它显式TLS/ACME或绑定可达性不明时标unsupported，不编SNI/指纹、不降级为insecure、不宣称完整成功。客户端输出保精确secret及IPv6/Surge转义；AnyTLS URI编码/，Mihomo带udp:true；多节点消息完整分页，不用旧三段/3600字符截断。

输出仅称“Kat实例配置文件中的节点信息，未验证连接/当前生效凭据”；磁盘文件不冒充已reload的内存配置。inactive/failed仍是已安装，不自动启动。Kat有效且旧SSRust/AnyTLSGo inactive/disabled遗留时只读Kat；旧backend活跃、仅旧痕迹或归属不明则拒绝，不回退旧配置。

确认安装后再次完整发现，下载前还核身份/hash；只创建缺失的标准协议。Manager普通install自检及daemon-reload/enable--now仅发生于未来用户明确确认的新安装任务，非已有节点读取。安装输出不回传凭据日志；结束后重新只读采集真实unit/config/内核身份，不能仅靠成功文字报成功；失败不自动重试、升级或接管自定义第二实例。

v0.7.2发布经过离线回归与隔离构建验证；不运行真实流媒体扫描/测速跑分/代理安装或TG测试。公开发布不自动切换运营实例。

## v0.7.2 正式对应源

完整源和SHA256SUMS：https://github.com/shui1iao/GUKO/releases/tag/v0.7.2 。公共镜像为ghcr.io/shui1iao/guko:v0.7.2（amd64/arm64）；org.opencontainers.image.revision标准确提交。源附件guko-v0.7.2-source.zip为本镜像对应源，非旧tag或私有local归档。动态工具的同次发行完整源仍单独随tool_source提供。MIT/AGPL及第三方义务见NOTICE-STREAM.md。
