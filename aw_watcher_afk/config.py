from aw_core.config import load_config_toml

default_config = """
[aw-watcher-afk]
timeout = 180
poll_time = 5

[aw-watcher-afk-testing]
timeout = 20
poll_time = 1
""".strip()

watcher_config = load_config_toml("aw-watcher-afk", default_config)
