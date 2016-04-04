#!/bin/bash

if [ ! -d "logs" ]; then
    mkdir logs
fi

python3 afk.py 2>&1 | tee -a "logs/$(date --iso=seconds).log"
