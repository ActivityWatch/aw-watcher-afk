import argparse
import sys

from aw_core.config import load_config_toml

default_config = """
[aw-watcher-afk]
timeout = 180
poll_time = 5
host = ""
port = ""
auth_user = ""
auth_password = ""

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
    default_host = config.get("host", "") or None
    default_port = config.get("port", "") or None
    default_auth_user = config.get("auth_user", "")
    default_auth_password = config.get("auth_password", "")

    parser = argparse.ArgumentParser(
        description="A watcher for keyboard and mouse input to detect AFK state."
    )
    parser.add_argument("--host", dest="host", default=default_host)
    parser.add_argument("--port", dest="port", default=default_port)
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
    parser.add_argument(
        "--auth-user",
        dest="auth_user",
        default=default_auth_user,
        help="Username for HTTP Basic Auth (for nginx-proxied servers)",
    )
    parser.add_argument(
        "--auth-password",
        dest="auth_password",
        default=default_auth_password,
        help="Password for HTTP Basic Auth (for nginx-proxied servers)",
    )
    parsed_args = parser.parse_args()
    return parsed_args
