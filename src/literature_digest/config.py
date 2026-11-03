"""User-owned configuration, independent of Cellar and current directory."""

import os
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from urllib.parse import urlsplit

import yaml


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Paths:
    root: Path
    logs: Path

    @classmethod
    def resolve(cls, root=None):
        custom = root or os.environ.get("LITERATURE_DIGEST_HOME")
        base = (
            Path(custom).expanduser().absolute()
            if custom
            else (Path.home() / "Library/Application Support/LiteratureDigest")
        )
        return cls(base, base / "logs" if custom else Path.home() / "Library/Logs/LiteratureDigest")

    @property
    def config(self):
        return self.root / "config"

    @property
    def db(self):
        return self.root / "data/literature.db"

    @property
    def feed(self):
        return self.root / "public/feed.xml"


def template(relative):
    return files("literature_digest").joinpath("resources", relative).read_text(encoding="utf-8")


def initialize(paths, copy_prompt=False):
    for directory in [paths.config, paths.db.parent, paths.feed.parent, paths.logs]:
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    created = []
    for name in ["feeds", "settings"]:
        dest = paths.config / f"{name}.yaml"
        try:
            with dest.open("x", encoding="utf-8") as out:
                out.write(template(f"config/{name}.example.yaml"))
            created.append(dest.name)
        except FileExistsError:
            pass
    if copy_prompt:
        try:
            with (paths.config / "digest.md").open("x", encoding="utf-8") as out:
                out.write(template("prompts/digest.md"))
            created.append("digest.md")
        except FileExistsError:
            pass
    return created


def load_yaml(path):
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ConfigError("YAMLのルートはマッピングで指定してください")
        return value
    except (OSError, yaml.YAMLError):
        raise ConfigError("設定を読み込めません。initとYAMLの形式を確認してください") from None


def http_url(value):
    if not isinstance(value, str):
        return False
    try:
        p = urlsplit(value)
        return p.scheme in {"http", "https"} and bool(p.hostname) and not (p.username or p.password)
    except ValueError:
        return False


def load_feeds(paths):
    value = load_yaml(paths.config / "feeds.yaml")
    if set(value) != {"feeds"} or not isinstance(value["feeds"], list):
        raise ConfigError("feeds.yamlにはfeeds配列を指定してください")
    seen = set()
    for f in value["feeds"]:
        if not isinstance(f, dict) or set(f) - {"id", "name", "url", "enabled", "category"}:
            raise ConfigError("フィードに未対応の設定項目があります")
        if not all(isinstance(f.get(k), str) and f[k].strip() for k in ["id", "name", "url"]):
            raise ConfigError("フィードのid、name、urlが必要です")
        if f["id"] in seen or not http_url(f["url"]):
            raise ConfigError("フィードIDが重複しているかURLが不正です")
        if not isinstance(f.get("enabled", True), bool):
            raise ConfigError("enabledはtrue/falseで指定してください")
        if not isinstance(f.get("category", ""), str):
            raise ConfigError("categoryは文字列で指定してください")
        seen.add(f["id"])
    return value["feeds"]


def load_settings(paths):
    defaults = yaml.safe_load(template("config/settings.example.yaml"))
    user = load_yaml(paths.config / "settings.yaml")
    for section, values in user.items():
        if section not in defaults or not isinstance(values, dict):
            raise ConfigError("settings.yamlに未対応の設定項目があります")
        if set(values) - set(defaults[section]):
            raise ConfigError(
                "設定項目が不正です。APIキーは環境変数かキーチェーンを使用してください"
            )
        defaults[section].update(values)
    s = defaults

    def integer(value, low, high):
        return type(value) is int and low <= value <= high

    checks = [
        isinstance(s["llm"]["model"], str) and s["llm"]["model"].startswith("sarashina"),
        type(s["llm"]["temperature"]) in (int, float) and 0 <= s["llm"]["temperature"] <= 2,
        integer(s["llm"]["max_completion_tokens"], 1, 8000),
        integer(s["llm"]["timeout"], 1, 300),
        integer(s["llm"]["retries"], 0, 5),
        integer(s["llm"]["batch_limit"], 1, 1000),
        type(s["metadata"]["pubmed"]) is bool,
        isinstance(s["metadata"]["email"], str),
        integer(s["publisher"]["limit"], 1, 10000),
        all(
            isinstance(s["publisher"][k], str) and s["publisher"][k].strip()
            for k in ["title", "description"]
        ),
        s["server"]["host"] == "127.0.0.1",
        integer(s["server"]["port"], 1, 65535),
        isinstance(s["schedule"]["weekdays"], list)
        and bool(s["schedule"]["weekdays"])
        and all(integer(d, 0, 6) for d in s["schedule"]["weekdays"]),
        integer(s["schedule"]["hour"], 0, 23),
        integer(s["schedule"]["minute"], 0, 59),
    ]
    if not all(checks):
        raise ConfigError("設定値の型・範囲が不正です（HTTPホストは127.0.0.1のみ）")
    return s
