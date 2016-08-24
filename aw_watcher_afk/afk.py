import logging
import platform
from datetime import datetime, timedelta, timezone
from time import sleep

from aw_core.models import Event
from aw_client import ActivityWatchClient

from .listeners import KeyboardListener, MouseListener

# TODO: Move to argparse
settings = {
    "timeout": 180,
    "update_interval": 30,
    "check_interval": 5,
}


def main():
    """ Set up argparse """
    import argparse

    parser = argparse.ArgumentParser("A watcher for keyboard and mouse input to detect AFK state")
    parser.add_argument("-v", dest='verbose', action="store_true",
                        help='run with verbose logging')
    parser.add_argument("--testing", action="store_true",
                        help='run in testing mode (also enforces verbose logging)')
    parser.add_argument("--desktop-notify", action="store_true",
                        help='sends desktop notifications when you become afk/non-afk')

    args = parser.parse_args()

    """ Set up logging """
    logging.basicConfig(
        level=logging.DEBUG if args.testing or args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
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
    last_change = now  # Last time the state changed
    last_activity = now  # Last time of input activity
    previous_activity = now  # Last time of input activity prior to the current one
    last_update = now  # Last report time
    last_check = now  # Last check/poll time

    """
    State Reporter
    """

    def report_state(afk, duration, timestamp=None, update=False):
        nonlocal last_change, last_update
        try:
            assert duration >= timedelta()
        except:
            logger.warning("Duration was negative: {}s".format(duration.total_seconds()))
        label = "afk" if afk else "not-afk"
        e = Event(label=label,
                  timestamp=(last_change if update else now) if not timestamp else timestamp,
                  duration=duration)
        last_update = now
        if update:
            client.replace_last_event(bucketname, e)
        else:
            last_change = now
            client.send_event(bucketname, e)
            msg = "You are now AFK" if afk else "You are no longer AFK"
            logger.info(msg)
            send_notification(msg)

    """
    Run Watcher
    """

    logger.info("afkwatcher started")

    while True:
        try:
            last_check = now  # Might as well be put at the end of the loop, but it's more visible here.
            sleep(settings["check_interval"])
            now = datetime.now(timezone.utc)

            new_event = False
            if mouseListener.has_new_event() or keyboardListener.has_new_event():
                # logger.debug("New event")
                new_event = True
                previous_activity = last_activity
                last_activity = now
                # Get/clear events
                mouse_event = mouseListener.next_event()
                keyboard_event = keyboardListener.next_event()

            if afk is None:
                """ Initialization """
                afk = not new_event
                # Report
                report_state(afk=afk, duration=timedelta())

            if now >= last_check + timedelta(seconds=settings["timeout"]):
                # Computer has been woken up from a sleep/hibernation
                # (or computer has a hang longer than the timeout, which is unlikely)
                logger.debug(20 * "-")
                logger.debug("Hibernation/sleep/stalling detected")
                # Report
                if last_change:
                    if afk:
                        report_state(afk=True, duration=now - previous_activity, update=True)
                    else:
                        report_state(afk=True, duration=now - previous_activity, timestamp=previous_activity)
                report_state(afk=False, duration=timedelta())
                # NOTE: Kind of iffy. Gives incorrect behavior in case of stall, but it's the easiest solution we found to an annoying problem.
                last_activity = now
                afk = False

            elif afk and new_event:
                """ No longer AFK """
                logger.debug(20 * "-")
                logger.debug("Became non-AFK")
                afk = False
                # Report
                if last_change:
                    report_state(afk=True, duration=now - previous_activity, timestamp=previous_activity, update=True)
                report_state(afk=False, duration=timedelta(), update=False)

            elif not afk and now > last_activity + timedelta(seconds=settings["timeout"]):
                """ Now afk """
                logger.debug(20 * "-")
                logger.debug("Became AFK")
                afk = True
                # Report
                if last_change:
                    report_state(afk=False, duration=last_activity - last_change, update=True)
                report_state(afk=True, duration=now - last_activity, timestamp=last_activity, update=False)

            elif now > last_update + timedelta(seconds=settings["update_interval"]):
                """ Report state again if it was a long time since last time """
                logger.debug(20 * "-")
                logger.debug("Updating last event")
                if afk:
                    # Report AFK state from last activity
                    report_state(afk=True, duration=now - last_change, update=True)
                else:
                    # Updated not-afk state from last activity
                    report_state(afk=False, duration=now - last_change, update=True)
        except KeyboardInterrupt:
            logger.info("afkwatcher stopped by keyboard interrupt")
            break
        except Exception as e:
            logger.warning("afkwatcher stopped by unexpected exception:\n{}".format(str(e)))
            break
