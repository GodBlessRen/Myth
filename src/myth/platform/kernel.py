"""Compatibility shim for v0.6-v0.8 imports.

New code should import MythComponents from myth.platform.
"""

from .components import ADAPTERS, CORE, DOMAINS, MythComponents

MythKernel = MythComponents

__all__ = ["ADAPTERS", "CORE", "DOMAINS", "MythComponents", "MythKernel"]
