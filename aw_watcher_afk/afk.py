import logging
import platform
from datetime import datetime, timedelta
import pytz
from time import sleep

from aw_core.models import Event
from aw_client import ActivityWatchClient

from .listeners import KeyboardListener, MouseListener

# TODO: Move to argparse
settings = {
    "timeout": 60,
    "check_interval": 1,
}

logger = logging.getLogger("aw.watcher.afk")


def main():
    import argparse

    parser = argparse.ArgumentParser("A watcher for keyboard and mouse input to detect AFK state")
    parser.add_argument("--testing", action="store_true")
    parser.add_argument("--desktop-notify", action="store_true")

    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.testing else logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    client = ActivityWatchClient("aw-watcher-afk", testing=args.testing)

    bucketname = "{}_{}".format(client.client_name, client.client_hostname)
    eventtype = "afkstatus"
    client.create_bucket(bucketname, eventtype)

    if args.desktop_notify:
        from gi.repository import Notify
        Notify.init("afkwatcher")

    def send_notification(msg):
        if args.desktop_notify:
            # Can crash the application if the notification daemon disappears
            n = Notify.Notification.new("AFK state changed", msg)
            n.show()

    now = datetime.now(pytz.utc)
    last_change = now
    last_activity = now
    is_afk = True

    mouseListener = MouseListener()
    mouseListener.start()

    keyboardListener = KeyboardListener()
    # OS X doesn't seem to like the KeyboardListener, segfaults
    if platform.system() != "Darwin":
        keyboardListener.start()
    else:
        logger.warning("KeyboardListener is broken in OS X, will not use for detecting AFK state.")

    logger.info("afkwatcher started")

    def change_to_afk(dt: datetime):
        """
        This function should be called when user becomes AFK
        The argument dt should be the time when the last activity was detected,
        which should be: change_to_afk(dt=last_activity)
        """
        nonlocal last_change
        e = Event(label=["not-afk"],
                  timestamp=[last_change],
                  duration={
                      "value": (dt - last_change).total_seconds(),
                      "unit": "seconds"
                  })
        client.send_event(bucketname, e)
        logger.info("Now AFK")
        send_notification("Now AFK")

        last_change = dt
        nonlocal is_afk
        is_afk = True

    def change_to_not_afk(dt: datetime):
        """
        This function should be called when user is no longer AFK
        The argument dt should be the time when the at-keyboard indicating activity was detected,
        which should be: change_to_not_afk(dt=now)
        """
        nonlocal last_change
        e = Event(label=["afk"],
                  timestamp=[last_change],
                  duration={
                      "value": (dt - last_change).total_seconds(),
                      "unit": "seconds"
                  })
        client.send_event(bucketname, e)
        logger.info("No longer AFK")
        send_notification("No longer AFK")

        nonlocal is_afk
        is_afk = False
        last_change = dt

    while True:
        # FIXME: Doesn't work if computer is put to sleep since state is unlikely to be
        #        in is_afk when sleep is initiated by the user.
        try:
            sleep(settings["check_interval"])
            now = datetime.now(pytz.utc)
            if mouseListener.has_new_event() or keyboardListener.has_new_event():
                """
                Check if there has been any activity on the mouse or keyboard and if so,
                update last_activity to now and set is_afk to False if previously AFK
                """
                # logger.debug("activity detected")
                mouse_event = mouseListener.next_event()
                keyboard_event = keyboardListener.next_event()

                logger.debug(mouse_event)
                logger.debug(keyboard_event)

                if is_afk:
                    """
                    No longer AFK
                    If AFK, keyboard/mouse activity indicates the user is no longer AFK
                    """
                    change_to_not_afk(now)
                elif now - last_activity > timedelta(seconds=settings["timeout"]):
                    """
                    is_afk=False, but loop has been interrupted so user might actually be afk
                    Took longer than `timeout` since last loop, computer likely put to sleep
                    """
                    change_to_afk(dt=last_activity)
                    change_to_not_afk(dt=now)
                last_activity = now
            if not is_afk:
                # If not previously AFK, check if enough time has passed for user to now be considered AFK
                passed_time = now - last_activity
                passed_afk = passed_time > timedelta(seconds=settings["timeout"])
                if passed_afk:
                    # Now AFK
                    # Store event with the ended non-AFK period
                    change_to_afk(dt=last_activity)

        except KeyboardInterrupt:
            logger.info("afkwatcher stopped by keyboard interrupt")
            break
        except Exception as e:
            logger.warning("afkwatcher stopped by unexpected exception:\n{}".format(str(e)))
            break

