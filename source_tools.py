"""Compatibility alias: the implementation moved to core/source_tools.py.

`import source_tools` returns the same module object as `core.source_tools`, so existing imports and
monkeypatch targets such as `source_tools.<name>` keep working without a second copy of the code.
"""
import sys

from core import source_tools as _implementation

sys.modules[__name__] = _implementation
