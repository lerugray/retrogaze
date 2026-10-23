"""
Retrogaze — NES-era pixel art constraint validator and corrector.

The primary entry point is :func:`enforce_constraints`, which runs the full
pipeline (grid alignment, palette remapping, tile color reduction, and metadata
generation) on any input image.
"""

from .enforce import enforce_constraints

__all__ = ["enforce_constraints"]
__version__ = "0.1.0"
