# Berlin Flat Bot - Rust Version Makefile

# Variables
BINARY_NAME=berlin-flat-bot
INSTALL_PATH=/opt/berlin-flat-bot
SERVICE_USER=flatbot
SERVICE_FILE=berlin-flat-bot.service

# Default target
.PHONY: all
all: build

# Development build
.PHONY: build
build:
	cargo build

# Production build (optimized)
.PHONY: release
release:
	cargo build --release

# Run tests
.PHONY: test
test:
	cargo test

# Run with logging
.PHONY: run
run:
	RUST_LOG=berlin_flat_bot=info cargo run

# Run in debug mode
.PHONY: debug
debug:
	RUST_LOG=debug cargo run

# Format code
.PHONY: fmt
fmt:
	cargo fmt

# Lint code
.PHONY: lint
lint:
	cargo clippy -- -D warnings

# Check all (format, lint, test)
.PHONY: check
check: fmt lint test

# Clean build artifacts
.PHONY: clean
clean:
	cargo clean

# Install as system service
.PHONY: install
install: release
	@echo "Installing Berlin Flat Bot as system service..."
	
	# Create service user if it doesn't exist
	@if ! id $(SERVICE_USER) &>/dev/null; then \
		sudo useradd -r -s /bin/false -d $(INSTALL_PATH) $(SERVICE_USER); \
		echo "Created service user: $(SERVICE_USER)"; \
	fi
	
	# Create install directory
	sudo mkdir -p $(INSTALL_PATH)
	
	# Copy binary and config
	sudo cp target/release/$(BINARY_NAME) $(INSTALL_PATH)/
	@if [ -f config.json ]; then \
		sudo cp config.json $(INSTALL_PATH)/; \
	else \
		echo "Warning: config.json not found. You'll need to create one manually."; \
	fi
	
	# Set ownership and permissions
	sudo chown -R $(SERVICE_USER):$(SERVICE_USER) $(INSTALL_PATH)
	sudo chmod +x $(INSTALL_PATH)/$(BINARY_NAME)
	
	# Install systemd service
	sudo cp $(SERVICE_FILE) /etc/systemd/system/
	sudo systemctl daemon-reload
	sudo systemctl enable $(BINARY_NAME)
	
	@echo "Installation complete!"
	@echo "Start with: sudo systemctl start $(BINARY_NAME)"
	@echo "Check logs: sudo journalctl -u $(BINARY_NAME) -f"

# Uninstall system service
.PHONY: uninstall
uninstall:
	@echo "Uninstalling Berlin Flat Bot..."
	
	# Stop and disable service
	-sudo systemctl stop $(BINARY_NAME)
	-sudo systemctl disable $(BINARY_NAME)
	
	# Remove service file
	-sudo rm -f /etc/systemd/system/$(SERVICE_FILE)
	sudo systemctl daemon-reload
	
	# Remove installation directory
	-sudo rm -rf $(INSTALL_PATH)
	
	# Remove service user (optional)
	@echo "Service user '$(SERVICE_USER)' left intact. Remove manually if needed:"
	@echo "sudo userdel $(SERVICE_USER)"
	
	@echo "Uninstallation complete!"

# Start service
.PHONY: start
start:
	sudo systemctl start $(BINARY_NAME)

# Stop service
.PHONY: stop
stop:
	sudo systemctl stop $(BINARY_NAME)

# Restart service
.PHONY: restart
restart:
	sudo systemctl restart $(BINARY_NAME)

# Show service status
.PHONY: status
status:
	sudo systemctl status $(BINARY_NAME)

# Show service logs
.PHONY: logs
logs:
	sudo journalctl -u $(BINARY_NAME) -f

# Update service (rebuild and restart)
.PHONY: update
update: release
	sudo systemctl stop $(BINARY_NAME)
	sudo cp target/release/$(BINARY_NAME) $(INSTALL_PATH)/
	sudo chown $(SERVICE_USER):$(SERVICE_USER) $(INSTALL_PATH)/$(BINARY_NAME)
	sudo chmod +x $(INSTALL_PATH)/$(BINARY_NAME)
	sudo systemctl start $(BINARY_NAME)
	@echo "Service updated and restarted!"

# Cross-compile for different targets
.PHONY: cross-arm64
cross-arm64:
	rustup target add aarch64-unknown-linux-gnu
	cargo build --release --target aarch64-unknown-linux-gnu

.PHONY: cross-x86
cross-x86:
	rustup target add x86_64-unknown-linux-gnu  
	cargo build --release --target x86_64-unknown-linux-gnu

# Docker build
.PHONY: docker
docker:
	docker build -t berlin-flat-bot .

# Generate documentation
.PHONY: docs
docs:
	cargo doc --open

# Benchmark (if criterion is added to dev-dependencies)
.PHONY: bench
bench:
	cargo bench

# Security audit
.PHONY: audit
audit:
	cargo audit

# Performance profile with flamegraph
.PHONY: profile
profile:
	cargo flamegraph --bin $(BINARY_NAME)

# Memory profiling with valgrind
.PHONY: memcheck
memcheck: release
	valgrind --tool=memcheck --leak-check=full ./target/release/$(BINARY_NAME)

# Development setup
.PHONY: dev-setup
dev-setup:
	# Install useful development tools
	cargo install cargo-audit cargo-flamegraph
	rustup component add clippy rustfmt

# Help
.PHONY: help
help:
	@echo "Berlin Flat Bot - Available Make Targets:"
	@echo ""
	@echo "Development:"
	@echo "  build      - Build debug version"
	@echo "  release    - Build optimized release version"
	@echo "  test       - Run tests"
	@echo "  run        - Run with info logging"
	@echo "  debug      - Run with debug logging"
	@echo "  check      - Format, lint, and test"
	@echo "  clean      - Clean build artifacts"
	@echo ""
	@echo "System Service:"
	@echo "  install    - Install as systemd service"
	@echo "  uninstall  - Remove systemd service"
	@echo "  start      - Start service"
	@echo "  stop       - Stop service"
	@echo "  restart    - Restart service"
	@echo "  status     - Show service status"
	@echo "  logs       - Show service logs (real-time)"
	@echo "  update     - Rebuild and restart service"
	@echo ""
	@echo "Cross-compilation:"
	@echo "  cross-arm64 - Build for ARM64 (Raspberry Pi)"
	@echo "  cross-x86   - Build for x86_64 Linux"
	@echo ""
	@echo "Development Tools:"
	@echo "  docs       - Generate and open documentation"
	@echo "  audit      - Security audit"
	@echo "  profile    - CPU profiling with flamegraph"
	@echo "  memcheck   - Memory profiling with valgrind"
	@echo "  dev-setup  - Install development tools"