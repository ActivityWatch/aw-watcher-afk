#!/usr/bin/env python

from setuptools import setup, find_packages

setup(name='aw-watcher-afk',
      version='0.1',
      description='AFK watcher for ActivityWatch',
      author='Erik Bjäreholt',
      author_email='erik@bjareho.lt',
      url='https://github.com/ActivityWatch/aw-watcher-afk',
      packages=['aw_watcher_afk'],
      install_requires=[
          'aw-client>=0.2',
          'pyuserinput',
          'pytz',
          'python-xlib'],
      dependency_links=[
          'https://github.com/python-xlib/python-xlib/tarball/master#egg=python-xlib',
          'https://github.com/ActivityWatch/aw-client/tarball/master#egg=aw-client'
      ],
      entry_points={
          'console_scripts': ['aw-watcher-afk = aw_watcher_afk:main']
      })
