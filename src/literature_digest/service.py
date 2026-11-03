"""Two independent, user-controlled LaunchAgents with stable executable paths."""

import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

LABELS = {"batch": "ai.literaturedigest.batch", "http": "ai.literaturedigest.http"}


def stable_binary(override=None):
    if override:
        path = Path(override).expanduser().absolute()
    else:
        brew = shutil.which("brew")
        if not brew:
            raise ValueError(
                "brewが見つかりません。pip版ではservice install --binary /absolute/pathを指定してください"
            )
        result = subprocess.run(
            [brew, "--prefix"], capture_output=True, text=True, check=True, timeout=30
        )
        path = Path(result.stdout.strip()) / "bin/literature-digest"
    if not path.is_absolute() or not path.is_file() or not os.access(path, os.X_OK):
        raise ValueError("実行可能なCLIの絶対パスを指定してください")
    if "Cellar" in path.parts:
        raise ValueError("Cellar内ではなくHomebrewのbin/literature-digestを指定してください")
    # Do not resolve(): a symlink intentionally follows upgrades.
    return str(path)


def build_plists(binary, paths, settings):
    result = {}
    for target, label in LABELS.items():
        spec = {
            "Label": label,
            "ProgramArguments": [
                binary,
                "--home",
                str(paths.root),
                "run" if target == "batch" else "serve",
            ],
            "StandardOutPath": str(paths.logs / f"{target}.out.log"),
            "StandardErrorPath": str(paths.logs / f"{target}.err.log"),
            "ProcessType": "Background",
            "Umask": 0o077,
        }
        if target == "batch":
            schedule = settings["schedule"]
            spec["StartCalendarInterval"] = [
                {"Weekday": day, "Hour": schedule["hour"], "Minute": schedule["minute"]}
                for day in schedule["weekdays"]
            ]
        else:
            spec.update({"RunAtLoad": True, "KeepAlive": True, "ThrottleInterval": 10})
        result[target] = spec
    return result


def manage(action, paths, settings, target="all", binary=None, agent_dir=None):
    if sys.platform != "darwin":
        raise ValueError("LaunchAgentはmacOS専用です")
    directory = agent_dir or Path.home() / "Library/LaunchAgents"
    targets = list(LABELS) if target == "all" else [target]
    domain = f"gui/{os.getuid()}"
    output = {}
    if action == "install":
        specs = build_plists(stable_binary(binary), paths, settings)
        directory.mkdir(parents=True, exist_ok=True)
        paths.logs.mkdir(parents=True, exist_ok=True)
        for item in targets:
            dest = directory / f"{LABELS[item]}.plist"
            if dest.exists():
                raise ValueError(
                    "既存のLaunchAgentがあります。変更時はservice uninstall後にinstallしてください"
                )
        for item in targets:
            with (directory / f"{LABELS[item]}.plist").open("xb") as out:
                plistlib.dump(specs[item], out)
            output[item] = "installed (service startで起動)"
        return output
    for item in targets:
        label = LABELS[item]
        dest = directory / f"{label}.plist"

        def ctl(*args):
            return subprocess.run(
                ["/bin/launchctl", *args], capture_output=True, text=True, timeout=30
            )

        loaded = ctl("print", f"{domain}/{label}").returncode == 0
        if action == "status":
            output[item] = (
                "loaded" if loaded else "installed/stopped" if dest.exists() else "not installed"
            )
        elif action == "start":
            if not dest.exists():
                raise ValueError("先にservice installを実行してください")
            if ctl("enable", f"{domain}/{label}").returncode != 0:
                raise ValueError("launchctl enableに失敗しました")
            if not loaded and ctl("bootstrap", domain, str(dest)).returncode != 0:
                raise ValueError(
                    "launchctl bootstrapに失敗しました。service statusとログを確認してください"
                )
            output[item] = "started" if item == "http" else "scheduled"
        elif action in {"stop", "uninstall"}:
            if loaded and ctl("bootout", f"{domain}/{label}").returncode != 0:
                raise ValueError("launchctl bootoutに失敗しました。plistは削除していません")
            if action == "stop":
                if ctl("disable", f"{domain}/{label}").returncode != 0:
                    raise ValueError("launchctl disableに失敗しました")
            if action == "uninstall":
                dest.unlink(missing_ok=True)
            output[item] = "stopped" if action == "stop" else "uninstalled (ユーザーデータ保持)"
    return output
