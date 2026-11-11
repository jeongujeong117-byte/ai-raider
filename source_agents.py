"""Compatibility alias: the implementation moved to agents/source_agents.py.
Per-source extractors live in agents/*_agent.py and are re-exported by that module.

`import source_agents` returns the same module object as `agents.source_agents`, so existing imports and
monkeypatch targets such as `source_agents.<name>` keep working without a second copy of the code.
"""
import sys

from agents import source_agents as _implementation

sys.modules[__name__] = _implementation
