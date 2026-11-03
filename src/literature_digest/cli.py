"""The same entry point for pip and Homebrew installations."""

import argparse
import json
import sqlite3
import subprocess
import sys
import time

from . import __version__
from .collector import collect
from .config import Paths, initialize, load_feeds, load_settings
from .database import Database
from .doctor import diagnose
from .generator import generate
from .publisher import publish
from .runtime import configure_logging, process_lock
from .server import make_server
from .service import manage


def parser():
    p = argparse.ArgumentParser(
        prog="literature-digest",
        description="科学論文RSSを短い日本語ニュースに編集してローカル配信します",
    )
    p.add_argument("--version", action="version", version=f"LiteratureDigest {__version__}")

    # Put global options on each subparser too, so either ordering works.
    def common(target, suppress=False):
        default = argparse.SUPPRESS if suppress else None
        target.add_argument(
            "--home",
            default=default,
            metavar="DIR",
            help="データ・設定ディレクトリ（環境変数LITERATURE_DIGEST_HOMEも可）",
        )
        target.add_argument("--verbose", action="store_true", default=default, help="詳細ログ")
        target.add_argument(
            "--dry-run",
            action="store_true",
            default=default,
            help="API・データ更新・サービス操作をせず予定を表示",
        )
        target.add_argument(
            "--limit",
            type=positive,
            default=default,
            metavar="N",
            help="収集はフィードごとの件数、生成は1実行の件数上限",
        )

    common(p)
    sub = p.add_subparsers(dest="command", required=True)
    descriptions = {
        "init": "初期設定（既存設定を保持）",
        "collect": "RSS/Atomを収集",
        "generate": "未処理の記事を生成",
        "run": "収集・記事生成・RSS更新",
        "publish": "RSS再生成",
        "serve": "localhostでRSS配信",
        "status": "処理状態",
        "doctor": "環境診断",
        "service": "LaunchAgent管理",
    }
    for command, help_text in descriptions.items():
        child = sub.add_parser(command, help=help_text)
        common(child, True)
        if command == "init":
            child.add_argument(
                "--copy-prompt",
                action="store_true",
                help="同梱プロンプトをユーザー設定へコピー（上書きしない）",
            )
        if command == "doctor":
            child.add_argument(
                "--offline",
                action="store_true",
                help="認証とHTTP確認を省略（APIは常に呼び出しません）",
            )
        if command == "service":
            child.add_argument(
                "action", choices=["install", "start", "stop", "status", "uninstall"]
            )
            child.add_argument("--target", choices=["all", "batch", "http"], default="all")
            child.add_argument("--binary", help="pip版用CLIの絶対パス。Homebrew版は自動解決")
    return p


def positive(value):
    try:
        n = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("正の整数を指定してください") from None
    if n <= 0:
        raise argparse.ArgumentTypeError("正の整数を指定してください")
    return n


def emit(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def execute(args):
    paths = Paths.resolve(args.home)
    if args.dry_run:
        # No keychain, database opening, logging, network, mkdir or launchctl side effects.
        emit(
            {
                "dry_run": True,
                "command": args.command,
                "home": str(paths.root),
                "limit": args.limit,
                "action": getattr(args, "action", None),
            }
        )
        return 0
    if args.command == "doctor":
        report = diagnose(paths, args.offline)
        emit(report)
        return int(any(v in {"error", "missing"} for v in report.values()))
    if args.command == "init":
        created = initialize(paths, args.copy_prompt)
        with process_lock(paths):
            db = Database(paths.db)
            db.close()
        emit({"home": str(paths.root), "created": created})
        return 0
    if args.command == "status":
        if not paths.db.exists():
            raise ValueError("先にinitを実行してください")
        conn = sqlite3.connect(paths.db.as_uri() + "?mode=ro", uri=True)
        try:
            # Read-only: status must not migrate or recover an active worker.
            db = Database.__new__(Database)
            db.conn = conn
            emit(db.status())
        finally:
            conn.close()
        return 0
    if args.command == "service":
        settings = load_settings(paths) if args.action == "install" else {}
        emit(manage(args.action, paths, settings, args.target, args.binary))
        return 0
    settings = load_settings(paths)
    if args.command == "serve":
        server = make_server(paths.feed, settings["server"]["port"], settings["server"]["host"])
        try:
            server.serve_forever()
        finally:
            server.server_close()
        return 0
    feeds = load_feeds(paths) if args.command in {"collect", "run"} else []
    if not paths.db.exists():
        raise ValueError("先にinitを実行してください")
    logger = configure_logging(paths, args.verbose)
    start = time.monotonic()
    logger.info("Execution start command=%s", args.command)
    report = {}
    try:
        with process_lock(paths):
            db = Database(paths.db)
            try:
                if args.command in {"collect", "run"}:
                    report["collect"] = collect(db, feeds, args.limit)
                if args.command in {"generate", "run"}:
                    report["generate"] = generate(db, paths, settings, args.limit)
                if args.command in {"publish", "run"}:
                    report["published"] = publish(db, paths, settings)
                    logger.info("RSS published count=%s", report["published"])
            finally:
                db.close()
        emit(report)
        return int(
            bool(
                report.get("collect", {}).get("feed_errors")
                or report.get("generate", {}).get("failed")
            )
        )
    finally:
        logger.info(
            "Execution end command=%s elapsed=%.2fs", args.command, time.monotonic() - start
        )


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        return execute(args)
    except KeyboardInterrupt:
        print("処理を中断しました。未完了記事は次回に回収します。", file=sys.stderr)
        return 130
    except (OSError, ValueError, sqlite3.Error, subprocess.SubprocessError) as exc:
        # External exceptions may embed credentials or source data. Only our local ValueErrors are descriptive.
        message = (
            str(exc)
            if type(exc) is ValueError or type(exc).__module__ == "literature_digest.config"
            else type(exc).__name__
        )
        print(f"エラー: {message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
