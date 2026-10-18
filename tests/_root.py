"""Imported first by every suite: makes the repo root the working directory and puts it on sys.path, so a suite's
paths (out/..., firmware/..., host/) and `from emu import` mean what they did when the suites lived at the root.
A suite then runs from anywhere: python3 tests/test_solo.py, or python3 test_solo.py inside tests/."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
