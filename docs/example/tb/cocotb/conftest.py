# tb/cocotb/conftest.py
#
# test_uart.py contains @cocotb.test() coroutines that run inside a simulator
# context — they are not standalone pytest functions.  Exclude the file from
# pytest collection so that it is only imported by the simulator via the
# test_runner.py parametrised wrapper.
collect_ignore = ["test_uart.py"]
