"""Compatibility alias: the implementation moved to core/media_store.py.

`import media_store` returns the same module object as `core.media_store`, so existing imports and
monkeypatch targets such as `media_store.<name>` keep working without a second copy of the code.
"""
import sys

from core import media_store as _implementation

sys.modules[__name__] = _implementation
