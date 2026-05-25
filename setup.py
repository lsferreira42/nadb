from setuptools import setup, find_packages
import os


def read_version():
    version_file = os.path.join(os.path.dirname(__file__), "_version.py")
    with open(version_file, "r", encoding="utf-8") as f:
        namespace = {}
        exec(f.read(), namespace)
    return namespace["__version__"]

# Include SQL files
package_data = {
    'sql': ['*.sql'],
}

# Read the long description from README.md
with open('README.md', 'r', encoding='utf-8') as f:
    long_description = f.read()

setup(
    # Using explicit module name instead of package directory
    py_modules=['nakv', '_version', 'transaction', 'backup_manager', 'index_manager', 'logging_config', 'nadb_cli'],
    
    # Create an alias so import nadb works
    packages=['nadb', 'storage_backends', 'sql'],
    
    name='nadb',
    version=read_version(),
    install_requires=[],
    extras_require={
        'redis': ['redis>=3.5.0'],  # Optional Redis dependency
        's3': ['boto3>=1.20.0'],
        'otel': ['opentelemetry-api>=1.20.0'],
        'dev': ['pytest>=6.0.0', 'pytest-cov>=2.10.0'],
    },
    author='Leandro Ferreira',
    author_email='leandrodsferreira@gmail.com',
    description='A simple, thread-safe, zero external dependencies key-value store '
                'with asynchronous memory buffering capabilities, binary data support, '
                'tagging system, data compression, and pluggable storage backends.',
    long_description=long_description,
    long_description_content_type='text/markdown',
    url='https://github.com/lsferreira42/nadb',
    package_data=package_data,
    include_package_data=True,
    # packages=find_packages(),  # Make sure storage_backends is included
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Topic :: Database',
        'Topic :: Software Development :: Libraries',
        'Topic :: Software Development :: Libraries :: Python Modules',
    ],
    python_requires='>=3.7',
    keywords='database, key-value, nosql, storage, memory, disk, persistence, tagging, redis',
    entry_points={
        'console_scripts': [
            'nadb=nadb_cli:main',
        ],
    },
)
