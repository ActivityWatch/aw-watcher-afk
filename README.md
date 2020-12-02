aw-watcher-afk
==============

[![Build Status](https://github.com/ActivityWatch/aw-watcher-afk/workflows/Build/badge.svg)](https://github.com/ActivityWatch/aw-watcher-afk/actions)

Watches your keyboard and mouse activity to determine if you are AFK or not

## How to install

To install the pre-built application, go to https://activitywatch.net/downloads/

To build your own packaged application, run `make package`

To install the latest git version directly from github without cloning, run
`pip install git+https://github.com/ActivityWatch/aw-watcher-afk.git`

To install from a cloned version, cd into the directory and run
`poetry install` to install inside an virtualenv. If you want to install it
system-wide it can be installed with `pip install .`, but that has the issue
that it might not get the exact version of the dependencies due to not reading
the poetry.lock file.
