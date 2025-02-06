.PHONY: build test package clean

POETRY_EXTRAS =

ifeq ($(USE_EVDEV),true)
	POETRY_EXTRAS := $(POETRY_EXTRAS) use_evdev
endif

build:
	poetry install --extras "$(POETRY_EXTRAS)"

test:
	poetry run aw-watcher-afk --help  # Ensures that it at least starts
	make typecheck

typecheck:
	poetry run mypy aw_watcher_afk --ignore-missing-imports

package:
	pyinstaller aw-watcher-afk.spec --clean --noconfirm

clean:
	rm -rf build dist
	rm -rf aw_watcher_afk/__pycache__
