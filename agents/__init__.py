"""Per-source collection agents.

Importing this package or any agent module never starts a server, thread or collection.
"""


class Cancelled(Exception):
    """Stop requested during Instagram/X collection (re-exported as raider.Cancelled)."""
