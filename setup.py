#!/usr/bin/env python

from setuptools import setup, find_packages

setup(name='actwa-watcher-afk',
      version='0.1',
      description='AFK watcher for ActivityWatch',
      author='Erik Bjäreholt',
      author_email='erik@bjareho.lt',
      url='https://github.com/ActivityWatch/actwa-watcher-afk',
      namespace_packages=['actwa', 'actwa.watchers'],
      packages=['actwa.watchers.afk'],
      install_requires=['actwa-client', 'pyuserinput'],
      entry_points={
            'console_scripts': ['actwa-watcher-afk = actwa.watchers.afk:main']
        }
     )
