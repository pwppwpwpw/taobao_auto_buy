# 淘宝定时自动抢购

这个仓库已经重构成了一个可以直接运行的 Python 项目，不再是单个脚本堆在一起。

当前项目支持：

- 定时等待到指定时间后自动抢购
- Selenium 驱动 Chrome 登录淘宝并保持登录状态
- 可选人工勾选商品，或者自动全选购物车商品
- 可选无头模式运行，适合后台常驻
- 生成 macOS `launchd` 的 `.plist`，方便挂成后台服务
- 控制台日志 + 文件日志 + 失败截图

## 目录结构

```text
.
├── README.md
├── config.example.toml
├── requirements.txt
├── taobao.py
└── taobao_autobuy
    ├── __init__.py
    ├── __main__.py
    ├── app.py
    ├── browser.py
    ├── cli.py
    ├── config.py
    └── logger.py
```

## 工作原理

项目分成 4 层：

1. `config.py`
   负责读取 `TOML` 配置，统一管理时间、浏览器、购物车和输出参数。
2. `browser.py`
   负责创建 Selenium Chrome Driver，并支持持久化 Chrome 用户目录。
3. `app.py`
   负责业务流程：登录、保活、等待抢购时间、点击结算、提交订单。
4. `cli.py`
   提供命令行入口，比如运行、准备登录态、生成后台服务配置。

## 安装

建议使用 Python 3.11+。

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

你本机还需要：

- 已安装 Google Chrome
- Selenium 可用的 ChromeDriver
  - Selenium 4 通常会自动管理驱动
  - 如果你本机环境特殊，也可以在配置里手动填 `driver_path`

## 快速开始

### 1. 准备配置

先复制一份配置：

```bash
cp config.example.toml config.toml
```

重点改这几个字段：

- `[run].buy_time`
- `[browser].headless`
- `[cart].selection_mode`

推荐两种模式：

### 模式 A：有人看着页面，最稳

```toml
[browser]
headless = false

[cart]
selection_mode = "manual"
```

这种模式和你原来的脚本一致：

- 程序先登录淘宝
- 自动保活到抢购前
- 在抢购前停止刷新
- 你手动勾选商品
- 到点后脚本自动点结算和提交订单

运行：

```bash
python3 taobao.py run --config config.toml
```

### 模式 B：后台常驻，尽量不打开浏览器窗口

```toml
[browser]
headless = true

[cart]
selection_mode = "select_all"

[output]
leave_browser_open = false
```

这个模式依赖“持久化登录态”，第一次要先准备 Chrome 用户目录。

先执行：

```bash
python3 taobao.py prepare-profile --config config.toml
```

这个命令会打开一个 Chrome 窗口，你在里面扫码登录淘宝。登录成功后，回到终端按回车退出，登录态会保存在：

- `runtime/chrome-profile`

之后就可以无头运行：

```bash
python3 taobao.py run --config config.toml
```

## 后台常驻运行

### 方案 1：直接 `nohup`

```bash
nohup python3 taobao.py run --config /绝对路径/config.toml > /绝对路径/runtime/nohup.out 2>&1 &
```

### 方案 2：macOS `launchd`

生成一个 `plist`：

```bash
python3 taobao.py render-launchd \
  --config config.toml \
  --output runtime/com.taobao.autobuy.plist \
  --label com.taobao.autobuy
```

然后把生成的文件拷到 `~/Library/LaunchAgents/`，再执行：

```bash
launchctl unload ~/Library/LaunchAgents/com.taobao.autobuy.plist 2>/dev/null || true
cp runtime/com.taobao.autobuy.plist ~/Library/LaunchAgents/com.taobao.autobuy.plist
launchctl load ~/Library/LaunchAgents/com.taobao.autobuy.plist
```

它会在加载后启动脚本，脚本自己会等待到 `buy_time` 再执行。

## 命令说明

### `run`

正式运行抢购流程。

```bash
python3 taobao.py run --config config.toml
```

可选覆盖配置：

```bash
python3 taobao.py run --config config.toml --headless
python3 taobao.py run --config config.toml --show-browser
```

### `prepare-profile`

用来第一次手动登录，保存淘宝登录态，给后续无头模式使用。

```bash
python3 taobao.py prepare-profile --config config.toml
```

### `render-launchd`

生成 macOS 后台运行用的 `plist`。

```bash
python3 taobao.py render-launchd --config config.toml --output runtime/com.taobao.autobuy.plist
```

## 配置说明

### `[run]`

- `buy_time`: 抢购时间，格式 `YYYY-MM-DD HH:MM:SS`
- `timezone`: 时区，默认 `Asia/Shanghai`
- `stop_refresh_before_seconds`: 人工模式下，提前多久停止刷新
- `keep_alive_interval`: 保活刷新间隔
- `max_submit_retry_times`: 下单失败后的最大重试次数

### `[browser]`

- `headless`: 是否无头运行
- `detach`: 是否让浏览器进程独立存在
- `window_size`: 浏览器窗口大小
- `user_data_dir`: Chrome 用户目录，保存登录态的关键
- `profile_directory`: Chrome Profile 名称，默认 `Default`

### `[cart]`

- `selection_mode = "manual"`
  - 适合你盯着页面看
  - 抢购前脚本会停下来，让你自己勾选商品
- `selection_mode = "select_all"`
  - 适合无头后台跑
  - 脚本会自动勾选购物车里的全部商品
  - 建议抢购前把购物车里只保留目标商品

### `[output]`

- `log_file`: 日志文件路径
- `screenshot_dir`: 失败截图目录
- `leave_browser_open`: 脚本退出后是否保留浏览器

## 已知限制

这个项目已经尽量支持“后台跑”，但需要明确几个现实限制：

1. 淘宝登录风控、验证码、扫码校验，可能要求你人工处理。
2. 完全无头运行时，页面结构变化、风控页、支付确认页都可能让自动流程中断。
3. 无头模式最稳的做法不是“完全不打开浏览器”，而是：
   - 先用 `prepare-profile` 保存一次登录态
   - 抢购时再复用该 Profile 无头运行
4. 如果你需要精确选择某一个商品而不是全选，当前版本最稳的是人工模式；后台模式建议购物车里只留目标商品。

## 日志和排错

日志默认写入：

- `runtime/logs/taobao_autobuy.log`

失败截图默认写入：

- `runtime/screenshots/`

如果运行失败，优先看日志和截图。

## 典型使用建议

如果你是第一次跑：

1. 先用有界面模式跑通一次。
2. 再执行 `prepare-profile` 保存登录态。
3. 最后切到 `headless = true` + `selection_mode = "select_all"` 测试后台模式。

如果你追求稳定，不建议一开始就强行全无头，因为淘宝的页面和风控不是稳定 API。
