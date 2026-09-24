"""Jodit FileBrowser and Uploader connector for Python."""

from importlib.metadata import version

from jcpy.app import create_app

__version__ = version("jodit-python")

__all__ = ["__version__", "create_app"]
