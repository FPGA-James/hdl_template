"""Pure-Python unit test for the counter's reference model."""

from pyuvm_tb.<<NAME>>_golden_model import CounterModel, MAX_COUNT


def test_disabled_counter_holds_zero():
    m = CounterModel()
    m.tick(10)
    assert m.count == 0


def test_enabled_counter_adds_increment_per_cycle():
    m = CounterModel()
    m.configure(enable=True, increment=5)
    m.tick(3)
    assert m.count == 15


def test_count_saturates_at_max():
    m = CounterModel()
    m.configure(enable=True, increment=255)
    m.tick(1000)
    assert m.count == MAX_COUNT == 65535


def test_reset_count_clears_and_counter_holds_when_disabled():
    m = CounterModel()
    m.configure(enable=True, increment=2)
    m.tick(4)
    m.configure(enable=False, increment=2)
    m.tick(4)
    assert m.count == 8
    m.reset_count()
    assert m.count == 0


def test_status_word_packs_enabled_and_count():
    m = CounterModel()
    m.configure(enable=True, increment=1)
    m.tick(2)
    assert m.status_word() == (2 << 1) | 1
