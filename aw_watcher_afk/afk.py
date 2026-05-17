import json
import logging
import os
import platform
import requests
from datetime import datetime, timedelta, timezone
from time import sleep

from aw_client import ActivityWatchClient
from aw_core.models import Event

from .config import load_config

system = platform.system()

if system == "Windows":
    # noreorder
    from .windows import seconds_since_last_input  # fmt: skip
elif system == "Darwin":
    # noreorder
    from .macos import seconds_since_last_input  # fmt: skip
elif system == "Linux":
    # noreorder
    from .unix import seconds_since_last_input  # fmt: skip
else:
    raise Exception(f"Unsupported platform: {system}")


logger = logging.getLogger(__name__)
td1ms = timedelta(milliseconds=1)


def _patch_client_auth(client, user, password):
    """Replace aw-client HTTP methods to inject Basic Auth credentials."""
    from aw_client.client import always_raise_for_request_errors

    auth = requests.auth.HTTPBasicAuth(user, password)
    _url = client._url

    @always_raise_for_request_errors
    def _get(self_ref, endpoint, params=None):
        return requests.get(_url(endpoint), params=params, auth=auth)

    @always_raise_for_request_errors
    def _post(self_ref, endpoint, data, params=None):
        headers = {"Content-type": "application/json", "charset": "utf-8"}
        return requests.post(_url(endpoint), data=bytes(json.dumps(data), "utf8"), headers=headers, params=params, auth=auth)

    @always_raise_for_request_errors
    def _delete(self_ref, endpoint, data=None):
        if data is None:
            data = {}
        headers = {"Content-type": "application/json"}
        return requests.delete(_url(endpoint), data=json.dumps(data), headers=headers, auth=auth)

    client._get = lambda endpoint, params=None: _get(client, endpoint, params)
    client._post = lambda endpoint, data, params=None: _post(client, endpoint, data, params)
    client._delete = lambda endpoint, data=None: _delete(client, endpoint, data)


class Settings:
    def __init__(self, config_section, timeout=None, poll_time=None):
        # Time without input before we're considering the user as AFK
        self.timeout = timeout or config_section["timeout"]
        # How often we should poll for input activity
        self.poll_time = poll_time or config_section["poll_time"]

        assert self.timeout >= self.poll_time


class AFKWatcher:
    def __init__(self, args, testing=False):
        # Read settings from config
        self.settings = Settings(
            load_config(testing), timeout=args.timeout, poll_time=args.poll_time
        )

        self.client = ActivityWatchClient(
            "aw-watcher-afk", host=args.host, port=args.port, testing=testing
        )

        if args.auth_user and args.auth_password:
            _patch_client_auth(self.client, args.auth_user, args.auth_password)
            logger.info("HTTP Basic Auth enabled for user: %s", args.auth_user)

        self.bucketname = "{}_{}".format(
            self.client.client_name, self.client.client_hostname
        )

        # Store initial parent PID for orphan detection
        self._initial_ppid = os.getppid()

    def ping(self, afk: bool, timestamp: datetime, duration: float = 0):
        data = {"status": "afk" if afk else "not-afk"}
        e = Event(timestamp=timestamp, duration=duration, data=data)
        pulsetime = self.settings.timeout + self.settings.poll_time
        self.client.heartbeat(self.bucketname, e, pulsetime=pulsetime, queued=True)

    def run(self):
        logger.info("aw-watcher-afk started")

        # Initialization
        self.client.wait_for_start()

        eventtype = "afkstatus"
        self.client.create_bucket(self.bucketname, eventtype, queued=True)

        # Start afk checking loop
        with self.client:
            self.heartbeat_loop()

    def heartbeat_loop(self):
        afk = False
        while True:
            try:
                if system in ["Darwin", "Linux"] and os.getppid() != self._initial_ppid:
                    logger.info(
                        "afkwatcher stopped because parent process died "
                        f"(ppid changed from {self._initial_ppid} to {os.getppid()})"
                    )
                    break

                now = datetime.now(timezone.utc)
                seconds_since_input = seconds_since_last_input()
                last_input = now - timedelta(seconds=seconds_since_input)
                logger.debug(f"Seconds since last input: {seconds_since_input}")

                # If no longer AFK
                if afk and seconds_since_input < self.settings.timeout:
                    logger.info("No longer AFK")
                    self.ping(afk, timestamp=last_input)
                    afk = False
                    # ping with timestamp+1ms with the next event (to ensure the latest event gets retrieved by get_event)
                    self.ping(afk, timestamp=last_input + td1ms)
                # If becomes AFK
                elif not afk and seconds_since_input >= self.settings.timeout:
                    logger.info("Became AFK")
                    self.ping(afk, timestamp=last_input)
                    afk = True
                    # ping with timestamp+1ms with the next event (to ensure the latest event gets retrieved by get_event)
                    self.ping(
                        afk, timestamp=last_input + td1ms, duration=seconds_since_input
                    )
                # Send a heartbeat if no state change was made
                else:
                    if afk:
                        # we need the +1ms here too, to make sure we don't "miss" the last heartbeat
                        # (if last_input hasn't changed)
                        self.ping(
                            afk,
                            timestamp=last_input + td1ms,
                            duration=seconds_since_input,
                        )
                    else:
                        self.ping(afk, timestamp=last_input)

                sleep(self.settings.poll_time)

            except KeyboardInterrupt:
                logger.info("aw-watcher-afk stopped by keyboard interrupt")
                break
