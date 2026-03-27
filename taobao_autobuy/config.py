from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib


TAOBAO_HOME = "https://www.taobao.com"
TAOBAO_CART = "https://cart.taobao.com/cart.htm"


class ConfigError(ValueError):
    pass


def _read_text_map(path: Path) -> dict[str, Any]:
    with path.open("rb") as fh:
        data = tomllib.load(fh)
    if not isinstance(data, dict):
        raise ConfigError("配置文件格式错误，根节点必须是对象")
    return data


def _resolve_path(path_str: str, base_dir: Path) -> Path:
    path = Path(path_str).expanduser()
    if not path.is_absolute():
        path = (base_dir / path).resolve()
    return path


def _ensure_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{field_name} 必须是整数")
    return value


def _ensure_float(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{field_name} 必须是数字")
    return float(value)


def _ensure_bool(value: Any, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"{field_name} 必须是布尔值")
    return value


def _ensure_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{field_name} 必须是非空字符串")
    return value.strip()


@dataclass(slots=True)
class RunConfig:
    buy_time_text: str
    timezone_name: str
    stop_refresh_before_seconds: int
    max_login_retry_times: int
    login_check_interval: int
    keep_alive_interval: int
    max_submit_retry_times: int
    poll_interval_seconds: float

    @property
    def timezone(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.timezone_name)
        except Exception as exc:
            raise ConfigError(f"无效时区: {self.timezone_name}") from exc

    @property
    def buy_time(self) -> dt.datetime:
        try:
            naive = dt.datetime.strptime(self.buy_time_text, "%Y-%m-%d %H:%M:%S")
        except ValueError as exc:
            raise ConfigError("buy_time 格式必须是 YYYY-MM-DD HH:MM:SS") from exc
        return naive.replace(tzinfo=self.timezone)


@dataclass(slots=True)
class BrowserConfig:
    headless: bool
    detach: bool
    window_size: str
    page_load_timeout: int
    chrome_binary: str | None
    driver_path: str | None
    user_data_dir: Path
    profile_directory: str


@dataclass(slots=True)
class CartConfig:
    selection_mode: str
    auto_select_on_retry: bool

    def validate(self, headless: bool) -> None:
        valid_modes = {"manual", "select_all"}
        if self.selection_mode not in valid_modes:
            values = ", ".join(sorted(valid_modes))
            raise ConfigError(f"cart.selection_mode 只能是: {values}")
        if headless and self.selection_mode == "manual":
            raise ConfigError("headless 模式不能使用 manual 选品，请改成 select_all")


@dataclass(slots=True)
class OutputConfig:
    log_file: Path
    screenshot_dir: Path
    leave_browser_open: bool


@dataclass(slots=True)
class AppConfig:
    config_path: Path
    taobao_home: str
    taobao_cart: str
    run: RunConfig
    browser: BrowserConfig
    cart: CartConfig
    output: OutputConfig

    @property
    def base_dir(self) -> Path:
        return self.config_path.parent


def load_config(config_path: str | Path) -> AppConfig:
    path = Path(config_path).expanduser().resolve()
    if not path.exists():
        raise ConfigError(f"配置文件不存在: {path}")

    raw = _read_text_map(path)
    base_dir = path.parent

    run_raw = raw.get("run", {})
    browser_raw = raw.get("browser", {})
    cart_raw = raw.get("cart", {})
    output_raw = raw.get("output", {})

    if not isinstance(run_raw, dict):
        raise ConfigError("[run] 必须是对象")
    if not isinstance(browser_raw, dict):
        raise ConfigError("[browser] 必须是对象")
    if not isinstance(cart_raw, dict):
        raise ConfigError("[cart] 必须是对象")
    if not isinstance(output_raw, dict):
        raise ConfigError("[output] 必须是对象")

    run = RunConfig(
        buy_time_text=_ensure_str(run_raw.get("buy_time"), "run.buy_time"),
        timezone_name=str(run_raw.get("timezone", "Asia/Shanghai")).strip() or "Asia/Shanghai",
        stop_refresh_before_seconds=_ensure_int(
            run_raw.get("stop_refresh_before_seconds", 180),
            "run.stop_refresh_before_seconds",
        ),
        max_login_retry_times=_ensure_int(
            run_raw.get("max_login_retry_times", 180),
            "run.max_login_retry_times",
        ),
        login_check_interval=_ensure_int(
            run_raw.get("login_check_interval", 2),
            "run.login_check_interval",
        ),
        keep_alive_interval=_ensure_int(
            run_raw.get("keep_alive_interval", 60),
            "run.keep_alive_interval",
        ),
        max_submit_retry_times=_ensure_int(
            run_raw.get("max_submit_retry_times", 50),
            "run.max_submit_retry_times",
        ),
        poll_interval_seconds=_ensure_float(
            run_raw.get("poll_interval_seconds", 0.05),
            "run.poll_interval_seconds",
        ),
    )

    browser = BrowserConfig(
        headless=_ensure_bool(browser_raw.get("headless", False), "browser.headless"),
        detach=_ensure_bool(browser_raw.get("detach", True), "browser.detach"),
        window_size=str(browser_raw.get("window_size", "1440,900")).strip() or "1440,900",
        page_load_timeout=_ensure_int(
            browser_raw.get("page_load_timeout", 20),
            "browser.page_load_timeout",
        ),
        chrome_binary=(
            str(browser_raw.get("chrome_binary", "")).strip() or None
        ),
        driver_path=(
            str(browser_raw.get("driver_path", "")).strip() or None
        ),
        user_data_dir=_resolve_path(
            str(browser_raw.get("user_data_dir", "./runtime/chrome-profile")),
            base_dir,
        ),
        profile_directory=str(browser_raw.get("profile_directory", "Default")).strip() or "Default",
    )

    cart = CartConfig(
        selection_mode=str(cart_raw.get("selection_mode", "manual")).strip() or "manual",
        auto_select_on_retry=_ensure_bool(
            cart_raw.get("auto_select_on_retry", True),
            "cart.auto_select_on_retry",
        ),
    )

    output = OutputConfig(
        log_file=_resolve_path(
            str(output_raw.get("log_file", "./runtime/logs/taobao_autobuy.log")),
            base_dir,
        ),
        screenshot_dir=_resolve_path(
            str(output_raw.get("screenshot_dir", "./runtime/screenshots")),
            base_dir,
        ),
        leave_browser_open=_ensure_bool(
            output_raw.get("leave_browser_open", True),
            "output.leave_browser_open",
        ),
    )

    cart.validate(browser.headless)

    return AppConfig(
        config_path=path,
        taobao_home=TAOBAO_HOME,
        taobao_cart=TAOBAO_CART,
        run=run,
        browser=browser,
        cart=cart,
        output=output,
    )
