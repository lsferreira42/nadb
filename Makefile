.PHONY: clean test test-fs test-redis test-all lint build dist upload upload-test all help dev-install

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
	@echo "  test-all    - Run all tests for all backends"
	@echo "  test-quick  - Run tests without slow tests"
	@echo "  test-cov    - Run tests with coverage report"
	@echo "  lint        - Run linting tools"
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
	PYTHONPATH=. pytest -v nakv_tests_redis.py

# Run all tests for all backends
test-all: install-redis
	PYTHONPATH=. pytest -v nakv_tests_fs.py nakv_tests_redis.py

# Run tests without slow tests (marked with @pytest.mark.slow)
test-quick: dev-install
	PYTHONPATH=. pytest -v nakv_tests_fs.py -k "not slow"

# Run tests with coverage report
test-cov: install-redis
	PYTHONPATH=. pytest --cov=. nakv_tests_fs.py nakv_tests_redis.py --cov-report=term --cov-report=html
	@echo "HTML coverage report generated in htmlcov/"

# Run linting tools
lint:
	pylint nakv.py
	flake8 nakv.py

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

# Default target when just running 'make'
all: test build 