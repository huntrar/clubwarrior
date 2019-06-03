#!/usr/bin/env python

from setuptools import setup, find_packages
import clubwarrior
import os

def read(*names):
    values = dict()
    extensions = ['.txt', '.rst']
    for name in names:
        value = ''
        for extension in extensions:
            filename = name + extension
            if os.path.isfile(filename):
                value = open(name + extension).read()
                break
        values[name] = value
    return values

long_description = """
%(README)s

News
====

%(CHANGES)s

""" % read('README', 'CHANGES')

setup(
    name='clubwarrior',
    version=clubwarrior.__version__,
    description='Track and sync your Clubhouse.io stories in TaskWarrior',
    long_description=long_description,
    classifiers=[
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
    ],
    keywords='clubhouse.io taskwarrior task tracking management sync',
    author='Hunter Hammond',
    author_email='huntrar@gmail.com',
    maintainer='Hunter Hammond',
    maintainer_email='clubwarrior.dev@gmail.com',
    url='https://github.com/huntrar/clubwarrior',
    license='MIT',
    packages=find_packages(),
    entry_points={
        'console_scripts': [
            'clubwarrior = clubwarrior.clubwarrior:run',
        ]
    },
    install_requires=[
        'requests',
        'tasklib',
    ]
)
