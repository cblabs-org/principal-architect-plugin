PLUGIN_NAME := pa-daemon
DIST_DIR    := dist

RAW_VERSION := $(shell git describe --tags --always --dirty 2>/dev/null || echo "0.1.0")
VERSION     ?= $(shell echo "$(RAW_VERSION)" | sed -E 's/^v//')

.PHONY: all install uninstall dist-zip test lint clean

all: dist-zip

# Install or upgrade `pa-daemon` in-place into ~/.gemini/config/plugins/pa-daemon and link ~/.local/bin/pa
install:
	VERSION="$(VERSION)" ./scripts/install.sh

# Remove `pa-daemon` and ~/.local/bin/pa symlink
uninstall:
	./scripts/uninstall.sh

# Build self-contained, ready-to-unzip universal plugin bundle (`dist/pa-daemon.zip` & `dist/pa-daemon-v<VERSION>.zip`)
dist-zip:
	@rm -rf $(DIST_DIR)
	@mkdir -p $(DIST_DIR)/stage/$(PLUGIN_NAME)
	@PA_DAEMON_HOME="$(CURDIR)/$(DIST_DIR)/stage/$(PLUGIN_NAME)" \
		PA_BIN_DIR="$(CURDIR)/$(DIST_DIR)/stage-bin" \
		VERSION="$(VERSION)" \
		./scripts/install.sh >/dev/null
	@rm -rf "$(DIST_DIR)/stage/$(PLUGIN_NAME)/state" "$(DIST_DIR)/stage-bin"
	@find "$(DIST_DIR)/stage/$(PLUGIN_NAME)" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
	@python3 -c 'import os, pathlib, sys, zipfile; stage = pathlib.Path(sys.argv[1]); out = pathlib.Path(sys.argv[2]); zf = zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED); [zf.write(p, p.relative_to(stage)) for p in sorted(stage.rglob("*"))]; zf.close()' "$(DIST_DIR)/stage" "$(DIST_DIR)/$(PLUGIN_NAME).zip"
	@cp "$(DIST_DIR)/$(PLUGIN_NAME).zip" "$(DIST_DIR)/$(PLUGIN_NAME)-v$(VERSION).zip"
	@rm -rf "$(DIST_DIR)/stage"
	@echo "Created $(DIST_DIR)/$(PLUGIN_NAME).zip and $(DIST_DIR)/$(PLUGIN_NAME)-v$(VERSION).zip (version $(VERSION))"

test:
	@if [ -x .venv/bin/pytest ]; then .venv/bin/pytest; else pytest; fi

lint:
	@if [ -x .venv/bin/ruff ]; then .venv/bin/ruff check .; else ruff check .; fi

clean:
	rm -rf $(DIST_DIR)
