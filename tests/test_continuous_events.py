from datetime import timedelta

from aw_client import ActivityWatchClient

client = ActivityWatchClient("aw-watcher-afk", testing=True)
print(client.get_buckets())

events = client.get_events("aw-watcher-afk-testing_erb-laptop-ubuntu")

print("\n\n")

last_event = None
wrong_events = 0
for event in sorted(events, key=lambda e: e.timestamp):
    if last_event:
        # The diff is the gap between the two events, should be zero
        # In reality it is currently sometimes negative and almost always larger than 1s
        diff = (event.timestamp - last_event.timestamp) - last_event.duration

        print("{} at {}".format(event.label, event.timestamp))
        print("Duration: {}".format(event.duration))

        if not timedelta(seconds=1) > abs(diff):
            print("  WARNING: Diff had absolute value of over 1s ({})".format(diff))
            wrong_events += 1

        if last_event.label == event.label:
            print("  WARNING: Two {} events in a row".format(event.label))

        print("")
    last_event = event

print("Percent of wrong events: {}".format(wrong_events / len(events)))