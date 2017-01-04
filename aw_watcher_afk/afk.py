import logging
import platform
from datetime import datetime, timedelta, timezone
from time import sleep
import argparse

from aw_core.models import Event
from aw_core.log import setup_logging
from aw_client import ActivityWatchClient

from .listeners import KeyboardListener, MouseListener

# TODO: Move to argparse
# Will be overridden if --testing flag is given
settings = {
    "timeout": 180,
    "update_interval": 30,
    "check_interval": 5,
}


def main() -> None:
    """ Set up argparse """
    parser = argparse.ArgumentParser("A watcher for keyboard and mouse input to detect AFK state")
    parser.add_argument("-v", dest='verbose', action="store_true",
                        help='run with verbose logging')
    parser.add_argument("--testing", action="store_true",
                        help='run in testing mode')
    parser.add_argument("--desktop-notify", action="store_true",
                        help='sends desktop notifications when you become afk/non-afk')
    args = parser.parse_args()

    """ If running in testing mode, use shortened timeouts """
    if args.testing:
        settings["timeout"] = 20
        settings["update_interval"] = 5
        settings["check_interval"] = 1

    """ Set up logging """
    setup_logging("aw-watcher-afk",
                  testing=args.testing, verbose=args.verbose,
                  log_stderr=True, log_file=True)
    logger = logging.getLogger("aw.watcher.afk")

    """ Set up aw-client """
    client = ActivityWatchClient("aw-watcher-afk", testing=args.testing)
    bucketname = "{}_{}".format(client.client_name, client.client_hostname)
    eventtype = "afkstatus"
    client.create_bucket(bucketname, eventtype)

    """ Desktop Notifications """
    if args.desktop_notify:
        from gi.repository import Notify
        Notify.init("afkwatcher")

    def send_notification(msg):
        if args.desktop_notify:
            # Can crash the application if the notification daemon disappears
            n = Notify.Notification.new("AFK state changed", msg)
            n.show()

    """ Setup listeners """
    mouseListener = MouseListener()
    mouseListener.start()

    keyboardListener = KeyboardListener()
    # OS X doesn't seem to like the KeyboardListener, segfaults
    if platform.system() == "Darwin":
        logger.warning("KeyboardListener is broken in OS X, will not use for detecting AFK state.")
    else:
        keyboardListener.start()

    """ Variable initializer """
    afk = None
    now = datetime.now(timezone.utc)
    last_change = now           # Last time the state changed
    last_activity = now         # Last time of input activity
    second_last_activity = now  # Second last time of input activity
    last_update = now           # Last report time
    last_check = now            # Last check/poll time

    def _report_state(afk, duration, timestamp, update=False):
        """
        State Reporter
        """
        try:
            assert duration >= timedelta()
        except:
            logger.warning("Duration was negative: {}s".format(duration.total_seconds()))

        label = "afk" if afk else "not-afk"
        e = Event(label=label, timestamp=timestamp, duration=duration)

        if update:
            client.replace_last_event(bucketname, e)
        else:
            client.send_event(bucketname, e)

    def change_state(when=now):
        nonlocal afk
        nonlocal last_change, last_update

        _report_state(afk=afk, duration=when - last_change, timestamp=last_change, update=True)
        afk = not afk
        last_change = when
        last_update = now
        _report_state(afk=afk, duration=now - when, timestamp=last_change, update=False)

        if afk:
            msg = "Now AFK (no activity for {timeout}s, therefore became AFK {timeout}s ago)".format(timeout=(now - when).total_seconds())
        else:
            msg = "No longer AFK (activity detected)"
        logger.info(msg)
        send_notification(msg)

    def update_unchanged(when):
        nonlocal last_update
        last_update = now
        duration = now - last_change
        _report_state(afk, duration=duration, timestamp=last_change, update=True)

    def set_state(new_afk, when):
        if afk == new_afk:
            update_unchanged(when)
        else:
            change_state(when)

    """
    Run watcher
    """

    logger.info("afkwatcher started")

    """ Initialization """
    sleep(1)
    afk = not mouseListener.has_new_event() or keyboardListener.has_new_event()
    _report_state(afk=afk, duration=timedelta(), timestamp=now)

    while True:
        try:
            # Might as well be put at the end of the loop, but it's more visible here.
            # Used for detecting if the computer is put to sleep.
            last_check = now

            sleep(settings["check_interval"])
            now = datetime.now(timezone.utc)

            new_event = False
            if mouseListener.has_new_event() or keyboardListener.has_new_event():
                # logger.debug("New event")
                new_event = True
                second_last_activity, last_activity = last_activity, now
                # Get/clear events
                mouse_event = mouseListener.next_event()
                keyboard_event = keyboardListener.next_event()

            if now > last_check + timedelta(seconds=2 * settings["check_interval"]):
                """
                Computer has been woken up from a sleep/hibernation
                (or computer has a hang longer than the timeout, which is unlikely)
                """
                logger.debug(20 * "-")
                logger.info("Hibernation/sleep/stalling detected")
                # Report
                # set_state(True, second_last_activity)
                # TODO: Uncertain about this conditional
                if afk:
                    _report_state(afk=True, duration=now - second_last_activity, timestamp=second_last_activity, update=True)
                else:
                    change_state(second_last_activity)
                change_state(now)
                # NOTE: Kind of iffy. Gives incorrect behavior in case of stall, but it's the easiest solution we found to an annoying problem.
                last_activity = now
                afk = False
            elif afk and new_event:
                """ No longer AFK """
                logger.debug(20 * "-")
                logger.debug("Became non-AFK")
                change_state(now)
            elif not afk and now > last_activity + timedelta(seconds=settings["timeout"]):
                """ Now afk """
                logger.debug(20 * "-")
                logger.debug("Became AFK")
                change_state(last_activity)
            elif now > last_update + timedelta(seconds=settings["update_interval"]):
                """ Report state again if it was a long time since last time """
                logger.debug(20 * "-")
                logger.debug("Updating last event")
                update_unchanged(now)

        except KeyboardInterrupt:
            logger.info("afkwatcher stopped by keyboard interrupt")
            break
