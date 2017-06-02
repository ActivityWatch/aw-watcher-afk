import logging
import argparse

from aw_core.log import setup_logging

from .afk import AFKWatcher

logger = logging.getLogger(__name__)


def main() -> None:
    # Set up argparse
    parser = argparse.ArgumentParser("A watcher for keyboard and mouse input to detect AFK state")
    parser.add_argument("-v", dest='verbose', action="store_true",
                        help='run with verbose logging')
    parser.add_argument("--testing", action="store_true",
                        help='run in testing mode')
    args = parser.parse_args()

    # Set up logging
    setup_logging("aw-watcher-afk",
                  testing=args.testing, verbose=args.verbose,
                  log_stderr=True, log_file=True)

    logger.info("aw-watcher-afk started")

    # Start watcher
    watcher = AFKWatcher(testing=args.testing)
    watcher.run()
