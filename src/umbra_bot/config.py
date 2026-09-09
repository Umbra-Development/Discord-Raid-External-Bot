import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any

import json5


if getattr(sys, "frozen", False):
    APPLICATION_ROOT = Path(sys.executable).resolve().parent
    BUNDLE_ROOT = Path(getattr(sys, "_MEIPASS", APPLICATION_ROOT))
else:
    APPLICATION_ROOT = Path(__file__).resolve().parents[2]
    BUNDLE_ROOT = APPLICATION_ROOT

CONFIG_PATH = APPLICATION_ROOT / "config" / "config.jsonc"
CONFIG_TEMPLATE_PATH = BUNDLE_ROOT / "config" / "config.jsonc.example"


def ensure_config(file_path: str | Path = CONFIG_PATH) -> Path:
    """Create a writable config from the bundled example when needed."""
    config_path = Path(file_path)
    if config_path.exists():
        return config_path
    if not CONFIG_TEMPLATE_PATH.exists():
        raise FileNotFoundError(
            f"Missing configuration template: {CONFIG_TEMPLATE_PATH}"
        )
    config_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(CONFIG_TEMPLATE_PATH, config_path)
    return config_path


def load_config(file_path: str | Path = CONFIG_PATH) -> dict[str, Any]:
    """Load application configuration from a JSON5 file."""
    with ensure_config(file_path).open(encoding="utf-8") as config_file:
        return json5.load(config_file)


def save_config(
    data: dict[str, Any], file_path: str | Path = CONFIG_PATH
) -> None:
    """Atomically save configuration as JSON, which is also valid JSON5."""
    config_path = Path(file_path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{config_path.name}.",
        suffix=".tmp",
        dir=config_path.parent,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as config_file:
            json.dump(data, config_file, ensure_ascii=False, indent=4)
            config_file.write("\n")
        os.replace(temporary_name, config_path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def reload_config() -> dict[str, Any]:
    """Reload the module-level configuration values from disk."""
    loaded = load_config()
    loaded_basic = loaded["basic_config"]
    loaded_messages = loaded["messages"]

    # Resolve every required value before changing module state. A malformed
    # file therefore leaves the last valid configuration active.
    loaded_token = str(loaded["token"])
    loaded_prefix = str(loaded_basic["prefix"])
    loaded_max_uses = int(loaded_basic["max_uses"])
    loaded_window = int(loaded_basic["wait_seconds"])
    loaded_block = int(loaded_basic["b_seconds"])
    loaded_pm = str(loaded_messages["pm"])
    loaded_pingpm = str(loaded_messages["pingpm"])

    if not loaded_prefix:
        raise ValueError("basic_config.prefix cannot be empty")
    if min(loaded_max_uses, loaded_window, loaded_block) < 1:
        raise ValueError("cooldown settings must be positive integers")

    global config, basic_config, messages
    global token, prefix, max_uses, wseconds, bseconds, pm, pingpm

    config = loaded
    basic_config = loaded_basic
    messages = loaded_messages
    token = loaded_token
    prefix = loaded_prefix
    max_uses = loaded_max_uses
    wseconds = loaded_window
    bseconds = loaded_block
    pm = loaded_pm
    pingpm = loaded_pingpm
    return loaded


reload_config()
