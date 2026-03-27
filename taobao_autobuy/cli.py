from __future__ import annotations

import argparse
import sys
from pathlib import Path
from textwrap import dedent
from xml.sax.saxutils import escape

from taobao_autobuy import __version__
from taobao_autobuy.app import TaobaoAutoBuyer
from taobao_autobuy.config import AppConfig, ConfigError, load_config
from taobao_autobuy.logger import setup_logger


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="淘宝定时自动抢购工具")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="执行抢购流程")
    run_parser.add_argument("--config", required=True, help="配置文件路径")
    run_group = run_parser.add_mutually_exclusive_group()
    run_group.add_argument("--headless", action="store_true", help="本次强制无头运行")
    run_group.add_argument("--show-browser", action="store_true", help="本次强制显示浏览器")

    prepare_parser = subparsers.add_parser("prepare-profile", help="人工登录并保存浏览器登录态")
    prepare_parser.add_argument("--config", required=True, help="配置文件路径")

    launchd_parser = subparsers.add_parser("render-launchd", help="生成 macOS launchd 的 plist")
    launchd_parser.add_argument("--config", required=True, help="配置文件路径")
    launchd_parser.add_argument("--output", required=True, help="输出 plist 路径")
    launchd_parser.add_argument(
        "--label",
        default="com.taobao.autobuy",
        help="launchd 服务名称，默认 com.taobao.autobuy",
    )
    launchd_parser.add_argument(
        "--python",
        default=sys.executable,
        help="plist 中使用的 Python 可执行文件，默认当前 Python",
    )
    return parser


def load_runtime(config_path: str) -> tuple[AppConfig, TaobaoAutoBuyer]:
    config = load_config(config_path)
    logger = setup_logger(config.output.log_file)
    buyer = TaobaoAutoBuyer(config, logger)
    return config, buyer


def render_launchd(config: AppConfig, output_path: Path, label: str, python_bin: str) -> Path:
    output_path = output_path.expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    stdout_log = output_path.parent / f"{label}.stdout.log"
    stderr_log = output_path.parent / f"{label}.stderr.log"

    plist = dedent(
        f"""\
        <?xml version="1.0" encoding="UTF-8"?>
        <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
        <plist version="1.0">
        <dict>
          <key>Label</key>
          <string>{escape(label)}</string>
          <key>ProgramArguments</key>
          <array>
            <string>{escape(str(Path(python_bin).expanduser().resolve()))}</string>
            <string>-m</string>
            <string>taobao_autobuy</string>
            <string>run</string>
            <string>--config</string>
            <string>{escape(str(config.config_path))}</string>
          </array>
          <key>WorkingDirectory</key>
          <string>{escape(str(config.base_dir))}</string>
          <key>RunAtLoad</key>
          <true/>
          <key>StandardOutPath</key>
          <string>{escape(str(stdout_log))}</string>
          <key>StandardErrorPath</key>
          <string>{escape(str(stderr_log))}</string>
        </dict>
        </plist>
        """
    )

    output_path.write_text(plist, encoding="utf-8")
    return output_path


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "run":
            config, buyer = load_runtime(args.config)
            headless_override = None
            if args.headless:
                headless_override = True
            elif args.show_browser:
                headless_override = False
            buyer.run(headless_override=headless_override)
            return

        if args.command == "prepare-profile":
            _, buyer = load_runtime(args.config)
            buyer.prepare_profile()
            return

        if args.command == "render-launchd":
            config, _ = load_runtime(args.config)
            output = render_launchd(config, Path(args.output), args.label, args.python)
            print(f"已生成 launchd 配置: {output}")
            return

        parser.error(f"未知命令: {args.command}")
    except ConfigError as exc:
        print(f"[CONFIG ERROR] {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    except KeyboardInterrupt:
        print("用户中断执行", file=sys.stderr)
        raise SystemExit(130)
