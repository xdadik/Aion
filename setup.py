#!/usr/bin/env python3
"""Minimal setup.py for fallback installation."""
from setuptools import setup, find_packages

setup(
    name="aion-hand",
    version="0.4.0",
    description="A modular, extensible AI agent framework with tool-use, memory, orchestration, and messaging integrations.",
    author="Aion Hand Contributors",
    license="MIT",
    python_requires=">=3.11",
    packages=find_packages(),
    extras_require={
        "messaging": ["aiohttp>=3.9"],
        "web": ["aiohttp>=3.9", "rich>=13.0"],
        "tui": ["rich>=13.0"],
        "all": ["aiohttp>=3.9", "rich>=13.0"],
        "dev": [
            "pytest>=8.0",
            "pytest-asyncio>=0.23",
            "pytest-cov>=5.0",
            "black>=24.0",
            "ruff>=0.4",
            "mypy>=1.10",
        ],
    },
    entry_points={
        "console_scripts": [
            "aion-hand=aion_hand_cli.cli:main",
        ],
    },
)
