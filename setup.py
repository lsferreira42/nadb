from setuptools import setup, find_packages

setup(
    packages=['nadb'],
    package_dir={'nadb': '.'},
    name='nadb',
    version='0.0.5',
    install_requires=[],
    author='Leandro Ferreira',
    author_email='leandrodsferreira@gmail.com',
    description='A simple, thread-safe, zero external dependencies key-value store '
                'with asynchronous memory buffering capabilities and disk persistence.',
    long_description=open('README.md').read(),
    long_description_content_type='text/markdown',
    url='https://github.com/lsferreira42/nadb',
)

