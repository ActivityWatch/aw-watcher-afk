.PHONY: build test package clean

build:
	poetry install

test:
	aw-watcher-afk --help  # Ensures that it at least starts
	make typecheck

typecheck:
	python -m mypy aw_watcher_afk --ignore-missing-imports

package:
	pyinstaller aw-watcher-afk.spec --clean --noconfirm

clean:
	rm -rf build dist
	rm -rf aw_watcher_afk/__pycache__
