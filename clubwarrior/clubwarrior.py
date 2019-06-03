#!/usr/bin/python3
import json
import sys
import os
from datetime import datetime
from tasklib import TaskWarrior, Task

from .config import Config
from .clubhouse import ClubhouseClient, Story

# TODO: See additional comments strewn throughout the file
#       Tests
#       Run as TaskWarrior hook
#       Include instructions to run as cron job
#           Also send signal to redraw vit display somehow
#       Manual conflict resolution
#       Import tasks instead of stories?
#           Might make things cluttered very quickly, but makes more sense granularity wise
#       Option to annotate tasks with Clubhouse URL
#           These annotations display by default in vit and would increase clutter, but handy to open with taskopen


class ClubWarrior:
    def __init__(self):
        # Load configuration
        self.config = Config()

        self.DEV_STATE = self.config.get('clubhouse', 'DevelopmentState')
        self.REVIEW_STATE = self.config.get('clubhouse', 'ReviewState')
        self.PRIORITIES = self.config.get('DEFAULT', 'Priorities', fallback=dict())
        self.IGNORE_TAGS = self.config.get('taskwarrior', 'IgnoreTags', fallback=list())

        # List of "post-development" workflow states defined by the user to match their Clubhouse workflow schema
        self.POSTDEV_STATES = self.config.get('clubhouse', 'PostDevWorkflowStates', fallback=list())
        # Create ClubWarrior data directory

        os.makedirs(self.config.DATA_DIR, exist_ok=True)

        # Instantiate Clubhouse client
        self.cc = ClubhouseClient()

        # Instantiate TaskWarrior client
        self.tw = TaskWarrior(self.config.TASK_DIR)

    def deserialize(self):
        """Deserialize Story's with Task UUIDs stored in local Clubhouse state."""
        if not os.path.exists(self.config.DATA_FILE):
            return {}

        with open(self.config.DATA_FILE, 'r') as f:
            return {s['id']: Story(s, s['workflow_state'], s['project']) for s in json.load(f)}

    def serialize(self, stories=None):
        """Serialize Story's with Task UUIDs to local Clubhouse state."""
        if stories is None:
            stories = list(self.cc.stories.values())

        # Discard stories that are in post-development states from our local Clubhouse state
        # We only wish to track stories that are yet to enter or are in active development
        active_stories = [x for x in stories if x['workflow_state'] not in self.POSTDEV_STATES]

        with open(self.config.DATA_FILE, 'w') as f:
            f.write(json.dumps(active_stories, default=lambda x: x._data))

    def filter_postdev(self, stories):
        """Filter out stories in a post-development state."""
        return {k: v for k, v in stories.items() if v['workflow_state'] not in self.POSTDEV_STATES}

    def filter_completed(self, tasks):
        """Filter out tasks in a completed state."""
        return [t for t in tasks if not t.completed]

    def update(self):
        """Synchronize changes between TaskWarrior and Clubhouse.

           Stories from Clubhouse are imported as tasks within TaskWarrior if they meet the following conditions:
               Owned by the username stored in the config.ini or the env variable CLUBWARRIOR_OWNER
               Workflow state is not a post-development state stored in the config.ini
                   These are Clubhouse workflow states which logically follow the Development stage
                       e.g. "Ready for Review", "Deploying", "Completed"

           Tasks which did not originate from Clubhouse are not synchronized.

           Taskwarrior <-> Clubhouse equivalencies:
               task.active <-> `In Development` workflow state
               task.completed <-> `Ready for Review` workflow state


           Synchronization flow:

            TaskWarrior state diverges from local* Clubhouse state {
                *The local Clubhouse state is the last saved state of Clubhouse stories following the execution of update
                 Formatted in JSON and including respective TaskWarrior UUIDs

                Remote Clubhouse state diverges from local Clubhouse state {
                    Indicates a conflict.
                    To resolve, reflect remote Clubhouse changes in TaskWarrior and update local Clubhouse state
                         This can result in loss of changes in TaskWarrior.
                         To prevent conflicts, increase the frequency at which updates are made.
                }

                Remote Clubhouse state converges with local Clubhouse state {
                    Reflect TaskWarrior changes in remote Clubhouse and update local Clubhouse state
                }
            }

            Remote Clubhouse state diverges from TaskWarrior state {
                Reflect remote changes in TaskWarrior and update local Clubhouse state
            }


        """
        # TODO: Perform a rollback on Clubhouse on error?

        # Pull remote Clubhouse stories (self.cc.stories)
        self.cc.pull_from_remote()

        # Deserialize local Clubhouse Story's and filter out Story's in post-development states
        local_stories = self.filter_postdev(self.deserialize())

        # Get TaskWarrior tasks, using local Clubhouse stories to filter out untracked tasks
        tracked_uuids = [v['task_uuid'] for v in local_stories.values()]
        tasks = [t for t in self.tw.tasks.all() if t['uuid'] in tracked_uuids]

        # Retrieve task changes
        task_deltas = self.get_task_deltas(tasks, local_stories.values())
        if task_deltas:
            # Detect state conflicts between local and remote Clubhouse
            conflicts = self.get_conflicts(local_stories, self.cc.stories)
            if conflicts:
                # Resolve conflicts (may overwrite changes made to TaskWarrior since last update)
                task_deltas = self.resolve_conflicts(conflicts, task_deltas)

            # Push TaskWarrior changes to remote Clubhouse
            self.push_to_remote(task_deltas)

            # Push complete; refresh everything from remote
            self.cc.pull_from_remote()

        # Update or insert remote Clubhouse changes into TaskWarrior
        updated_stories = self.upsert_tasks(self.filter_completed(tasks), self.cc.stories.values(), local_stories)

        # Serialize any stories updated to the local Clubhouse state
        self.serialize(updated_stories)

    def get_task_deltas(self, tasks, stories):
        """Returns differences between tasks and local stories (keyed by Story ID.)

           Task data is returned in the comparison.

           The format of the delta objects conforms to the Update Story endpoint in Clubhouse's API
           The exception is delta['blocked_by_create'] and delta['blocked_by_delete'], which use Create/Delete Story-Link endpoints
        """
        # Optionally colored labels defined in config.ini
        LABEL_COLORS = self.config.get('DEFAULT', 'LabelColors', fallback=dict())

        deltas = {}

        # Stories keyed by task UUID
        uuid_stories = {v['task_uuid']: v for v in stories}

        # Create inverse workflow state and project dictionaries
        inverted_workflow_states = {v: k for k, v in self.cc.workflow_states.items()}
        inverted_projects = {v: k for k, v in self.cc.projects.items()}

        for task in tasks:
            story = uuid_stories.get(task['uuid'], Story())
            delta = {}

            if task['description'] != story['name']:
                delta['name'] = task['description']

            if task.completed and story['workflow_state'] not in self.POSTDEV_STATES:
                delta['workflow_state_id'] = inverted_workflow_states[self.REVIEW_STATE]

            tags = set(x for x in task['tags'] if x not in self.IGNORE_TAGS)
            if tags != set(story['tags']):
                delta['labels'] = [{'name': t} for t in tags]

            if task.active and story['workflow_state'] != self.DEV_STATE and not delta.get('workflow_state', None):
                delta['workflow_state_id'] = inverted_workflow_states[self.DEV_STATE]

            if task['project'] != story['project']:
                delta['project_id'] = inverted_projects.get(task['project'], 0)
                if not delta['project_id']:
                    # TODO: Create the Project in clubhouse instead of error?
                    raise Exception('Clubhouse requires a project be set to an existing option: {}.'.format(tuple(self.cc.projects.values())))

            task_due = None
            if task['due']:
                # Strip tzinfo that TaskWarrior includes
                task_due = task['due'].strftime("%Y-%m-%dT%H:%M:%SZ")
            if task_due != story['deadline']:
                delta['deadline'] = task_due

            task_blocked_by = set(uuid_stories[x]['id'] for x in task['depends']._uuids if x in uuid_stories) if task['depends'] else set()
            if task_blocked_by != set(story['blocked_by'].values()):
                # Create new blocking relationships
                delta['blocked_by_create'] = []

                for blocking_story_id in task_blocked_by:
                    blocks = {'subject_id': blocking_story_id,
                              'object_id': story['id'],
                              'verb': 'blocks'}
                    delta['blocked_by_create'].append(blocks)

                # Delete completed blocks
                delta['blocked_by_delete'] = []
                for link_id, subject_id in story['blocked_by'].items():
                    if subject_id not in task_blocked_by:
                        delta['blocked_by_delete'].append(str(link_id))

            priority = self.PRIORITIES[task['priority']] if task['priority'] in self.PRIORITIES else None
            if priority != story['priority']:
                if 'labels' not in delta:
                    # Preserve existing tags
                    delta['labels'] = [{'name': t} for t in tags]
                if priority:
                    delta['labels'].append({'name': priority})
            elif 'labels' in delta and story['priority']:
                # Preserve existing priority
                delta['labels'].append({'name': story['priority']})

            # Set optionally colored labels defined in config.ini
            for label in delta.get('labels', list()):
                color = LABEL_COLORS.get(label['name'], LABEL_COLORS.get('default', ''))
                if color:
                    label['color'] = color

            if delta:
                deltas[story['id']] = delta

        return deltas

    def get_conflicts(self, local, remote):
        """Returns IDs of any local stories modified remotely since last update."""
        return [k for k in local.keys() if local[k] != remote[k]]

    def resolve_conflicts(self, conflicts, deltas):
        """Removes conflicting tasks from the deltas list, effectively erasing any changes made.

           If AutoResolveConflict is not set to true in the configuration, prompts user first
        """
        if not self.config.getboolean('DEFAULT', 'AutoResolveConflict'):
            # TODO: implement a manual conflict resolution system
            resolve = input("""WARNING: Detected conflict between local and remote Clubhouse states.
         If you choose to continue, you may lose changes made to the affected tasks.
         Continue? (y/n): """).lower()
            if resolve not in ('y', 'yes'):
                sys.stderr.write('Exiting due to conflict between local and remote Clubhouse states.\n')
                sys.exit(1)

        # Resolve the conflict automatically by removing conflicting deltas
        return {k: v for k, v in deltas.items() if k not in conflicts}

    def push_to_remote(self, deltas):
        """Push task deltas to remote Clubhouse."""
        for k, delta in deltas.items():
            blocked_by_create = delta.pop('blocked_by_create', [])
            for blocks in blocked_by_create:
                self.cc.create_story_link(blocks)

            blocked_by_delete = delta.pop('blocked_by_delete', [])
            for link_id in blocked_by_delete:
                self.cc.delete_story_link(link_id)

            self.cc.update_story(k, delta)

    def upsert_tasks(self, tasks, remote_stories, local_stories):
        """Performs an in-place update on existing tasks or creates new tasks for untracked stories.

           If a story was modified remotely but diverges from its respective task, the task is updated.
           If a story exists remotely but not locally, a new task is created.
           The new state of the stories overwrites the last local state.
        """
        update_stories = {}
        create_stories = {}

        # Inverse priorities dictionary
        INVERSE_PRIORITIES = {v: k for k, v in self.PRIORITIES.items()}

        # Updated tasks is keyed by story ID and passed to create_tasks for managing addition of dependencies
        updated_tasks = {}

        # Attempt to resolve task UUID using local stories
        for v in remote_stories:
            if v['id'] in local_stories and local_stories[v['id']]['task_uuid']:
                v['task_uuid'] = local_stories[v['id']]['task_uuid']
                update_stories[v['task_uuid']] = v
            else:
                create_stories[v['id']] = v

        # Update existing tasks
        for task in tasks:
            story = update_stories.get(task['uuid'], Story())
            if task['description'] != story['name']:
                task['description'] = story['name']

            if story['workflow_state'] in self.POSTDEV_STATES:
                task['status'] = 'completed'

            tags = set(x for x in task['tags'] if x not in self.IGNORE_TAGS)
            ignore_tags = [x for x in task['tags'] if x in self.IGNORE_TAGS]
            story_tags = set(x for x in story['tags'] if x not in self.PRIORITIES.values())
            if tags != story_tags:
                task['tags'] = list(story_tags) + ignore_tags

            if not task.active and story['workflow_state'] == self.DEV_STATE:
                # Start task using Clubhouse start date
                task['start'] = datetime.strptime(story['started_at'], "%Y-%m-%dT%H:%M:%SZ")
            elif task.active and story['workflow_state'] != self.DEV_STATE:
                # Stop task
                task.stop()

            if task['project'] != story['project']:
                task['project'] = story['project']

            if story['deadline'] is not None:
                # Strip tzinfo that TaskWarrior includes
                task_due = datetime.strftime(task['due'], "%Y-%m-%dT%H:%M:%SZ")
                if task_due != story['deadline']:
                    task['due'] = datetime.strptime(story['deadline'], "%Y-%m-%dT%H:%M:%SZ")

            story_blocked_by = set(local_stories[x]['task_uuid'] for x in story['blocked_by'].values() if x in local_stories)
            task_blocked_by = set(update_stories[x]['task_uuid'] for x in task['depends']._uuids if x in update_stories) if task['depends'] else set()
            if task_blocked_by != story_blocked_by:
                task['depends'].add(story_blocked_by)

            story_priority = INVERSE_PRIORITIES[story['priority']] if story['priority'] in INVERSE_PRIORITIES else None
            if task['priority'] != story_priority:
                task['priority'] = story_priority

            # Save task (complete the update). Only saves if task was modified.
            task.save()

            # Add to updated tasks
            updated_tasks[story['id']] = task

        # Create new tasks out of stories that are not in a post-development state
        self.create_tasks(self.filter_postdev(create_stories), updated_tasks)

        # Save all the remote stories, post-development or not
        return list(update_stories.values()) + list(create_stories.values())

    def create_tasks(self, stories, inserted_tasks):
        """Create new tasks based on stories and insert them to TaskWarrior."""
        # Tasks contain tasks which have been inserted (keyed by Story ID, not Task UUID)
        tasks = dict(inserted_tasks)

        # Story IDs contain Story IDs which have not yet been inserted as a Task
        story_ids = list(stories.keys())
        while story_ids:
            # Tasks with dependencies (blockers) must have their dependencies inserted before them
            story = stories[story_ids[0]]
            blockers = [x for x in story_ids if x in set(story['blocked_by'].values())]
            if blockers:
                for blocker in blockers:
                    # Move blockers to the front of the queue
                    story_ids.remove(blocker)
                    story_ids.insert(0, blocker)
                continue

            # Remove story from queue to be inserted as a TaskWarrior task
            sid = story_ids.pop(0)

            task = Task(self.tw)
            task['description'] = story['name']
            task['project'] = story['project']

            if story['deadline']:
                task['due'] = datetime.strptime(story['deadline'], '%Y-%m-%dT%H:%M:%SZ')

            # Start task using Clubhouse start date
            if story['started_at'] and story['workflow_state'] == self.DEV_STATE:
                task['start'] = datetime.strptime(story['started_at'], "%Y-%m-%dT%H:%M:%SZ")

            # Clubhouse priorities are High, Medium, Low but TaskWarrior is H, M, L
            if story['priority']:
                task['priority'] = story['priority'][0]

            task['tags'] = set(story['tags'])

            # We can assume at this stage all dependent tasks have been inserted to tasks already
            task['depends'] = set(tasks[k] for k in set(story['blocked_by'].values()) if k in tasks)

            # Save task (complete the insertion)
            task.save()

            # Save the UUID of the newly inserted task in the respective Story object
            story['task_uuid'] = task['uuid']

            # Add saved task to tasks, keyed by Story ID
            tasks[sid] = task


def run():
    try:
        cw = ClubWarrior()
        cw.update()
    except KeyboardInterrupt:
        sys.stderr.write('\nExiting with failure...\n')
        sys.exit(1)

if __name__ == '__main__':
    run()
