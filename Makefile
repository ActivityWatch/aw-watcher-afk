.PHONY: build

build:
	python3 setup.py install

test:
	python3 -m mypy aw_watcher_afk --ignore-missing-imports
	aw-watcher-afk --help  # Ensures that it at least starts

package:
	pyinstaller aw-watcher-afk.spec --clean --noconfirm

