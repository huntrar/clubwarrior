clubwarrior - Synchronize tasks between Clubhouse.io and TaskWarrior
====================================================================

``clubwarrior`` imports stories you are the owner of from `Clubhouse <https://clubhouse.io>`_ as tasks in `taskwarrior <https://taskwarrior.org>`_.

Features two-way synchronization of the following details:

 - story name / task description
 - project
 - story labels / task priority and tags
 - story deadline / task due
 - dependencies
 - state (story started / task active, story completed / task completed)

*This project is in the very early development stages and does not yet have proper tests in place, use it at your own risk.*

It is suggested you `backup your Clubhouse data <https://github.com/huntrar/exporter>`_ before using this program.

Installation
------------

::

    pip install clubwarrior

or

::

    pip install git+https://github.com/huntrar/clubwarrior.git#egg=clubwarrior

or

::

    git clone https://github.com/huntrar/clubwarrior
    cd clubwarrior
    python setup.py install

Usage
-----

The suggested method of running ``clubwarrior`` is with cron or a systemd timer.
If you are working on a heavily active Clubhouse.io environment, the longer the time between executions the higher risk of a synchronization conflict arising.

For features currently under development for now you can refer to the TODO list in the clubwarrior executable.

Further documentation will come as the project is further developed. Contributors are of course welcome.

Author
------

 - Hunter Hammond (clubwarrior.dev@gmail.com)
