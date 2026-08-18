"""Automatizacion del portal AmeliCA con Playwright."""

from .marker import AmelicaMarker
from .uploader import PORTAL_URL, AmelicaUploader

__all__ = ["AmelicaUploader", "AmelicaMarker", "PORTAL_URL"]
