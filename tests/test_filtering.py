"""Local integration tests: python3 -m unittest discover -s tests -v."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'git-backup/rootfs/run.sh'


class FilteringTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / 'config'
        self.repo = self.root / 'repository'
        self.source.mkdir()
        self.repo.mkdir()
        self.options = self.root / 'options.json'
        self.configure([], [])
        self.git('init', '-q')
        self.git('config', 'user.name', 'Test')
        self.git('config', 'user.email', 'test@example.invalid')
        subprocess.run(['git', 'init', '--bare', '-q', str(self.root / 'remote')], check=True)
        self.git('remote', 'add', 'origin', str(self.root / 'remote'))
        branch = self.git('symbolic-ref', '--short', 'HEAD')
        self.git('config', f'branch.{branch}.remote', 'origin')
        self.git('config', f'branch.{branch}.merge', f'refs/heads/{branch}')

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.repo), *args], text=True).strip()

    def configure(self, includes, excludes):
        self.options.write_text(json.dumps(dict(include_patterns=includes, exclude_patterns=excludes)))

    def put(self, name, content='fixture\n', destination=False):
        path = (self.repo if destination else self.source) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def backup(self, success=True, fail_sync=False):
        # Load actual functions without starting the add-on or accessing /data.
        script = SCRIPT.read_text()
        helpers = script[script.index('get_config_array()'):script.index('# Load configuration')]
        functions = script[script.index('build_rsync_args()'):script.index('# File Watcher')]
        harness = 'set -e\n' + helpers + '\n' + functions + '''
REPO_DIR=$1
HA_CONFIG=$2
CONFIG_PATH=$3
BRANCH=$(git -C "$REPO_DIR" symbolic-ref --short HEAD)
COMMIT_MESSAGE='Backup: {files}'
update_status() { :; }
do_backup test
'''
        if fail_sync:
            harness = harness.replace('do_backup test', 'rsync() { return 23; }\ndo_backup test')
        result = subprocess.run(['bash', '-c', harness, 'test', str(self.repo), str(self.source), str(self.options)],
                                capture_output=True, text=True)
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def test_deployment_structure_and_nested_allowlist(self):
        names = ['automations.yaml', 'scripts.yaml', 'configuration.yaml',
                 'blueprints/automation/nested/example.yaml',
                 'custom_components/example/nested/module.py', 'themes/dark/nested/theme.yaml',
                 'www/assets/icons/icon.svg', '.ssh/ha_deploy', '.ssh/ha_deploy.pub',
                 '.ha-deploy/repository/configuration.yaml', '.ha-deploy/baseline/old.yaml',
                 'deploy/check.sh', 'deploy/conflicts.sh', 'secrets.yaml', 'other.txt']
        for name in names:
            self.put(name)
        self.configure(['automations.yaml', 'scripts.yaml', 'configuration.yaml',
                        'blueprints/*', 'custom_components/*', 'themes/*', 'www/*', '*.yaml'],
                       ['.ha-deploy/', '.ssh/', 'deploy/', 'secrets.yaml'])
        self.backup()
        for name in names[:7]:
            self.assertTrue((self.repo / name).exists(), name)
        for name in names[7:]:
            self.assertFalse((self.repo / name).exists(), name)

    def test_tracked_exclusion_and_source_deletion(self):
        for name in ['configuration.yaml', 'secrets.yaml', '.ha-deploy/repository/old.yaml']:
            self.put(name)
        self.backup()
        self.configure(['*.yaml'], ['secrets.yaml', '.ha-deploy/'])
        (self.source / 'configuration.yaml').unlink()
        self.backup()
        self.assertEqual(self.git('ls-files'), '')
        self.assertTrue((self.source / 'secrets.yaml').exists())
        self.assertTrue((self.source / '.ha-deploy/repository/old.yaml').exists())
        self.assertFalse((self.repo / '.ha-deploy').exists())

    def test_empty_list_builtins_storage_and_metadata(self):
        self.put('ordinary.txt')
        self.put('.git/config', 'source metadata')
        self.put('nested/.git/config', 'nested metadata')
        self.put('.storage/lovelace.dashboard')
        self.put('.storage/core.config')
        for name in ['data.db', 'data.db-shm', 'data.db-wal', 'debug.log', 'home-assistant.log.1',
                     'OZW_Log.txt', 'tts/cache', 'backups/a.tar', 'backup/a.tar', '.cloud/token',
                     '__pycache__/a.pyc', 'a.tmp', '.cache/a', 'a.pyc', '.storage/auth',
                     'flows_cred.json', 'esphome/secrets.yaml', 'movie.mp4', '.idea/settings',
                     '.DS_Store', 'a.swp']:
            self.put(name)
        metadata = (self.repo / '.git/config').read_bytes()
        self.backup()
        self.assertEqual((self.repo / '.git/config').read_bytes(), metadata)
        self.assertFalse((self.repo / 'nested/.git').exists())
        self.assertEqual(set(self.git('ls-files').splitlines()),
                         {'ordinary.txt', '.storage/lovelace.dashboard', '.storage/core.config'})

    def test_ignore_preserved_and_no_repeat_commit(self):
        self.put('.gitignore', 'user ignored.yaml\n', destination=True)
        self.put('.gitignore', 'different\n')
        self.put('configuration.yaml')
        self.put('user ignored.yaml')
        self.backup()
        head = self.git('rev-parse', 'HEAD')
        self.backup()
        self.assertEqual(head, self.git('rev-parse', 'HEAD'))
        self.assertEqual((self.repo / '.gitignore').read_text(), 'user ignored.yaml\n')
        self.assertNotIn('user ignored.yaml', self.git('ls-files'))

    def test_allowlist_change_preserves_old_backup(self):
        self.put('one.yaml')
        self.put('two.yaml')
        self.backup()
        head = self.git('rev-parse', 'HEAD')
        self.configure(['one.yaml'], [])
        (self.source / 'two.yaml').unlink()
        self.backup()
        self.assertTrue((self.repo / 'two.yaml').exists())
        self.assertEqual(head, self.git('rev-parse', 'HEAD'))

    def test_spaces_and_storage_explicit_exclusion(self):
        self.put('themes/my theme/deep/file with spaces.yaml')
        self.put('.storage/lovelace.dashboard')
        self.put('.storage/core.config')
        self.configure(['themes/*', '!.storage/lovelace*', '!.storage/core.config'],
                       ['themes/my theme/deep/file with spaces.yaml', '.storage/*'])
        self.backup()
        self.assertEqual(self.git('ls-files'), '')

    def test_matching_include_exclude_and_spaces(self):
        self.put('file with spaces.yaml')
        self.put('blocked.yaml')
        self.put('old.pre-deploy')
        self.put('key.pub')
        self.configure(['*.yaml', '*'], ['blocked.yaml', '*.pre-deploy', '*.pub'])
        self.backup()
        self.assertEqual(self.git('ls-files'), 'file with spaces.yaml')

    def test_builtins_remove_previously_tracked_files(self):
        for name in ['data.db', '.storage/auth', 'nested/.git/config']:
            self.put(name, destination=True)
        self.git('add', '-A')
        self.git('commit', '-qm', 'Previously tracked protected files')
        self.configure(['*'], [])
        self.backup()
        self.assertEqual(self.git('ls-files'), '')
        self.assertEqual((self.repo / 'nested/.git/config').read_text(), 'fixture\n')
        self.assertFalse((self.repo / 'data.db').exists())
        self.assertFalse((self.repo / '.storage/auth').exists())

    def test_sync_failure_aborts_before_staging(self):
        self.put('configuration.yaml')
        self.backup()
        head = self.git('rev-parse', 'HEAD')
        self.put('configuration.yaml', 'unstaged change', destination=True)
        result = self.backup(success=False, fail_sync=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(head, self.git('rev-parse', 'HEAD'))
        self.assertEqual(self.git('diff', '--cached', '--name-only'), '')

    def test_legacy_storage_includes_without_conflicting_exclusion(self):
        self.put('.storage/lovelace.dashboard')
        self.put('.storage/core.config')
        self.put('.storage/auth')
        self.configure(['!.storage/lovelace*', '!.storage/core.config'], [])
        self.backup()
        self.assertEqual(set(self.git('ls-files').splitlines()),
                         {'.storage/lovelace.dashboard', '.storage/core.config'})

    def test_directory_exclusions_at_any_depth(self):
        for name in ['nested/.ssh/private', 'nested/__pycache__/cache',
                     'nested/backups/archive', 'nested/themes/sub/theme.yaml']:
            self.put(name)
        self.configure(['themes/'], ['.ssh/'])
        self.backup()
        self.assertEqual(self.git('ls-files'), 'nested/themes/sub/theme.yaml')
        self.configure([], [])
        self.put('nested/.ha-deploy/deep/file.yaml')
        self.backup()
        self.configure(['themes/'], ['.ha-deploy/'])
        self.backup()
        self.assertFalse((self.repo / 'nested/.ha-deploy').exists())

    def test_shipped_defaults(self):
        config = (SCRIPT.parents[1] / 'config.yaml').read_text()
        options = config.split('options:', 1)[1].split('schema:', 1)[0]
        excludes, includes = options.split('  exclude_patterns:', 1)[1].split('  include_patterns:', 1)
        parse = lambda lines: [json.loads(line.strip()[2:])
                               for line in lines.splitlines() if line.strip().startswith('- ')]
        self.configure(parse(includes), parse(excludes))
        for name in ['configuration.yaml', 'themes/deep/theme.css', '.storage/lovelace.dashboard',
                     '.storage/core.config', '.storage/auth', 'unselected.txt', 'data.db']:
            self.put(name)
        self.backup()
        self.assertEqual(set(self.git('ls-files').splitlines()),
                         {'configuration.yaml', 'themes/deep/theme.css',
                          '.storage/lovelace.dashboard', '.storage/core.config'})
        self.assertFalse((self.repo / '.gitignore').exists())


if __name__ == '__main__':
    unittest.main()
