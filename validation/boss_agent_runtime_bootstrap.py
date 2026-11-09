import runpy
import sys
from pathlib import Path


PACKAGE_DIR = Path(__file__).resolve().parent


def install_path():
    value = str(PACKAGE_DIR)
    if value not in sys.path:
        sys.path.insert(0, value)


def main():
    install_path()
    runpy.run_module("application", run_name="__main__")
