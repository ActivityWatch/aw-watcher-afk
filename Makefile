.PHONY: build test package clean

pip_install_args := . -r requirements.txt

ifdef DEV
pip_install_args += --editable
endif

build:
	pip3 install $(pip_install_args)

test:
	aw-watcher-afk --help  # Ensures that it at least starts

typecheck:
	python3 -m mypy aw_watcher_afk --ignore-missing-imports

package:
	pyinstaller aw-watcher-afk.spec --clean --noconfirm

clean:
	rm -rf build dist
	rm -rf aw_watcher_afk/__pycache__
