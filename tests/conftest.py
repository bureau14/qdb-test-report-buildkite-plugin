import os
import sys

import pytest

# Add lib and tools to sys.path
root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
lib_path = os.path.join(root, "lib")
tools_path = os.path.join(root, "tools")

if lib_path not in sys.path:
    sys.path.insert(0, lib_path)
if tools_path not in sys.path:
    sys.path.insert(0, tools_path)


@pytest.fixture(autouse=True)
def reset_report_logging():
    from report_logging import configure_logging, logger

    previous_level = logger.level
    configure_logging()
    yield
    logger.setLevel(previous_level)
