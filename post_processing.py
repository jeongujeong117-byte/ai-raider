"""Compatibility alias: the implementation moved to core/post_processing.py.

`import post_processing` returns the same module object as `core.post_processing`, so existing imports and
monkeypatch targets such as `post_processing.<name>` keep working without a second copy of the code.
"""
import sys

from core import post_processing as _implementation

sys.modules[__name__] = _implementation
