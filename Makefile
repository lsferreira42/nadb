.PHONY: clean test test-fs test-redis test-backends test-advanced test-all test-core test-quick test-debug test-file test-cov test-strict test-examples test-comprehensive lint quality-check build dist upload upload-test all help dev-install install-redis dev-setup

# Default target when just running 'make'
all: test build

# Help command that lists all available targets
help:
	@echo "NADB Makefile"
	@echo "Available targets:"
	@echo "  clean       - Remove build artifacts and cache files"
	@echo "  test        - Run basic filesystem tests (default)"
	@echo "  test-fs     - Run file system backend tests only"
	@echo "  test-redis  - Run Redis backend tests only"
	@echo "  test-backends - Run storage backends tests only"
	@echo "  test-advanced - Run advanced features tests only"
	@echo "  test-all    - Run all tests for all backends and features"
	@echo "  test-core   - Run core tests (filesystem + advanced features)"
	@echo "  test-quick  - Run tests without slow tests"
	@echo "  test-debug  - Run tests with verbose output, stop on first failure"
	@echo "  test-file   - Run specific test file (usage: make test-file FILE=test_name.py)"
	@echo "  test-cov    - Run tests with coverage report"
	@echo "  test-strict - Run tests with strict warnings (fail on warnings)"
	@echo "  test-examples - Test all examples to ensure they work"
	@echo "  test-comprehensive - Run all tests + examples"
	@echo "  lint        - Run linting tools"
	@echo "  quality-check - Run linting + strict tests"
	@echo "  build       - Build the package"
	@echo "  dist        - Create source and wheel distributions"
	@echo "  upload      - Upload package to PyPI"
	@echo "  upload-test - Upload package to TestPyPI"
	@echo "  dev-install - Install package in development mode"
	@echo "  install-redis - Install package with Redis support"
	@echo "  all         - Run tests and build the package"

# Clean up build artifacts and cache directories
clean:
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	rm -rf __pycache__/
	rm -rf .pytest_cache/
	rm -rf .coverage
	rm -rf htmlcov/
	rm -rf data/
	find . -name '*.pyc' -delete
	find . -name '__pycache__' -delete

# Install the package in development mode
dev-install:
	pip install -e .

# Install the package with Redis support
install-redis:
	pip install -e ".[redis]"

# Run filesystem tests only (default test suite)
test: test-fs

# Run filesystem tests specifically
test-fs: dev-install
	PYTHONPATH=. pytest -v nakv_tests_fs.py

# Run Redis tests specifically
test-redis: install-redis
	@echo "Redis must be running on localhost:6379 for these tests"
	PYTHONPATH=. pytest -v nakv_tests_redis.py

# Run storage backends tests specifically
test-backends: install-redis
	@echo "Redis must be running on localhost:6379 for these tests"
	PYTHONPATH=. pytest -v nakv_tests_storage_backends.py

# Run advanced features tests specifically
test-advanced: install-redis
	@echo "Redis must be running on localhost:6379 for these tests"
	PYTHONPATH=. pytest -v test_advanced_features.py

# Run all tests for all backends and features
test-all: install-redis
	@echo "Redis must be running on localhost:6379 for these tests"
	PYTHONPATH=. pytest -v nakv_tests_fs.py nakv_tests_redis.py nakv_tests_storage_backends.py test_advanced_features.py

# Run tests without slow tests (marked with @pytest.mark.slow)
test-quick: dev-install
	PYTHONPATH=. pytest -v nakv_tests_fs.py -k "not slow"

# Run only core functionality tests (filesystem + advanced features)
test-core: install-redis
	PYTHONPATH=. pytest -v nakv_tests_fs.py test_advanced_features.py

# Run tests with verbose output and stop on first failure
test-debug: install-redis
	@echo "Redis must be running on localhost:6379 for these tests"
	PYTHONPATH=. pytest -v -x nakv_tests_fs.py nakv_tests_redis.py nakv_tests_storage_backends.py test_advanced_features.py

# Run specific test file (usage: make test-file FILE=test_advanced_features.py)
test-file: install-redis
	@echo "Running tests for $(FILE)"
	PYTHONPATH=. pytest -v $(FILE)

# Run tests with coverage report
test-cov: 
	pip install -e ".[redis,dev]"
	@echo "Redis must be running on localhost:6379 for these tests"
	PYTHONPATH=. pytest --cov=. nakv_tests_fs.py nakv_tests_redis.py nakv_tests_storage_backends.py test_advanced_features.py --cov-report=term --cov-report=html
	@echo "HTML coverage report generated in htmlcov/"

# Run tests with strict warnings (fail on warnings)
test-strict: install-redis
	@echo "Redis must be running on localhost:6379 for these tests"
	@echo "Running tests with strict warnings (will fail on any warnings)"
	PYTHONPATH=. pytest -v --tb=short nakv_tests_fs.py nakv_tests_redis.py nakv_tests_storage_backends.py test_advanced_features.py

# Run linting tools
lint:
	@echo "Running linting tools..."
	pylint nakv.py transaction.py backup_manager.py index_manager.py logging_config.py || true
	flake8 nakv.py transaction.py backup_manager.py index_manager.py logging_config.py || true
	@echo "Linting completed!"

# Check code quality and run tests
quality-check: lint test-strict
	@echo "Quality check completed!"

# Build the package
build: clean
	python setup.py build

# Create source and wheel distributions
dist: clean
	python setup.py sdist bdist_wheel
	@echo "Distribution package created in dist/"

# Upload to PyPI
upload: dist
	@echo "Uploading to PyPI..."
	twine upload dist/*
	@echo "Package uploaded to PyPI"

# Upload to TestPyPI for testing before actual release
upload-test: dist
	@echo "Uploading to TestPyPI..."
	twine upload --repository-url https://test.pypi.org/legacy/ dist/*
	@echo "Package uploaded to TestPyPI"
	@echo "You can install it with:"
	@echo "pip install --index-url https://test.pypi.org/simple/ nadb"

# Install development requirements
dev-setup: dev-install
	pip install pytest pytest-cov pylint flake8 twine wheel redis

# Test all examples to ensure they work
test-examples: install-redis
	@echo "Testing all examples..."
	@echo "Testing blog example..."
	cd examples/blog && python blog.py &
	sleep 2
	pkill -f "python blog.py" || true
	@echo "Testing todo example..."
	cd examples/todo && python todo_app_redis.py &
	sleep 2
	pkill -f "python todo_app_redis.py" || true
	@echo "Testing wiki example..."
	cd examples/wiki && python wiki_system.py &
	sleep 2
	pkill -f "python wiki_system.py" || true
	@echo "All examples tested successfully!"

# Run comprehensive test suite (all tests + examples)
test-comprehensive: test-all test-examples
	@echo "Comprehensive test suite completed successfully!"

# Default target when just running 'make'
all: test build 