import sys
import argparse

from aw_core.config import load_config_toml

default_config = """
[aw-watcher-afk]
timeout = 180
poll_time = 5

[aw-watcher-afk-testing]
timeout = 20
poll_time = 1
""".strip()


def load_config(testing: bool):
    section = "aw-watcher-afk" + ("-testing" if testing else "")
    return load_config_toml("aw-watcher-afk", default_config)[section]


def parse_args():
    # get testing in a dirty way, because we need it for the config lookup
    testing = "--testing" in sys.argv
    config = load_config(testing)

    default_poll_time = config["poll_time"]
    default_timeout = config["timeout"]

    parser = argparse.ArgumentParser(
        "A watcher for keyboard and mouse input to detect AFK state."
    )
    parser.add_argument("--host", dest="host")
    parser.add_argument("--port", dest="port")
    parser.add_argument(
        "--testing", dest="testing", action="store_true", help="run in testing mode"
    )
    parser.add_argument(
        "--verbose",
        dest="verbose",
        action="store_true",
        help="run with verbose logging",
    )
    parser.add_argument(
        "--timeout", dest="timeout", type=float, default=default_timeout
    )
    parser.add_argument(
        "--poll-time", dest="poll_time", type=float, default=default_poll_time
    )
    parsed_args = parser.parse_args()
    return parsed_args
