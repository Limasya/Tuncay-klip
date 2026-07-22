"""
Zero-Bandwidth Clip Engine — Internal Config
─────────────────────────────────────────────
Configuration constants that must be importable without circular dependencies.
"""
import os

CHANNEL: str = os.environ.get("ZERO_BANDWIDTH_CHANNEL", "thetuncay")
