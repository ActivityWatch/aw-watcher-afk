import logging
import platform
from datetime import datetime, timedelta, timezone
from time import sleep

from aw_core.models import Event
from aw_client import ActivityWatchClient

from .listeners import KeyboardListener, MouseListener

# TODO: Move to argparse
settings = {
    "timeout": 60,
    "update_interval": 30,
    "check_interval": 1,
}



def main():
    """ Set up argparse """
    import argparse

    parser = argparse.ArgumentParser("A watcher for keyboard and mouse input to detect AFK state")
    parser.add_argument("--testing", action="store_true")
    parser.add_argument("--desktop-notify", action="store_true")

    args = parser.parse_args()

    """ Set up logging """
    logging.basicConfig(
        level=logging.DEBUG if args.testing else logging.INFO,
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
    last_change = now # Last time the state changed
    last_activity = now # Last time of input activity
    last_update = now # Last report time
    last_check = now # Last check/poll time
    
    
    """ State Reporter """
    
    def report_state(afk, duration, update):
        nonlocal last_change, last_update
        label = ["afk"] if afk else ["not-afk"]
        e = Event(label=label,
                  timestamp=[datetime.now(timezone.utc)],
                  duration={
                      "value": duration.total_seconds(),
                      "unit": "seconds"
                  })
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
            sleep(settings["check_interval"])
            last_check = now
            now = datetime.now(timezone.utc)

            new_event = False
            if mouseListener.has_new_event() or keyboardListener.has_new_event():
                new_event = True
                last_activity = now
                # Get events 
                mouse_event = mouseListener.next_event()
                keyboard_event = keyboardListener.next_event()
                # Log
                logger.debug(mouse_event)
                logger.debug(keyboard_event)
          
           
            if now >= last_check + timedelta(seconds=30):
                # Computer has been woken up from a sleep/hibernation
                # (or computer has a 30sec hang, which is unlikely)
                pass
            
            if afk == None:
                """ Initialization """
                afk = False
                # Report
                report_state(afk=False, duration=timedelta(), update=False)

            elif afk and new_event:
                """ No longer AFK """
                afk = False
                # Report
                if last_change:
                    report_state(afk=True, duration=now-last_change, update=True)
                report_state(afk=False, duration=timedelta(), update=False)

            elif not afk and now > last_activity + timedelta(seconds=settings["timeout"]):
                """ Now afk """
                afk = True
                # Report
                if last_change:
                    report_state(afk=False, duration=last_activity-last_change, update=True)
                report_state(afk=True, duration=now-last_activity, update=False)

            elif now > last_update + timedelta(seconds=settings["update_interval"]):
                """ Report state again if it was a long time since last time """
                if afk:
                    # Report AFK state from last activity
                    report_state(afk=True, duration=now-last_change, update=True)
                else:
                    # Updated not-afk state from last activity
                    report_state(afk=False, duration=now-last_change, update=True)
            

        except KeyboardInterrupt:
            logger.info("afkwatcher stopped by keyboard interrupt")
            break
        except Exception as e:
            logger.warning("afkwatcher stopped by unexpected exception:\n{}".format(str(e)))
            break

