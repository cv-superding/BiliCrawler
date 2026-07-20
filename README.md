# BiliCrawler · B站弹幕与评论数据爬取工具

> 模块化分层架构的 B 站（Bilibili）弹幕 / 评论采集工具：弹幕与评论采集、UP 主 / 收藏夹 / 合集 / 频道批量采集、断点续爬、反爬策略，并内置一套莫奈印象派柔和色调的 Web 控制面板。

---

## 一、功能特性

| 模块 | 说明 |
| --- | --- |
| 📜 弹幕采集器 | 解析 B站弹幕 protobuf 接口（`x/v2/dm/web/seg.so`），按 BV 号 / URL / av 号获取**全部弹幕**；输出文本、发送时间、用户哈希、类型、颜色、字号、视频内位置等；多 P 视频自动遍历。 |
| 💬 评论采集器 | 逐页爬取评论区，采集内容、用户信息（昵称 / UID / 头像 / 等级 / 大会员）、点赞、发布时间、**父 / 根评论 ID（还原回复树）**，支持按时间 / 热度排序，并递归获取二级评论。 |
| 📚 批量引擎 | （B站）支持 UP 主空间、收藏夹、合集、频道四类来源；（抖音）支持用户主页遍历；均内置并发采集、任务队列、**断点续爬**（记录已采集视频 ID，中断后从断点继续）。 |
| 🌐 多平台 | 架构平台无关，**B站**（弹幕 + 评论）与**抖音**（评论 + 批量）均已内置；新增平台只需扩展 `crawlers/` 与 `utils/`。 |
| 📤 导出器 | 统一 snake_case 字段；JSON 带 UTF-8 BOM，CSV 用 `utf-8-sig`（Excel 中文不乱码）。 |
| 🛡️ 反爬策略 | 自适应限速、随机 UA 池轮换、Cookie 会话管理、HTTP 412/429/5xx 指数退避重试（最多 3 次）。 |
| ⚙️ 配置管理 | 单一 YAML 文件管理延迟、重试、Cookie、导出路径等。 |
| 🎨 Web 面板 | Flask + 原生前端，4 个页面：视频采集 / 批量采集 / 任务队列（暂停·恢复·取消）/ 数据导出。 |

---

## 二、目录结构

```
Bili-Crawl danmaku&comments/
├── bili_crawler/                 # 主包
│   ├── __main__.py               # 命令行入口（python -m bili_crawler）
│   ├── config/settings.py        # YAML 配置加载
│   ├── utils/                    # 工具层
│   │   ├── http.py               # HTTP 客户端（重试/退避/限速/UA）
│   │   ├── anti_crawl.py         # 限速器 / UA 池 / 重试策略
│   │   ├── wbi.py                # WBI 签名（评论接口必备）
│   │   ├── protobuf.py           # 弹幕 protobuf/XML 解析（零依赖）
│   │   ├── parse.py              # BV/av/mid/收藏夹 等输入解析
│   │   ├── exceptions.py         # 自定义异常
│   │   └── logger.py
│   ├── models/                   # 数据模型层（snake_case）
│   │   ├── danmaku.py  comment.py  task.py
│   ├── crawlers/                 # 采集器层
│   │   ├── base.py               # 基类 + 回调钩子（解耦运行环境）
│   │   ├── danmaku.py  comment.py  batch.py
│   ├── exporters/                # 数据导出层
│   │   ├── base.py  json_exporter.py  csv_exporter.py
│   └── web/                      # Web 控制面板
│       ├── app.py                # Flask 应用 + REST API
│       ├── task_manager.py       # 任务调度 / 暂停 / 续爬 / 导出
│       ├── templates/*.html      # 4 个页面
│       └── static/{css,js}       # 莫奈色调样式与交互
├── data/                         # 运行时数据（已 gitignore）
│   ├── exports/                  # 导出文件
│   ├── results/                  # 任务原始 JSON
│   └── state/                    # 断点续爬状态
├── tests/smoke.py                # 离线冒烟测试
├── config.example.yaml           # 配置样例
├── config.yaml                   # 本地配置（由 config.example.yaml 复制而来，已 gitignore）
├── requirements.txt
├── pyproject.toml
└── README.md
```

**四层架构**（便于扩展到抖音 / YouTube 等平台）：

```
┌─────────────┐   ┌─────────────┐   ┌─────────────┐   ┌─────────────┐
│  crawlers   │──▶│   models    │◀──│  exporters  │   │     web     │
│  采集器层   │   │  模型层     │   │  导出层     │   │  控制面板   │
└──────┬──────┘   └─────────────┘   └─────────────┘   └──────┬──────┘
       │                                                     │
       └──────────────────────┬──────────────────────────────┘
                              ▼
                     ┌─────────────────┐
                     │     utils       │  HTTP / 反爬 / protobuf / 解析 / 配置
                     └─────────────────┘
```

---

## 三、安装说明

要求 **Python ≥ 3.9**。

```bash
# 1. 克隆仓库
git clone https://github.com/cv-superding/BiliCrawler.git
cd BiliCrawler

# 2. 安装依赖（推荐虚拟环境）
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt

# 3. 复制配置模板（config.yaml 已被 gitignore，不会泄露你的 Cookie）
cp config.example.yaml config.yaml     # Windows: copy config.example.yaml config.yaml

# 4.（可选）以可编辑模式安装，获得 bili-crawler 命令
pip install -e .
```

### 5. 使用 Docker 部署（免装 Python 环境，适合长驻 / 服务器）

项目已提供 `Dockerfile` 与 `docker-compose.yml`，并支持用环境变量覆盖 Web 监听地址，**无需在宿主机装 Python**。

1. 准备配置（含你的 Cookie）：
   - 本地已有 `config.yaml`：直接挂载即可；
   - 全新克隆：先 `cp config.example.yaml config.yaml`，填入 Cookie。
2. 启动（推荐 Compose）：
   ```bash
   docker compose up -d --build
   ```
   或纯 Docker 命令：
   ```bash
   docker build -t bili-crawler .
   docker run -d --name bili-crawler -p 5000:5000 \
     -e BILI_WEB_HOST=0.0.0.0 \
     -v "$PWD/config.yaml:/app/config.yaml:ro" \
     -v "$PWD/data:/app/data" \
     bili-crawler
   ```
3. 浏览器打开 `http://<服务器IP>:5000` 即可使用四个页面。

> ⚠️ **安全**：镜像构建时通过 `.dockerignore` 已排除 `config.yaml`、两个 Cookie 文件与 `.workbuddy/`，**不会把你的凭据烤进镜像**。请务必用 `-v` 挂载本地真实的 `config.yaml`（含 Cookie）与 `data/`，不要把凭据写进镜像或提交仓库。
> **监听地址**：容器内默认沿用配置里的 `web.host`；可用 `BILI_WEB_HOST` / `BILI_WEB_PORT` 环境变量覆盖（如 `BILI_WEB_HOST=0.0.0.0` 让容器外也能访问）。

> 依赖仅 `requests` / `pyyaml` / `flask` / `werkzeug`，均为成熟轻量库。

---

## 四、快速开始

### 方式 A：Web 控制面板（推荐）

```bash
# 使用项目自带默认值直接启动（config.yaml 已存在）
python -m bili_crawler web
# 或： python -m bili_crawler        （不传子命令默认启动 Web）
```

启动后浏览器打开 **http://127.0.0.1:5000** 即可使用四个页面。

> 提升采集上限：编辑 `config.yaml`，将浏览器登录后的 Cookie 填入 `cookie.session`（见第五节）。

### 方式 B：命令行单次采集

```bash
# 采集弹幕并导出 CSV
python -m bili_crawler crawl "BV1xx411c7mD" --danmaku --format csv --output data/exports/my_danmaku

# 采集评论（按热度），导出 JSON
python -m bili_crawler crawl "https://www.bilibili.com/video/BV1xx411c7mD" --comment --sort hot
```

---

## 五、使用指南

### 1. 视频数据采集页（`/video`）
输入 **BV 号 / 完整视频 URL / av 号**，勾选「弹幕」「评论」（可多选），点击「开始采集」即创建任务并跳转队列页。

> 🔑 **Cookie 自检**：视频页与批量页均提供「检查 Cookie 登录态」按钮，点击后调用 B站 `nav` 接口，直观显示当前 Cookie 是否有效、登录账号名。无需发起完整采集即可确认 Cookie 是否正确（避免「填了却不知道对不对」）。
> 也可直接访问 `GET /api/health/cookie` 获取 JSON 结果 `{ ok, logged_in, uname, cookie_len }`。

### 2. 批量采集页（`/batch`）
- **来源链接 / ID**：UP 主空间、收藏夹、合集或频道链接（或纯数字 UP mid）。
- **来源类型**：`自动识别` / `UP 主空间` / `收藏夹` / `合集` / `频道`。
- **并发数**：1–8，越大越快但越易触发风控。
- **断点续爬**：已完成的视频 ID 记录在 `data/state/`，中断后重提相同来源会自动跳过。

### 3. 任务队列页（`/tasks`）
实时展示每个任务的进度条、状态徽章（排队中 / 采集中 / 已暂停 / 已完成 / 失败 / 已取消）、最新日志，并支持：
- **暂停 / 恢复**：暂停后采集线程在检查点阻塞，恢复后继续。
- **取消**：发送取消信号，线程在最近检查点安全退出。

页面默认每 1.5 秒自动刷新，可手动暂停自动刷新。

### 4. 数据导出页（`/export`）
列出所有「已完成」任务，选择 **JSON / CSV** 格式（批量任务还需选择导出「弹幕」或「评论」），点击「下载」即得文件。两种格式均带 UTF-8 BOM，Excel 直接打开中文不乱码。

### 5. Cookie 文件一键导入（推荐，避免手动拼错）

手动复制整段 `Cookie` 请求头容易漏字段或引报错。推荐用浏览器插件（如 **Cookie-Editor**）把网站的 Cookie 导出为 **JSON 数组**，再交给转换脚本：

| 平台 | 导出文件名 | 转换脚本 | 写入字段 |
| --- | --- | --- | --- |
| B站 | `B站cookie.txt`（JSON 数组） | `python convert_bili_cookie.py` | `cookie.session` |
| 抖音 | `抖音cookie.txt`（JSON 数组） | `python convert_cookie.py` | `cookie.douyin` |

- B站转换脚本**保留** `SESSDATA` 里的 `%2C/%3D` 等原始编码（解码会导致鉴权失败）；抖音脚本会做 URL 解码。
- 这两个 `.txt` 文件含你的真实账号凭据，已被写入 `.gitignore`，**请勿提交到仓库**。仓库里只保留 `B站cookie.example.txt` / `抖音cookie.example.txt` 占位模板。

> 若不想用脚本，也可直接在 `config.yaml` 的 `cookie.session` / `cookie.douyin` 粘贴 `name=value; ...` 字符串（见第六节说明）。

---

## 六、配置参数说明（`config.yaml`）

| 配置段 | 字段 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `http` | `delay_min` / `delay_max` | `0.5` / `1.5` | 请求间随机休眠区间（秒），自适应限速在此区间波动 |
| | `timeout` | `15` | 单次请求超时（秒） |
| | `max_retries` | `3` | 触发 412/429/5xx 时的最大重试次数（指数退避） |
| | `backoff_base` | `1.0` | 退避基数，第 n 次重试约休眠 `base * 2^n` 秒 |
| | `concurrency` | `3` | 批量采集并发数 |
| | `proxy` | `""` | 代理地址（如 `http://127.0.0.1:7890`），留空不开启 |
| `user_agent` | `rotate` | `true` | 是否启用随机 UA 轮换 |
| | `pool` | `[]` | 自定义 UA 池（留空用内置默认池） |
| `cookie` | `session` | `""` | 登录 Cookie（提升上限、降低风控） |
| | `expire_days` | `30` | Cookie 有效天数（提示刷新用） |
| `export` | `output_dir` / `raw_dir` / `state_dir` | `data/exports` 等 | 导出 / 原始数据 / 断点状态目录 |
| `web` | `host` / `port` / `debug` | `127.0.0.1` / `5000` / `false` | Web 服务绑定参数 |

> **获取 Cookie**：浏览器登录 B站 → F12 → Network → 任意请求 → Request Headers → 复制 `Cookie` 整段粘贴到 `cookie.session`。

---

## 七、REST API 接口文档

基础前缀：无（直接相对于站点根）。所有请求 / 响应均为 `application/json`（导出下载除外）。

### 采集提交
| 方法 | 路径 | 说明 | 请求体 |
| --- | --- | --- | --- |
| `POST` | `/api/crawl/video` | 提交视频采集 | `{ "input": "BVxxx", "types": ["danmaku","comment"] }` |
| `POST` | `/api/crawl/batch` | 提交批量采集 | `{ "source": "...", "source_type": "auto|space|favorites|collection|channel", "kinds": ["danmaku","comment"], "concurrency": 3 }` |

### 任务查询与控制
| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/tasks` | 任务列表（含状态 / 进度 / 最近日志） |
| `GET` | `/api/tasks/<task_id>` | 单个任务详情 |
| `POST` | `/api/tasks/<task_id>/pause` | 暂停 |
| `POST` | `/api/tasks/<task_id>/resume` | 恢复 |
| `POST` | `/api/tasks/<task_id>/cancel` | 取消 |

### 导出
| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/export/options` | 可导出（已完成）任务列表 |
| `GET` | `/api/export/<task_id>?format=json\|csv&sub=danmaku\|comment` | 触发文件下载（批量任务需 `sub`） |

### 健康检查
| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/health/cookie` | 校验 Cookie 登录态（调用 `nav` 接口），返回 `{ ok, logged_in, uname, cookie_len }`；任何异常也以 JSON 返回，不会返回 HTML 错误页 |

**任务状态机**：`pending → running ↔ paused → running → completed / failed / cancelled`

---

## 八、反爬策略说明

1. **自适应限速**：每次请求前在 `[delay_min, delay_max]` 随机休眠；触发限流时自动放宽区间，平稳时缓慢回落。
2. **随机 UA 池**：默认内置多款主流浏览器 UA，可配置 `user_agent.pool` 自定义。
3. **Cookie 会话**：登录 Cookie 由 `config.yaml` 注入请求头，提升采集上限、降低风控概率。
4. **指数退避重试**：遇到 `412`（风控）/ `429`（限流）/ `5xx`，按 `backoff_base * 2^n` 退避重试，最多 `max_retries` 次后抛出 `RateLimitError` / `APIError`。
5. **WBI 签名**：评论接口（`x/v2/reply/wbi/main`）需 WBI 签名，`utils/wbi.py` 自动获取密钥并签名，无需手动干预。
6. **异常覆盖**：网络超时、API 限流、JSON / protobuf / XML 解析失败等均有对应异常与日志，不会静默崩溃。

---

## 九、数据字段说明（统一 snake_case）

**弹幕 `Danmaku`**：`id` `id_str` `content` `send_time` `send_time_iso` `uid_hash` `mode` `mode_name` `color` `color_hex` `fontsize` `progress_ms` `progress_sec` `pool` `weight` `action` `bvid` `cid` `page`

> ⚠️ 弹幕接口出于隐私只返回 `uid_hash`（用户 ID 哈希），**不含明文 UID**；明文 UID 请通过评论接口获取。

**评论 `Comment`**：`rpid` `oid` `bvid` `user_id` `username` `avatar` `level` `content` `ctime` `ctime_iso` `like` `parent` `root` `sex` `vip` `ip_location` `sub_reply_count` `page`
- `parent == 0` 且 `root == 自身 rpid` → 一级评论；
- 二级回复 `parent` 指向直接父评论，`root` 指向根评论，据此可重建回复树。

---

## 十、抖音平台支持（已内置）

架构按平台无关设计，抖音平台已完整接入（采集器 + 签名 + 解析 + Web 面板 + 命令行）。

### 10.1 支持的采集类型

| 类型 | 说明 | 状态 |
| --- | --- | --- |
| 抖音评论 | 单视频评论 + 二级回复（还原回复树） | ✅ 支持 |
| 抖音批量 | 按用户主页（sec_user_id）遍历全部视频采集评论 | ✅ 支持 |
| 抖音弹幕 | 抖音视频**没有「弹幕」概念**（直播才有弹幕） | ❌ 不支持 |

> 因此抖音平台在 Web 面板中仅开放「评论」类型，选择抖音后会自动禁用「弹幕」。

### 10.2 涉及的接口与签名

- 一级评论：`GET /aweme/v1/web/comment/list/`（游标分页）
- 二级回复：`GET /aweme/v1/web/comment/list/reply/`
- 用户视频列表：`GET /aweme/v1/web/aweme/post/`
- **签名（核心）**：抖音 Web 接口必须在查询参数中携带签名，否则返回空数据 / 风控。
  - 本工具内置 **X-Bogus** 纯 Python 实现（移植自 Evil0ctal/Douyin_TikTok_Download_API，Apache-2.0，**零依赖、离线可用**）。
  - 部分新接口优先校验 **a_bogus**（bdms SDK 生成）。若 X-Bogus 被拒，可在 `config.yaml` 启用
    `douyin.with_a_bogus: true` 并自备 Node.js 签名脚本 `js/douyin_sign_worker.js`（脚手架已提供，
    填入真实 a_bogus 生成逻辑即可）。
- ⚠️ 签名所用的 User-Agent 必须与请求发送时的 UA **完全一致**，工具已内部统一处理。

### 10.3 Cookie 配置（重要）

抖音与 B站账号体系**完全独立**，B站 Cookie 对抖音无效。请在 `config.yaml` 单独填写：

```yaml
cookie:
  session: "B站 Cookie（不变）"
  douyin: "sessionid=xxx; ttwid=xxx; msToken=xxx"   # 抖音 Cookie（可选，提升稳定性）
```

获取方式：浏览器登录 `douyin.com` → F12 → Network → 任意请求 → Request Headers → Cookie，
整段复制。留空时仍可尝试游客模式（部分视频受限）。

### 10.4 使用方式

**Web 面板**：视频页 / 批量页顶部新增「平台」下拉，选择「抖音」后输入视频链接（或 aweme_id）/
用户主页链接即可，其余流程与 B站一致。

**命令行**：

```bash
# 抖音单视频评论，导出 JSON
python -m bili_crawler crawl "https://www.douyin.com/video/734xxxx" --comment --platform douyin --format json

# 抖音用户主页全部视频评论，导出 CSV
python -m bili_crawler crawl "https://www.douyin.com/user/MS4wLjABAAAAxxx" --comment --platform douyin --format csv
```

### 10.5 抖音评论字段（导出 snake_case）

`comment_id`(cid) / `aweme_id` / `user_id` / `username` / `avatar` / `content` / `create_time`
(+ISO) / `digg_count` / `reply_comment_total` / `parent_id` / `root_id` / `ip_label` /
`user_level` / `is_author` / `vip` / `page`。

### 10.6 扩展到 YouTube 等其它平台

架构已与平台解耦，新增平台只需：
- 在 `crawlers/` 下新建采集器继承 `BaseCrawler`（复用 `models/` 与 `exporters/`）；
- 在 `utils/` 下补充对应签名 / 解析（如 YouTube 的 `innertube`）；
- `web/task_manager.py` 的 `submit_*` 与 `app.py` 路由已预留 `platform` 维度，增加入口即可。



---

## 十一、合规与注意事项

- 本工具仅供**学习、研究与个人数据分析**使用，请遵守 B站《用户协议》与相关法规。
- 控制请求频率，勿高频批量请求或绕过平台限制；商业用途请使用官方开放平台 / 授权接口。
- `config.yaml` 含 Cookie 等敏感信息，已加入 `.gitignore`，**请勿提交到仓库**。
- 弹幕 protobuf 解析为手写零依赖实现；若 B站调整接口，仅需更新 `utils/protobuf.py` 与对应采集器。

---

## 十二、界面预览（截图）

> 实际界面为莫奈印象派柔和色调（低饱和度紫灰 / 雾蓝 / 暖米色，圆角卡片 + 柔和阴影）。
> 启动后访问 `http://127.0.0.1:5000` 即可查看；建议截图替换本节的占位说明：

- **视频采集页**：顶部输入区（BV/URL）、采集类型 chip 选择、字段说明卡片。
- **批量采集页**：来源链接输入、来源类型下拉、并发数配置、断点续爬说明。
- **任务队列页**：实时进度条 + 状态徽章 + 暂停/恢复/取消按钮 + 滚动日志。
- **数据导出页**：已完成任务列表 + 格式（JSON/CSV）+ 批量子类型选择 + 下载。

运行 `python -m bili_crawler web` 后在浏览器中按 `F12 → 设备工具栏` 或系统截图工具截取各页面即可补全此处图片。

---

## 十三、测试

```bash
# 离线冒烟测试（无需联网）：验证 protobuf 解析 / URL 解析 / 模型 / 导出 BOM
python tests/smoke.py

# 抖音模块离线测试：X-Bogus 签名 / 输入解析 / 模型 / 采集器解析逻辑
python tests/douyin_smoke.py
```

---

## 十四、常见问题 / 故障排查

### Q1. 评论采集返回 `code=-403 访问权限不足`，怎么办？
这通常是**账号被 B站限流**，而非 Cookie 失效或代码错误。判定方法：
- 在视频页 / 批量页点击「检查 Cookie 登录态」→ 若显示「✓ Cookie 有效，当前登录账号：xxx」，说明登录态正常，问题在限流；
- 短时间大量请求（含调试、反复重试）极易触发评论接口（`x/v2/reply/wbi/main`）的风控冷却。

**两种限流，应对不同：**
1. **轻量级限流（最常见）**：暂停 **10~30 分钟**不要重复请求，冷却通常会自动解除；期间可在 `config.yaml` 调大 `http.delay_min/delay_max`、把批量 `concurrency` 降到 1，采集会更平稳。
2. **账号级限流（较难搞）**：B站 会把评论接口的 `-403` 绑定到**账号 UID**，而非单次会话。此时即便你重新导出 Cookie（**同一账号**）也**依然 -403**——我们实测遇到过同一账号连续多日被卡的情况。这种情况只能：① 彻底停用该账号数小时~数天再试；或 ② **换一个 B站账号**的 Cookie（重新运行 `convert_bili_cookie.py` 导入）。

> 工具已对 `-403/-412/-509` 等业务级风控码做了识别：会抛出 `ThrottleError` 并自动分级冷却（每次翻倍、上限 10 分钟，单任务最多约 34 分钟），任务日志也会明确提示「账号被临时限流」，而非只甩一句原始错误。但**账号级封禁代码无法自动解除**，需人工换号或长等。
> 相比之下，弹幕接口（`x/v2/dm/web/seg.so`）对账号级 -403 不敏感，通常仍可正常采集。

### Q2. 评论采集返回 `code=-101 账号未登录`？
Cookie 未生效。请确认：
1. `config.yaml` 的 `cookie.session` 填入的是**完整 Cookie 字符串**（含 `SESSDATA=...; bili_jct=...`）；
2. 修改配置后**重启了 Web 面板**（`python -m bili_crawler web`）——配置仅在启动时加载；
3. Cookie 未过期（登录态失效需重新从浏览器复制）。

### Q3. 弹幕采集到 0 条？
可能原因：
- **该视频本身弹幕很少 / 已关闭弹幕**：B站弹幕接口只返回常规弹幕（`seg.so` protobuf 的 field 1），若该视频仅含命令弹幕或弹幕被关，则为 0 条（属正常）。建议换一个弹幕活跃的视频验证（工具已实测单视频可稳定抓取 1700+ 条弹幕）。
- **多 P / 长视频仅抓到部分**：弹幕按约 360 秒/段分段。工具已按视频时长 `ceil(时长/360)` 推算段数并逐段抓取；若仍异常，查看任务日志中「分段接口无数据」提示，多为网络 / 登录态导致。

### Q4. 下载导出文件变成 `.htm`？
旧版曾因导出路径依赖当前工作目录导致 `send_file` 找不到文件、返回 HTML 错误页被浏览器存成 `.htm`。当前版本已修复：导出路径在加载时锚定为**项目根目录绝对路径**，且任何异常都以 JSON 返回。若仍异常，导出接口会返回 JSON 错误提示而非 HTML。

### Q5. 抖音采集返回「响应不是合法 JSON / 签名失效 / 需登录」？
抖音 Web 接口强依赖签名（X-Bogus / a_bogus），常见原因：
1. **未填抖音 Cookie**：抖音与 B站账号独立，请在 `config.yaml` 的 `cookie.douyin` 单独填写（`sessionid` / `ttwid` / `msToken` 等），否则部分视频会被拒。
2. **X-Bogus 被服务端拒绝**：当前抖音正逐步迁移到 `a_bogus`。若 X-Bogus 持续失效，可在 `config.yaml` 设 `douyin.with_a_bogus: true`，并在 `js/douyin_sign_worker.js` 中接入真实 `a_bogus` 生成逻辑（参考 bdms SDK），工具会自动追加该签名。
3. **请求过于频繁触发风控**：降低并发、调大 `http.delay_*` 后重试。
4. 抖音签名是动态反爬机制，可能随版本变化；本工具签名模块已隔离在 `utils/douyin_sign.py`，便于单独更新而无需改动采集逻辑。

---

## 十五、项目状态与已知问题

- **弹幕接口**：稳定，单视频实测可抓取 1700+ 条；对账号级限流不敏感。
- **评论接口**：功能完整（含二级回复树、WBI 签名），但**对账号级 -403 风控极敏感**（见 Q1）。若你的账号被限流，弹幕仍可正常跑，评论需换号或长等。
- **抖音平台**：评论采集依赖签名。默认内置 **X-Bogus**（纯 Python，离线可用）；若服务端要求更强的 **a_bogus**，需自备 `js/douyin_sign_worker.js`（参考 bdms SDK）。抖音无「弹幕」概念（仅直播弹幕），故不提供抖音弹幕采集。
- **配置与 Cookie**：`config.yaml` 与 `B站cookie.txt` / `抖音cookie.txt` 均已 gitignore，请放心拉取仓库、自行填入，**切勿把含凭据的文件提交回仓库**。

欢迎提 Issue / PR。建议先阅读 `tests/` 下的离线冒烟测试，了解数据模型与解析逻辑。

---

## 许可证

Apache-2.0 © BiliCrawler Contributors

> 采用 Apache License 2.0：可自由使用、修改、分发（含商用），但需保留版权与许可证声明，并在修改文件中注明变更。详见仓库根目录 `LICENSE`。
