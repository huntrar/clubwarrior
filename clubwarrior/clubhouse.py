"""Clubhouse REST API v2 client."""
import json
import os
import sys
from collections import defaultdict
import requests

from .config import Config


class Story:
    def __init__(self, resp=defaultdict(str), workflow_state=None, project=None):
        # Load configuration
        config = Config()
        self.PRIORITIES = config.get('DEFAULT', 'Priorities', fallback=dict())

        # Date is loaded from Clubhouse API response or from a previous state saved in a file
        self._data = {}

        keys = ['id', 'name', 'started_at']
        self._data.update({k: v for k, v in resp.items() if k in keys})
        self._data['project'] = project
        self._data['workflow_state'] = workflow_state
        self._data['blocked_by'] = resp.get('blocked_by', {})
        self._data['tags'] = resp.get('tags', [])
        self._data['task_uuid'] = resp.get('task_uuid', 0)
        self._data['deadline'] = resp.get('deadline', None)
        self._data['priority'] = resp.get('priority', None)

        self.deserialize_api(resp)

        # Keys to ignore in __eq__, __bool__
        self.ignore_keys = ['task_uuid']


    def __getitem__(self, key):
        try:
            int(key)
            raise StopIteration
        except ValueError:
            pass

        return self._data.get(key, None)

    def __setitem__(self, key, value):
        self._data[key] = value

    def deserialize_api(self, resp):
        """Load data from serialized Clubhouse API response."""
        # Find any stories blocking this story
        if resp.get('blocked', False):
            for s in resp.get('story_links', []):
                if s['verb'] == 'blocks' and s['object_id'] == resp['id']:
                    self._data['blocked_by'][str(s['id'])] = s['subject_id']

        # Set tags and priority level if applicable
        for l in resp.get('labels', []):
            priorities = list(self.PRIORITIES.values())
            if l['name'] in priorities:
                # Set priority level, choosing the highest listed
                if not self._data['priority']:
                    self._data['priority'] = l['name']
                elif priorities.index(l['name']) < priorities.index(self._data['priority']):
                    self._data['priority'] = l['name']
            else:
                # Set tag
                self._data['tags'].append(l['name'].lower())

    def __repr__(self):
        return self._data['name']

    def __eq__(self, other):
        return {k: v for k, v in self._data.items() if k not in self.ignore_keys} == {k: v for k, v in other._data.items() if k not in self.ignore_keys}

    def __bool__(self):
        return any(v for k, v in self._data.items() if k not in self.ignore_keys)



class ClubhouseClient:
    def __init__(self):
        self.BASE_URL = 'https://api.clubhouse.io/api/v2'

        # Load configuration
        config = Config()
        self.DEBUG = config.get('DEFAULT', 'Debug', fallback=False)
        self.TOKEN = config.get('clubhouse', 'ApiToken', fallback=str()) or os.environ.get('CLUBHOUSE_API_TOKEN')
        self.OWNER = config.get('clubhouse', 'Owner', fallback=str()) or os.environ.get('CLUBHOUSE_OWNER')
        if not self.OWNER:
            sys.stderr.write('You must set Owner in the configuration or the CLUBHOUSE_OWNER environment variable to your Clubhouse.io username\n')
            sys.stderr.write('Configuration located at {}\n'.format(config.which()))
            sys.exit(1)

        # Populate with pull_from_remote()
        self.projects = {}
        self.workflow_states = {}
        self.stories = {}

    def get(self, endpoint, params=None):
        if params is None:
            params = {}
        params['token'] = self.TOKEN
        headers = {'Content-Type': 'application/json'}
        if self.DEBUG:
            print('curl -X GET -H "Content-Type: application/json" \'{}/{}?{}\''.format(self.BASE_URL, endpoint.lstrip('/'), '&'.join('{}={}'.format(k, v) for k, v in params.items())))
        r = requests.get('{}/{}'.format(self.BASE_URL, endpoint.lstrip('/')), params=params, headers=headers)
        r.raise_for_status()
        return r

    def put(self, endpoint, data=None):
        if data is None:
            data = {}
        headers = {'Content-Type': 'application/json'}
        if self.DEBUG:
            print('curl -X PUT -H "Content-Type: application/json" \'{}/{}?token={}\' --data \'{}\''.format(self.BASE_URL, endpoint.lstrip('/'), self.TOKEN, json.dumps(data)))
        r = requests.put('{}/{}?token={}'.format(self.BASE_URL, endpoint.lstrip('/'), self.TOKEN), data=json.dumps(data), headers=headers)
        r.raise_for_status()
        return r

    def post(self, endpoint, data=None):
        if data is None:
            data = {}
        headers = {'Content-Type': 'application/json'}
        if self.DEBUG:
            print('curl -X POST -H "Content-Type: application/json" \'{}/{}?token={}\' --data \'{}\''.format(self.BASE_URL, endpoint.lstrip('/'), self.TOKEN, json.dumps(data)))
        r = requests.post('{}/{}?token={}'.format(self.BASE_URL, endpoint.lstrip('/'), self.TOKEN), data=json.dumps(data), headers=headers)
        r.raise_for_status()
        return r

    def delete(self, endpoint):
        headers = {'Content-Type': 'application/json'}
        if self.DEBUG:
            print('curl -X DELETE -H "Content-Type: application/json" \'{}/{}?token={}\''.format(self.BASE_URL, endpoint.lstrip('/'), self.TOKEN))
        r = requests.delete('{}/{}?token={}'.format(self.BASE_URL, endpoint.lstrip('/'), self.TOKEN), headers=headers)
        r.raise_for_status()
        return r

    def list_projects(self):
        """List Projects returns a dictionary of Project IDs mapped to their Project names ."""
        return {x['id']: x['name'].lower() for x in self.get('projects').json()}

    def list_default_workflow_states(self):
        """List Workflow States returns a list of all (default) Workflow states in the organization."""
        return {x['id']: x['name'] for x in self.get('workflows').json()[0]['states']}

    def get_story(self, story_id, params=None):
        """Get Story returns information about a chosen Story."""
        if params is None:
            params = {}
        return self.get('stories/{}'.format(str(story_id).lstrip('/')), params).json()

    def search_stories(self, params):
        """Search Stories lets you search Stories based on desired parameters."""
        return self.get('search/stories', params).json()['data']

    def update_story(self, story_id, data=None):
        """Update Story can be used to update Story properties."""
        if data is None:
            data = {}
        return self.put('stories/{}'.format(story_id), data).json()

    def create_story_link(self, data=None):
        """Story links (called Story Relationships in the UI) allow you create semantic relationships between two stories."""
        if data is None:
            data = {}
        return self.post('story-links', data).json()

    def delete_story_link(self, link_id):
        """Delete Story-Link can be used to delete any Story Link (called Story Relationships in the UI)."""
        return self.delete('story-links/{}'.format(link_id))

    def pull_from_remote(self):
        """Pull Clubhouse objects (workflow states, projects, stories) from remote Clubhouse."""
        # Map of workflow state IDs to workflow states (Ready for Review, Deploying, Completed, etc..)
        self.workflow_states = self.list_default_workflow_states()

        # Map of project ID to project name for resolving project_id in a Story
        self.projects = self.list_projects()

        # List of stories owned by owner set in config
        self.stories = {s['id']: Story(s, self.workflow_states[s['workflow_state_id']], self.projects[s['project_id']])
                        for s in self.search_stories({'query': 'owner:{}'.format(self.OWNER)})}
