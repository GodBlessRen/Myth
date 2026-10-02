"""Stable Myth core vocabulary.

The core records durable intent and facts.  It deliberately does not prescribe
how intelligence is organized.
"""

from .primitives import Goal, GoalState

__all__ = ["Goal", "GoalState"]
