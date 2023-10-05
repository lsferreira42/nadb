from setuptools import setup, find_packages

setup(
    name='nadb',
    version='0.1.0',
    packages=find_packages(),
    install_requires=[],
    author='Leandro Ferreira',
    author_email='leandrodsferreira@gmail.com',
    description='A simple lock based key-value store',
    long_description=open('README.md').read(),
    long_description_content_type='text/markdown',
    url='https://github.com/lsferreira42/nadb',
)

