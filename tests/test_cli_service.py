import plistlib
import sqlite3
from unittest.mock import patch

import pytest

from literature_digest.cli import main
from literature_digest.config import (
    ConfigError,
    Paths,
    initialize,
    load_feeds,
    load_settings,
    template,
)
from literature_digest.credentials import api_key
from literature_digest.database import Database
from literature_digest.doctor import diagnose
from literature_digest.runtime import configure_logging, process_lock
from literature_digest.service import build_plists, stable_binary


def test_init_idempotent(paths):
    config = paths.config / "feeds.yaml"
    config.write_text("feeds: []\n# user data\n")
    assert initialize(paths) == []
    assert "user data" in config.read_text()
    assert "v1" in template("prompts/digest.md")


def test_home_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("LITERATURE_DIGEST_HOME", str(tmp_path / "custom"))
    assert Paths.resolve().root == tmp_path / "custom"
    assert Paths.resolve(tmp_path / "override").root == tmp_path / "override"


def test_cli_commands(paths, capsys):
    assert main(["init", "--home", str(paths.root)]) == 0
    assert main(["--home", str(paths.root), "publish"]) == 0
    assert main(["status", "--home", str(paths.root)]) == 0
    assert main(["--home", str(paths.root), "doctor", "--offline"]) == 0
    assert "not checked" in capsys.readouterr().out


def test_dry_run_has_no_effects(tmp_path, capsys):
    root = tmp_path / "missing"
    for cmd in ["init", "run", "collect", "generate", "publish", "serve"]:
        assert main(["--home", str(root), cmd, "--dry-run"]) == 0
    assert not root.exists()


def test_negative_limit_rejected():
    with pytest.raises(SystemExit):
        main(["run", "--limit", "0"])


def test_invalid_config_no_secrets(paths, capsys):
    (paths.config / "settings.yaml").write_text("llm:\n  api_key: secret-key\n")
    assert main(["--home", str(paths.root), "run"]) == 1
    assert "secret-key" not in capsys.readouterr().err


@pytest.mark.parametrize(
    "value",
    [
        "server:\n  host: 0.0.0.0\n",
        "llm:\n  timeout: false\n",
        "schedule:\n  weekdays: [7]\n",
        "llm:\n  max_completion_tokens: 9000\n",
    ],
)
def test_config_validation(paths, value):
    (paths.config / "settings.yaml").write_text(value)
    with pytest.raises(ConfigError):
        load_settings(paths)


def test_feeds_validation(paths):
    (paths.config / "feeds.yaml").write_text("feeds:\n- id: a\n  name: A\n  url: file:///secret\n")
    with pytest.raises(ConfigError):
        load_feeds(paths)


def test_db_future_schema_protected(paths):
    conn = sqlite3.connect(paths.db)
    conn.execute("PRAGMA user_version=99")
    conn.close()
    with pytest.raises(ValueError):
        Database(paths.db)


def test_lock_excludes_second_worker(paths):
    with process_lock(paths):
        with pytest.raises(ValueError):
            with process_lock(paths):
                pass


def test_plists_preserve_stable_brew_path(paths, settings):
    value = build_plists("/opt/homebrew/bin/literature-digest", paths, settings)
    for target, spec in value.items():
        assert spec["ProgramArguments"][0] == "/opt/homebrew/bin/literature-digest"
        assert "EnvironmentVariables" not in spec
        assert plistlib.loads(plistlib.dumps(spec)) == spec
    assert [d["Weekday"] for d in value["batch"]["StartCalendarInterval"]] == [1, 2, 3, 4, 5]
    assert value["batch"]["StartCalendarInterval"][0]["Hour"] == 8
    assert value["http"]["RunAtLoad"] and "StartCalendarInterval" not in value["http"]


def test_service_does_not_resolve_symlink(tmp_path):
    target = tmp_path / "Cellar/app/1/bin/command"
    target.parent.mkdir(parents=True)
    target.write_text("#!/bin/sh\n")
    target.chmod(0o755)
    link = tmp_path / "bin/literature-digest"
    link.parent.mkdir()
    link.symlink_to(target)
    assert stable_binary(str(link)) == str(link)
    with pytest.raises(ValueError):
        stable_binary(str(target))


def test_credentials_never_output(monkeypatch, capsys):
    monkeypatch.setenv("SARASHINA_API_KEY", "test-secret")
    assert api_key() == "test-secret"
    assert not capsys.readouterr().out


def test_log_redaction(paths, monkeypatch):
    monkeypatch.setenv("SARASHINA_API_KEY", "test-secret")
    logger = configure_logging(paths)
    logger.warning("key=%s", "test-secret")
    assert "test-secret" not in (paths.logs / "literature-digest.log").read_text()
    assert "[REDACTED]" in (paths.logs / "literature-digest.log").read_text()


def test_offline_doctor_no_keychain(paths):
    db = Database(paths.db)
    db.close()
    with patch("literature_digest.doctor.api_key", side_effect=AssertionError("no keychain")):
        assert diagnose(paths, True)["database"] == "ok"


def test_prompt_copy_is_explicit_and_idempotent(paths):
    assert not (paths.config / "digest.md").exists()
    assert initialize(paths, copy_prompt=True) == ["digest.md"]
    (paths.config / "digest.md").write_text("custom instructions")
    assert initialize(paths, copy_prompt=True) == []
    assert (paths.config / "digest.md").read_text() == "custom instructions"


def test_service_recovery_does_not_require_valid_config(paths):
    (paths.config / "settings.yaml").write_text("broken: [invalid yaml")
    for action in ["stop", "status", "uninstall"]:
        with patch("literature_digest.cli.manage", return_value={"http": "stopped"}) as manage:
            assert main(["--home", str(paths.root), "service", action]) == 0
            assert manage.call_args.args[0] == action
