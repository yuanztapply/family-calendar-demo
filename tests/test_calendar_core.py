from datetime import date, datetime, timezone
from pathlib import Path
import unittest

from calendar_core import Event, Slot, hour_slots, is_busy, parse_ics

UTC = timezone.utc


def calendar(body):
    return f"BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VEVENT\n{body}\nEND:VEVENT\nEND:VCALENDAR\n".encode()


class CalendarTests(unittest.TestCase):
    def test_demo_only_has_two_fictional_events(self):
        data = (Path(__file__).parent.parent / "demo-fictional.ics").read_bytes()
        events, warnings = parse_ics(data, "UTC")
        self.assertEqual(len(events), 2)
        self.assertFalse(warnings)
        self.assertTrue(all("FICTIONAL" in event.title for event in events))

    def test_daylight_saving_actual_day_lengths(self):
        self.assertEqual(len(hour_slots(date(2030, 3, 31), "Europe/Berlin")), 23)
        self.assertEqual(len(hour_slots(date(2030, 10, 27), "Europe/Berlin")), 25)
        self.assertEqual(len({slot.key for slot in hour_slots(date(2030, 10, 27), "Europe/Berlin")}), 25)

    def test_half_open_boundaries_and_cross_midnight(self):
        events, warnings = parse_ics(calendar("DTSTART:20300407T233000Z\nDTEND:20300408T010000Z"), "UTC")
        self.assertFalse(warnings)
        slots = hour_slots(date(2030, 4, 8), "UTC")
        self.assertTrue(is_busy(events, slots[0]))
        self.assertFalse(is_busy(events, slots[1]))

    def test_all_day_end_is_exclusive(self):
        events, warnings = parse_ics(calendar("DTSTART;VALUE=DATE:20300408\nDTEND;VALUE=DATE:20300409"), "UTC")
        self.assertFalse(warnings)
        self.assertTrue(all(is_busy(events, slot) for slot in hour_slots(date(2030, 4, 8), "UTC")))
        self.assertFalse(any(is_busy(events, slot) for slot in hour_slots(date(2030, 4, 9), "UTC")))

    def test_iana_timezone_and_folded_title(self):
        events, warnings = parse_ics(calendar("DTSTART;TZID=Asia/Tokyo:20300408T090000\nDTEND;TZID=Asia/Tokyo:20300408T100000\nSUMMARY:FICTIONAL\\, long\n  title"), "UTC")
        self.assertFalse(warnings)
        self.assertEqual(events[0].start.hour, 0)
        self.assertEqual(events[0].title, "FICTIONAL, long title")

    def test_unsupported_recurrence_is_reported(self):
        events, warnings = parse_ics(calendar("DTSTART:20300408T090000Z\nDTEND:20300408T100000Z\nRRULE:FREQ=DAILY"), "UTC")
        self.assertFalse(events)
        self.assertEqual(len(warnings), 1)

    def test_transparent_event_does_not_block_time(self):
        events, warnings = parse_ics(calendar("DTSTART:20300408T090000Z\nDTEND:20300408T100000Z\nTRANSP:TRANSPARENT"), "UTC")
        self.assertEqual((events, warnings), ([], []))

    def test_ambiguous_local_time_requires_explicit_utc(self):
        events, warnings = parse_ics(calendar("DTSTART;TZID=Europe/Berlin:20301027T023000\nDTEND;TZID=Europe/Berlin:20301027T033000"), "UTC")
        self.assertFalse(events)
        self.assertEqual(len(warnings), 1)

    def test_manual_busy_takes_priority(self):
        slot = hour_slots(date(2030, 4, 8), "UTC")[0]
        self.assertTrue(is_busy([], slot, [slot.key], [slot.key]))
        event = Event(slot.start, slot.end, "FICTIONAL")
        self.assertFalse(is_busy([event], slot, [], [slot.key]))

    def test_timed_duration_uses_elapsed_hours_at_dst(self):
        events, warnings = parse_ics(calendar("DTSTART;TZID=Europe/Berlin:20300331T013000\nDURATION:PT1H"), "UTC")
        self.assertFalse(warnings)
        self.assertEqual((events[0].end - events[0].start).total_seconds(), 3600)

    def test_unknown_timezone_is_reported(self):
        events, warnings = parse_ics(calendar("DTSTART;TZID=Unknown/Example:20300408T090000\nDTEND;TZID=Unknown/Example:20300408T100000"), "UTC")
        self.assertFalse(events)
        self.assertEqual(len(warnings), 1)

    def test_alarm_does_not_replace_event_summary(self):
        events, warnings = parse_ics(calendar("DTSTART:20300408T090000Z\nDTEND:20300408T100000Z\nSUMMARY:FICTIONAL event\nBEGIN:VALARM\nSUMMARY:Alarm text\nTRIGGER:-PT5M\nEND:VALARM"), "UTC")
        self.assertFalse(warnings)
        self.assertEqual(events[0].title, "FICTIONAL event")

    def test_unsupported_busy_component_is_reported(self):
        data = b"BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VFREEBUSY\nFREEBUSY:20300408T090000Z/20300408T110000Z\nEND:VFREEBUSY\nEND:VCALENDAR\n"
        events, warnings = parse_ics(data, "UTC")
        self.assertFalse(events)
        self.assertEqual(len(warnings), 1)

    def test_embedded_timezone_is_explicitly_flagged(self):
        data = b"BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VTIMEZONE\nTZID:Europe/Berlin\nEND:VTIMEZONE\nEND:VCALENDAR\n"
        events, warnings = parse_ics(data, "UTC")
        self.assertFalse(events)
        self.assertEqual(len(warnings), 1)



if __name__ == "__main__":
    unittest.main()
