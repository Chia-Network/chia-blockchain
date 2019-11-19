#!/usr/bin/env python

import re

import setuptools

NAME = "aiter"

packages = setuptools.find_packages(exclude=["tests"])
test_requirements = "pytest>=2.8.0"

with open('%s/__init__.py' % NAME, 'r') as fd:
    version = re.search(r'^__version__\s*=\s*[\'"]([^\'"]*)[\'"]',
                        fd.read(), re.MULTILINE).group(1)

with open('README.md') as f:
    readme = f.read()

with open('HISTORY.md') as f:
    history = f.read()


setuptools.setup(
    name=NAME,
    description="Useful patterns building upon asynchronous iterators.",
    long_description=readme + '\n\n' + history,
    long_description_content_type="text/markdown",
    author="Richard Kiss",
    author_email="him@richardkiss.com",
    version=version,
    packages=packages,
    package_data={'': ['LICENSE', 'NOTICE'], 'requests': ['*.pem']},
    url="https://github.com/richardkiss/%s" % NAME,
    license="http://opensource.org/licenses/MIT",
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Intended Audience :: Developers',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'License :: OSI Approved :: MIT License',
    ],)
