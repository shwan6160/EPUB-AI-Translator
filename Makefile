APP_NAME = erst
INSTALL_DIR = $(HOME)/.local/share/$(APP_NAME)
BIN_DIR = $(HOME)/.local/bin
VENV_DIR = $(INSTALL_DIR)/.venv

.PHONY: install uninstall

reinstall: uninstall install

install:
	@echo "Installing $(APP_NAME)..."
	mkdir -p $(INSTALL_DIR)
	mkdir -p $(BIN_DIR)

	cp -r . $(INSTALL_DIR)

	python3 -m venv $(VENV_DIR)
	$(VENV_DIR)/bin/pip install --upgrade pip
	$(VENV_DIR)/bin/pip install -r $(INSTALL_DIR)/requirements.txt

	@echo '#!/bin/bash' > $(BIN_DIR)/$(APP_NAME)
	@echo 'exec "$(VENV_DIR)/bin/python" "$(INSTALL_DIR)/main.py" "$$@"' >> $(BIN_DIR)/$(APP_NAME)
	@chmod +x $(BIN_DIR)/$(APP_NAME)

	@echo "Install complete! Make sure $(BIN_DIR) is in your PATH."

uninstall:
	@echo "Uninstalling $(APP_NAME)..."
	rm -f $(BIN_DIR)/$(APP_NAME)
	rm -rf $(INSTALL_DIR)
	@echo "Uninstall complete."
