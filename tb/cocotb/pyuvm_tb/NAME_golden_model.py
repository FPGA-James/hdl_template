"""Reference model of <<NAME>>_core's counter, used by the pyuvm testbench.

The core adds `increment` to a saturating 16-bit count on every clock edge
while enabled; it holds the value while disabled; reset_count clears it. The
model is cycle-level only: it has no notion of bus latency, so tests apply it
where the counter is *not* running during the bus transaction (disabled), or
compare against bounds when it is.
"""

MAX_COUNT = 65535  # status.pulse_count is 16 bits and saturates


class CounterModel:
    def __init__(self) -> None:
        self.count = 0
        self.enable = False
        self.increment = 1

    def configure(self, enable: bool, increment: int) -> None:
        self.enable = enable
        self.increment = increment

    def tick(self, cycles: int = 1) -> None:
        if self.enable:
            self.count = min(MAX_COUNT, self.count + cycles * self.increment)

    def reset_count(self) -> None:
        self.count = 0

    def status_word(self) -> int:
        """status register value: enabled in bit 0, pulse_count in bits 16:1."""
        return (self.count << 1) | int(self.enable)
