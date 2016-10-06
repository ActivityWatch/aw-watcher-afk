#!/bin/bash

env MYPYPATH="../aw-core/stubs/:../aw-core/:../aw-client/" python3 -m mypy --silent-imports aw_watcher_afk
exit $?
