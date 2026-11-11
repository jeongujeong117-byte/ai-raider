"""Compatibility alias: the implementation moved to agents/github_agent.py.

`import github_agent` returns the same module object as `agents.github_agent`, so existing imports and
monkeypatch targets such as `github_agent.<name>` keep working without a second copy of the code.
"""
import sys

from agents import github_agent as _implementation

sys.modules[__name__] = _implementation
