.PHONY: build test package clean

ifdef DEV
install_cmd := poetry install
else
install_cmd := pip3 install .
endif

build:
	$(install_cmd)

test:
	aw-watcher-afk --help  # Ensures that it at least starts

typecheck:
	python3 -m mypy aw_watcher_afk --ignore-missing-imports

package:
	pyinstaller aw-watcher-afk.spec --clean --noconfirm

clean:
	rm -rf build dist
	rm -rf aw_watcher_afk/__pycache__
