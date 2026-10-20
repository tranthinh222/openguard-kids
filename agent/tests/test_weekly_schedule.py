from datetime import datetime

from test_screen_time import policy


def test_schedule_slot_boundaries():
    current = policy()
    assert current.schedule_slot_at(datetime(2026, 10, 5, 0, 0)) == 0
    assert current.schedule_slot_at(datetime(2026, 10, 5, 0, 29)) == 0
    assert current.schedule_slot_at(datetime(2026, 10, 5, 0, 30)) == 1
    assert current.schedule_slot_at(datetime(2026, 10, 11, 23, 59)) == 335
