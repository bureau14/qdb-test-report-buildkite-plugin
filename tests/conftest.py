import sys
import os

# Add lib and tools to sys.path
root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
lib_path = os.path.join(root, "lib")
tools_path = os.path.join(root, "tools")

if lib_path not in sys.path:
    sys.path.insert(0, lib_path)
if tools_path not in sys.path:
    sys.path.insert(0, tools_path)
