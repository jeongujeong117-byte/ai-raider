"""Compatibility alias: the implementation moved to core/source_manager.py.

`import source_manager` returns the same module object as `core.source_manager`, so existing imports and
monkeypatch targets such as `source_manager.<name>` keep working without a second copy of the code.
"""
import sys

from core import source_manager as _implementation

sys.modules[__name__] = _implementation
