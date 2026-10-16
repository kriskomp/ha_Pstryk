"""Sell revenue / energy sold / average sell price sensors.

The checks live in sell_sensors_check.py and run in their own process, so their
Home Assistant stand-ins do not mix with the ones the other test modules use.
"""
import subprocess
import sys
from pathlib import Path


def test_sell_sensors():
    script = Path(__file__).with_name("sell_sensors_check.py")
    result = subprocess.run([sys.executable, "-I", str(script)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
