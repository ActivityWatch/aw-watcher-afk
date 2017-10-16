.PHONY: build test package clean

pip_install_args := . -r requirements.txt --upgrade

ifdef DEV
pip_install_args := --editable $(pip_install_args)
endif

build:
	pip3 install $(pip_install_args)

test:
	python3 -m mypy aw_watcher_afk --ignore-missing-imports
	aw-watcher-afk --help  # Ensures that it at least starts

package:
	pyinstaller aw-watcher-afk.spec --clean --noconfirm

clean:
	rm -rf build dist
	rm -rf aw_watcher_afk/__pycache__
