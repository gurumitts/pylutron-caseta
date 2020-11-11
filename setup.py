#!/usr/bin/python
"""Provides an API to the Lutron Caseta Smartbridge."""

from distutils.core import setup

setup(
    name="pylutron_caseta",
    version="0.7.2",
    license="Apache",
    description="""Provides an API to the Lutron Smartbridge""",
    author="gurumitts",
    author_email="",
    maintainer="guumitts",
    maintainer_email="",
    platforms=["Linux"],
    url="https://github.com/gurumitts/pylutron-caseta",
    download_url="https://github.com/gurumitts/pylutron-caseta",
    packages=["pylutron_caseta"],
    install_requires=[],
    python_requires=">=3.7.0",
)
