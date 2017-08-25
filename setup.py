#!/usr/bin/env python

from setuptools import setup

# [No longer needed] Additional windows deps:
# - PyHook (http://www.lfd.uci.edu/~gohlke/pythonlibs/#pyhook)
# - pywin32 (`pip install pypiwin32`)

setup(name='aw-watcher-afk',
      version='0.2',
      description='AFK watcher for ActivityWatch',
      author='Erik Bjäreholt',
      author_email='erik@bjareho.lt',
      url='https://github.com/ActivityWatch/aw-watcher-afk',
      packages=['aw_watcher_afk'],
      entry_points={
          'console_scripts': ['aw-watcher-afk = aw_watcher_afk:main']
      },
      classifiers=[
          'Programming Language :: Python :: 3'
      ])
