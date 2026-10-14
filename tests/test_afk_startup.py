"""Startup integration tests with the real client and its persistent queue."""

import json
import socket
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import requests

from aw_watcher_afk.afk import AFKWatcher


class OfflineStartupTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        # Isolate config, instance locks and SQLite queues on every platform,
        # including the replacement queue created by client.disconnect().
        for name in ("data", "cache", "config"):
            self.enter_patch(
                patch(
                    "aw_core.dirs.platformdirs.user_" + name + "_dir",
                    return_value=str(Path(directory.name) / name),
                )
            )

        self.available = threading.Event()
        self.offline_attempt = threading.Event()
        self.sampled = threading.Event()
        self.stop = threading.Event()
        self.delivered = threading.Event()
        self.expected_heartbeats = 0
        self.requests = []
        self.errors = []
        self.samples = iter((0.0, 20.0, 0.0))
        self.enter_patch(patch("aw_watcher_afk.afk.system", "Windows"))
        self.enter_patch(
            patch("aw_watcher_afk.afk.is_screen_locked", return_value=False)
        )
        self.enter_patch(
            patch(
                "aw_watcher_afk.afk.seconds_since_last_input",
                side_effect=self.sample,
            )
        )
        self.enter_patch(
            patch("requests.sessions.Session.request", side_effect=self.request)
        )

        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        self.watcher = AFKWatcher(
            SimpleNamespace(host="127.0.0.1", port=port, timeout=10, poll_time=0.01),
            testing=True,
        )
        self.queue = self.watcher.client.request_queue
        self.queue._attempt_reconnect_interval = 0.01
        self.thread = threading.Thread(target=self.run_watcher, daemon=True)
        self.addCleanup(self.cleanup_watcher)

    def enter_patch(self, patcher):
        result = patcher.start()
        self.addCleanup(patcher.stop)
        return result

    def sample(self):
        try:
            return next(self.samples)
        except StopIteration:
            # All preceding samples have been processed by the real loop.
            self.sampled.set()
            self.stop.wait(3)
            raise KeyboardInterrupt

    def request(self, method, url, **kwargs):
        if not self.available.is_set():
            self.offline_attempt.set()
            # Bound cleanup if a regression blocks in wait_for_start(), before
            # the watcher reaches the interruptible sensor loop.
            if self.stop.is_set() and method.upper() == "GET":
                raise KeyboardInterrupt
            raise requests.ConnectionError("server has not started")
        payload = json.loads(kwargs.get("data", b"{}"))
        self.requests.append((method.upper(), url, payload))
        heartbeats = sum("/heartbeat" in request[1] for request in self.requests)
        if self.expected_heartbeats and heartbeats == self.expected_heartbeats:
            self.delivered.set()
        response = requests.Response()
        response.status_code = 200
        response._content = b"{}"
        return response

    def run_watcher(self):
        try:
            self.watcher.run()
        except KeyboardInterrupt:
            # Deliberate shutdown signal raised by sample()/request() once the
            # test has observed what it needs; not a watcher failure.
            pass
        except Exception as error:
            self.errors.append(error)

    def cleanup_watcher(self):
        self.stop.set()
        if self.thread.ident is not None:
            self.thread.join(2)
        self.queue.stop()
        if self.queue.ident is not None:
            self.queue.join(2)
        self.assertFalse(self.thread.is_alive(), "watcher leaked from test")
        self.assertFalse(self.queue.is_alive(), "queue worker leaked from test")
        for queue in {self.queue, self.watcher.client.request_queue}:
            queue._persistqueue.close()
        instance = self.watcher.client.instance
        if hasattr(instance, "fp"):
            instance.fp.close()
        elif hasattr(instance, "fd"):
            # Let the Windows SingleInstance destructor release its lock.
            del self.watcher.client.instance

    def start_offline(self):
        self.thread.start()
        self.assertTrue(self.offline_attempt.wait(1), "no connection attempt")
        self.assertTrue(
            self.sampled.wait(1), "recording never started while the server was down"
        )
        self.assertEqual(self.errors, [])
        self.assertGreater(self.queue._persistqueue.qsize(), 0)
        self.assertEqual(self.requests, [])

    def test_records_offline_then_creates_bucket_before_replaying(self):
        self.start_offline()
        self.expected_heartbeats = self.queue._persistqueue.qsize()
        self.available.set()
        self.assertTrue(
            self.delivered.wait(1), "queued heartbeats were not all replayed"
        )
        self.assertEqual(len(self.requests), self.expected_heartbeats + 1)
        method, url, payload = self.requests[0]
        self.assertEqual(method, "POST")
        self.assertTrue(url.endswith("/buckets/" + self.watcher.bucketname))
        self.assertEqual(payload["type"], "afkstatus")
        method, url, payload = self.requests[1]
        self.assertEqual(method, "POST")
        self.assertIn("/heartbeat?pulsetime=", url)
        self.assertEqual(payload["data"], {"status": "not-afk"})
        self.assertIn(
            {"status": "afk"}, [payload["data"] for _, _, payload in self.requests[1:]]
        )

    def test_shutdown_offline_preserves_queued_heartbeats(self):
        self.start_offline()
        queued = self.queue._persistqueue.qsize()
        self.stop.set()
        self.thread.join(1)
        self.assertFalse(self.thread.is_alive(), "offline shutdown blocked")
        self.assertFalse(self.queue.is_alive())
        self.assertEqual(self.errors, [])
        # disconnect() constructs a new queue from the same SQLite files.
        reopened = self.watcher.client.request_queue._persistqueue
        self.assertEqual(reopened.qsize(), queued)
        self.assertEqual(reopened.get(block=False).data["data"], {"status": "not-afk"})


if __name__ == "__main__":
    unittest.main()
