from configparser import ConfigParser
from aw_core.config import load_config

default_settings = {
    "timeout": "180",
    "update_time": "30",
    "poll_time": "5",
}
default_testing_settings = {
    "timeout": "20",
    "update_time": "5",
    "poll_time": "1",
}

default_config = ConfigParser()
default_config['aw-watcher-afk'] = default_settings
default_config['aw-watcher-afk-testing'] = default_testing_settings
watcher_config = load_config("aw-watcher-afk", default_config)
