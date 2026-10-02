"""Myth platform skeleton.

The platform package is intentionally broad and mostly pure.  It names the
future product/runtime layers now so later work deepens stable seams instead of
inventing parallel subsystems.  "planned" never means executable.
"""

from .kernel import MythKernel
from .contracts import LayerState, PlatformLayer

__all__ = ["MythKernel", "LayerState", "PlatformLayer"]
