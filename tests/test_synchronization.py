"""Synchronization regressions using an independent local bare remote."""
from pathlib import Path
import subprocess
import unittest

import test_filtering as filtering


class SynchronizationTests(unittest.TestCase):
    setUp = filtering.FilteringTests.setUp
    git = filtering.FilteringTests.git
    put = filtering.FilteringTests.put
    configure = filtering.FilteringTests.configure
    backup = filtering.FilteringTests.backup

    def seed(self):
        self.put('configuration.yaml')
        self.backup()
        self.branch = self.git('symbolic-ref', '--short', 'HEAD')
        self.peer = self.root / 'peer'
        subprocess.run(['git', 'clone', '-q', '--branch', self.branch,
                        str(self.root / 'remote'), str(self.peer)], check=True)
        self.peer_git('config', 'user.name', 'Remote Tester')
        self.peer_git('config', 'user.email', 'remote@example.invalid')

    def peer_git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.peer), *args], text=True).strip()

    def remote_change(self, name, content):
        path = self.peer / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        self.peer_git('add', '-A')
        self.peer_git('commit', '-qm', 'Remote change')
        self.peer_git('push', '-q', 'origin', self.branch)
        return self.peer_git('rev-parse', 'HEAD')

    def remote_head(self):
        return subprocess.check_output(['git', '--git-dir', str(self.root / 'remote'),
                                        'rev-parse', f'refs/heads/{self.branch}'], text=True).strip()

    def test_remote_development_files_survive_backup_and_source_deletion(self):
        self.seed()
        self.remote_change('new-development-tool/settings.yaml', 'Git-owned\n')
        (self.source / 'configuration.yaml').unlink()
        self.backup()
        self.assertFalse((self.repo / 'configuration.yaml').exists())
        self.assertEqual((self.repo / 'new-development-tool/settings.yaml').read_text(), 'Git-owned\n')
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.remote_head())

    def test_remote_edit_of_managed_file_blocks_source_deletion(self):
        self.seed()
        remote = self.remote_change('configuration.yaml', 'Git-side development\n')
        (self.source / 'configuration.yaml').unlink()
        result = self.backup(success=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('blocks deletion', result.stderr)
        self.assertEqual(self.git('rev-parse', 'HEAD'), remote)
        self.assertEqual(self.git('status', '--porcelain'), '')
        self.assertEqual((self.repo / 'configuration.yaml').read_text(), 'Git-side development\n')

    def test_fresh_clone_uses_committed_ownership(self):
        self.seed()
        import shutil
        shutil.rmtree(self.repo)
        subprocess.run(['git', 'clone', '-q', '--branch', self.branch,
                        str(self.root / 'remote'), str(self.repo)], check=True)
        (self.source / 'configuration.yaml').unlink()
        self.backup()
        self.assertFalse((self.repo / 'configuration.yaml').exists())
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.remote_head())

    def test_manifest_merge_conflict_aborts_and_preserves_pending_backup(self):
        self.seed()
        import json
        hook = self.root / 'remote/hooks/pre-receive'
        hook.write_text('#!/bin/sh\nexit 1\n')
        hook.chmod(0o755)
        self.put('configuration.yaml', 'Pending local backup\n')
        self.assertNotEqual(self.backup(success=False).returncode, 0)
        pending = self.git('rev-parse', 'HEAD')
        hook.unlink()
        name = '.ha-backup/managed-files.json'
        value = json.loads((self.peer / name).read_text())
        value['files']['configuration.yaml']['fingerprint'] = '0' * 64
        remote = self.remote_change(name, json.dumps(value, indent=2, sort_keys=True) + '\n')
        result = self.backup(success=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('conflict', (result.stdout + result.stderr).lower())
        self.assertEqual(self.git('rev-parse', 'HEAD'), pending)
        self.assertEqual(self.remote_head(), remote)
        self.assertEqual(self.git('status', '--porcelain'), '')
        self.assertEqual((self.repo / 'configuration.yaml').read_text(), 'Pending local backup\n')

    def test_switch_existing_branch(self):
        self.seed()
        self.git('branch', 'backup-test')
        self.backup(branch='backup-test', action='setup_repository')
        self.assertEqual(self.git('symbolic-ref', '--short', 'HEAD'), 'backup-test')

    def test_switch_remote_only_branch(self):
        self.seed()
        self.peer_git('checkout', '-qb', 'remote-only')
        self.peer_git('push', '-q', 'origin', 'remote-only')
        self.backup(branch='remote-only', action='setup_repository')
        self.assertEqual(self.git('symbolic-ref', '--short', 'HEAD'), 'remote-only')

    def test_remote_advance_preserves_workflow_and_ignore(self):
        self.seed()
        remote = self.remote_change('.github/workflows/ha-sync-pr.yml', 'remote workflow\n')
        self.backup(action='setup_repository')
        self.assertEqual(self.git('rev-parse', 'HEAD'), remote)
        self.remote_change('.gitignore', 'ignored-local-file\n')
        self.backup()
        self.assertEqual((self.repo / '.github/workflows/ha-sync-pr.yml').read_text(), 'remote workflow\n')
        self.assertEqual((self.repo / '.gitignore').read_text(), 'ignored-local-file\n')
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.remote_head())

    def test_failed_push_retried_without_new_changes(self):
        self.seed()
        hook = self.root / 'remote/hooks/pre-receive'
        hook.write_text('#!/bin/sh\nexit 1\n')
        hook.chmod(0o755)
        self.put('configuration.yaml', 'changed configuration after rejected push\n')
        result = self.backup(success=False)
        self.assertNotEqual(result.returncode, 0)
        pending = self.git('rev-parse', 'HEAD')
        self.assertNotEqual(pending, self.remote_head())
        hook.unlink()
        self.backup()
        self.assertEqual(pending, self.remote_head())
        self.assertEqual(pending, self.git('rev-parse', 'HEAD'))

    def test_divergence_merges_without_losing_commits(self):
        self.seed()
        self.put('local.yaml', destination=True)
        self.git('add', '-A')
        self.git('commit', '-qm', 'Local pending commit')
        local = self.git('rev-parse', 'HEAD')
        remote = self.remote_change('.github/workflows/ha-sync-pr.yml', 'remote workflow\n')
        self.backup(action='setup_repository')
        self.git('merge-base', '--is-ancestor', local, 'HEAD')
        self.git('merge-base', '--is-ancestor', remote, 'HEAD')
        self.assertEqual(len(self.git('rev-list', '--parents', '-n', '1', 'HEAD').split()), 3)

    def test_merge_conflict_aborts_without_overwriting_commits(self):
        self.seed()
        self.put('configuration.yaml', 'local edit\n', destination=True)
        self.git('add', '-A')
        self.git('commit', '-qm', 'Local edit')
        local = self.git('rev-parse', 'HEAD')
        remote = self.remote_change('configuration.yaml', 'remote edit\n')
        result = self.backup(success=False, action='setup_repository')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('conflict', (result.stdout + result.stderr).lower())
        self.assertEqual(self.git('rev-parse', 'HEAD'), local)
        self.assertEqual(self.remote_head(), remote)
        self.assertEqual((self.repo / 'configuration.yaml').read_text(), 'local edit\n')
        self.assertEqual(self.git('status', '--porcelain'), '')

    def test_uncommitted_changes_block_switch_and_backup(self):
        self.seed()
        self.git('branch', 'backup-test')
        self.put('configuration.yaml', 'uncommitted\n', destination=True)
        for action in ['setup_repository', 'do_backup test']:
            result = self.backup(branch='backup-test', action=action, success=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(self.git('symbolic-ref', '--short', 'HEAD'), self.branch)
            self.assertEqual((self.repo / 'configuration.yaml').read_text(), 'uncommitted\n')

    def test_configured_identity_without_home(self):
        self.seed()
        self.backup(action='setup_repository', unset_home=True)
        self.put('configuration.yaml', 'identity check\n')
        self.backup(unset_home=True)
        self.assertEqual(self.git('log', '-1', '--format=%an <%ae>'),
                         'Backup Tester <backup@example.invalid>')

    def test_pending_push_and_remote_advance_are_both_preserved(self):
        self.seed()
        hook = self.root / 'remote/hooks/pre-receive'
        hook.write_text('#!/bin/sh\nexit 1\n')
        hook.chmod(0o755)
        self.put('configuration.yaml', 'pending backup configuration\n')
        self.assertNotEqual(self.backup(success=False).returncode, 0)
        pending = self.git('rev-parse', 'HEAD')
        hook.unlink()
        remote = self.remote_change('.github/workflows/ha-sync-pr.yml', 'remote workflow\n')
        self.backup()
        self.git('merge-base', '--is-ancestor', pending, 'HEAD')
        self.git('merge-base', '--is-ancestor', remote, 'HEAD')
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.remote_head())

    def test_fetch_failure_leaves_local_history_and_source_untouched(self):
        self.seed()
        head = self.git('rev-parse', 'HEAD')
        self.git('remote', 'set-url', 'origin', str(self.root / 'missing-remote'))
        self.put('configuration.yaml', 'source change must not be copied\n')
        result = self.backup(success=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.git('rev-parse', 'HEAD'), head)
        self.assertEqual((self.repo / 'configuration.yaml').read_text(), 'fixture\n')

    def test_staged_and_untracked_work_is_preserved(self):
        self.seed()
        self.put('configuration.yaml', 'staged change\n', destination=True)
        self.git('add', 'configuration.yaml')
        self.put('untracked.yaml', 'untracked work\n', destination=True)
        before = self.git('status', '--porcelain')
        result = self.backup(success=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.git('status', '--porcelain'), before)
        self.assertEqual((self.repo / 'configuration.yaml').read_text(), 'staged change\n')
        self.assertEqual((self.repo / 'untracked.yaml').read_text(), 'untracked work\n')

    def test_initial_setup_without_home_or_existing_repository(self):
        # No clone or global user identity is required, even for an empty remote.
        import shutil
        shutil.rmtree(self.repo)
        self.backup(branch='new-backup', action='setup_repository', unset_home=True)
        self.put('configuration.yaml')
        self.backup(branch='new-backup', unset_home=True)
        self.assertEqual(self.git('log', '-1', '--format=%an <%ae>'),
                         'Backup Tester <backup@example.invalid>')

    def test_existing_merge_is_not_aborted_by_backup(self):
        self.seed()
        self.git('checkout', '-qb', 'other')
        self.put('configuration.yaml', 'other change\n', destination=True)
        self.git('add', '-A')
        self.git('commit', '-qm', 'Other change')
        self.git('checkout', self.branch)
        self.put('configuration.yaml', 'local change\n', destination=True)
        self.git('add', '-A')
        self.git('commit', '-qm', 'Local change')
        merge = subprocess.run(['git', '-C', str(self.repo), 'merge', 'other'], capture_output=True)
        self.assertNotEqual(merge.returncode, 0)
        before = self.git('status', '--porcelain')
        self.assertNotEqual(self.backup(success=False).returncode, 0)
        self.assertEqual(self.git('status', '--porcelain'), before)
        self.assertTrue((self.repo / '.git/MERGE_HEAD').exists())
