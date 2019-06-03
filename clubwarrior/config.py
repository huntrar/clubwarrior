import configparser
import json
import os

import appdirs

from . import name, __author__



class Config:
    def __init__(self):
        self.config = configparser.ConfigParser()

        self.CONFIG_DIR = appdirs.user_config_dir(name, __author__)
        self.CONFIG_FILE = '{}/config.ini'.format(self.CONFIG_DIR.rstrip('/'))
        self.DATA_DIR = appdirs.user_data_dir(name, __author__)
        self.DATA_FILE = '{}/data.json'.format(self.DATA_DIR.rstrip('/'))

        if not os.path.exists(self.CONFIG_FILE):
            self.create_default()

        self.load()

        self.TASK_DIR = os.path.expanduser(self.get('taskwarrior', 'TaskDir'))

    def create_default(self):
        """Creates a default configuration file, user must set Owner and ApiKey fields for Clubhouse."""
        self.config['DEFAULT'] = {
            'Priorities': '{"H": "High", "M": "Medium", "L": "Low"}',
            'LabelColors': '{"High": "#ff0000", "Medium": "#ffA500", "Low": "#ffff00", "default": "#ffff00"}',
            'AutoResolveConflict': 'false',
            'Debug': 'false'
        }

        self.config['clubhouse'] = {
            'Owner': '',
            'ApiToken': '',
            'DevelopmentState': '"In Development"',
            'ReviewState': '"Ready for Review"',
            'CompletedState': '"Completed"',
            'PostDevWorkflowStates': '["Ready for Review", "Deploying", "Completed", "Tabled", "Cancelled"]'
        }

        self.config['taskwarrior'] = {
            'IgnoreTags': '["next"]',
            'TaskDir': '"~/.task"'
        }

        os.makedirs(self.CONFIG_DIR, exist_ok=True)
        with open(self.CONFIG_FILE, 'w') as f:
            print('Creating configuration file {}'.format(self.CONFIG_FILE))
            self.config.write(f)

    def load(self):
        self.config.read(self.CONFIG_FILE)

    def get(self, section, option, fallback=None):
        try:
            fallback = json.dumps(fallback)
            return json.loads(self.config.get(section, option, fallback=fallback) or fallback)
        except json.decoder.JSONDecodeError:
            return self.config.get(section, option)

    def getboolean(self, section, option, fallback=False):
        return self.config.getboolean(section, option, fallback=fallback)

    def which(self):
        return self.CONFIG_FILE
