"""Penguin AI Assistant package initialisation.

Exposes the :class:`~penguin.core.PenguinCore` class and package configuration
through :mod:`penguin.config` for convenience when importing ``penguin``.
"""
import os
import sys

# Add package directory to Python path
package_dir = os.path.dirname(os.path.abspath(__file__))
if package_dir not in sys.path:
    sys.path.insert(0, package_dir)

from .core import PenguinCore
from .config import config

__version__ = "0.1.0"
__all__ = ["PenguinCore", "config"]
