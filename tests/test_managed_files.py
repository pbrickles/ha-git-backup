"""Ownership and migration integration tests through the real backup entry point."""
import importlib.util
import hashlib
import io
import json
import os
import shutil
import signal
import subprocess
import time
import unittest
from unittest.mock import patch

import test_filtering as filtering

spec = importlib.util.spec_from_file_location('managed_sync', filtering.SCRIPT.with_name('managed_sync.py'))
managed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(managed)


class ManagedFilesTests(unittest.TestCase):
    setUp = filtering.FilteringTests.setUp
    git = filtering.FilteringTests.git
    put = filtering.FilteringTests.put
    configure = filtering.FilteringTests.configure
    backup = filtering.FilteringTests.backup
    backup_files = filtering.FilteringTests.backup_files

    def commit_fixture(self):
        self.git('add', '-A')
        self.git('commit', '-qm', 'Fixture repository state')

    def manifest(self):
        return json.loads((self.repo / managed.MANIFEST).read_text())

    def assert_clean_failure(self, **kwargs):
        head = self.git('rev-parse', 'HEAD')
        result = self.backup(success=False, **kwargs)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.git('rev-parse', 'HEAD'), head)
        self.assertEqual(self.git('status', '--porcelain'), '')
        return result

    def approve(self, name):
        options = json.loads(self.options.read_text())
        options['adoption_approvals'] = [{
            'path': name,
            'repository_fingerprint': managed.fingerprint(self.repo / name),
            'source_fingerprint': managed.fingerprint(self.source / name),
        }]
        self.options.write_text(json.dumps(options))

    def test_migration_adopts_identical_files_preserves_arbitrary_git_files(self):
        self.put('configuration.yaml')
        for name in ['configuration.yaml', 'new-tool/plan.yaml', 'themes/dev/README.md',
                     'openspec/.openspec.yaml', '.github/workflows/check.yml', '.gitignore']:
            self.put(name, destination=True)
        self.commit_fixture()
        self.backup()
        self.assertEqual(set(self.manifest()['files']), {'configuration.yaml'})
        self.assertTrue((self.repo / 'new-tool/plan.yaml').exists())
        self.assertTrue((self.repo / 'themes/dev/README.md').exists())
        self.assertTrue((self.repo / 'openspec/.openspec.yaml').exists())
        head = self.git('rev-parse', 'HEAD')
        self.backup()
        self.assertEqual(self.git('rev-parse', 'HEAD'), head)

    def test_conflicting_adoption_requires_exact_content_approval(self):
        self.put('configuration.yaml', 'Git version\n', destination=True)
        self.commit_fixture()
        self.put('configuration.yaml', 'HA version\n')
        result = self.assert_clean_failure()
        self.assertIn('Adoption requires explicit approval', result.stderr)
        self.approve('configuration.yaml')
        self.put('configuration.yaml', 'HA changed after approval\n')
        self.assert_clean_failure()
        self.approve('configuration.yaml')
        self.backup()
        self.assertEqual((self.repo / 'configuration.yaml').read_text(), 'HA changed after approval\n')
        self.assertEqual(set(self.manifest()['files']), {'configuration.yaml'})
        # Approval is fingerprint-bound and grants no permission for later Git changes.
        self.put('configuration.yaml', 'New Git work\n', destination=True)
        self.commit_fixture()
        self.assert_clean_failure()

    def test_conflict_preflight_prevents_other_copies_or_deletions(self):
        self.put('old.yaml')
        self.backup()
        self.put('z-conflict.yaml', 'Git\n', destination=True)
        self.commit_fixture()
        (self.source / 'old.yaml').unlink()
        self.put('a-new.yaml')
        self.put('z-conflict.yaml', 'HA\n')
        self.assert_clean_failure()
        self.assertTrue((self.repo / 'old.yaml').exists())
        self.assertFalse((self.repo / 'a-new.yaml').exists())

    def test_missing_manifest_never_infers_deleted_source_ownership(self):
        self.put('old.yaml')
        self.backup()
        (self.repo / managed.MANIFEST).unlink()
        self.commit_fixture()
        (self.source / 'old.yaml').unlink()
        self.put('new.yaml')
        self.backup()
        self.assertTrue((self.repo / 'old.yaml').exists())
        self.assertEqual(set(self.manifest()['files']), {'new.yaml'})

    def test_invalid_manifests_abort_without_changes(self):
        self.put('old.yaml')
        self.backup()
        (self.source / 'old.yaml').unlink()
        self.put('new.yaml')
        bad = ['', '{}', '{', '{"version":1,"files":[]}',
               '{"version":1,"version":1,"files":{}}',
               json.dumps({'version': 2, 'files': {}}),
               json.dumps({'version': True, 'files': {}}),
               json.dumps({'version': 1, 'files': {'../outside': {'fingerprint': '0' * 64}}}),
               json.dumps({'version': 1, 'files': {'old.yaml': {'fingerprint': 'bad'}}}),
               json.dumps({'version': 1, 'files': {'openspec/plan.yaml': {'fingerprint': '0' * 64}}}),
               json.dumps({'version': 1, 'files': {'a': {'fingerprint': '0' * 64},
                                                       'a/b': {'fingerprint': '0' * 64}}})]
        for text in bad:
            with self.subTest(manifest=text):
                (self.repo / managed.MANIFEST).write_text(text)
                self.commit_fixture()
                self.assert_clean_failure()
                self.assertTrue((self.repo / 'old.yaml').exists())
                self.assertFalse((self.repo / 'new.yaml').exists())

    def test_manifest_symlink_is_rejected(self):
        self.put('configuration.yaml')
        self.backup()
        (self.repo / managed.MANIFEST).unlink()
        outside = self.root / 'outside.json'
        outside.write_text('{"version":1,"files":{}}')
        (self.repo / managed.MANIFEST).symlink_to(outside)
        self.commit_fixture()
        self.assert_clean_failure()
        self.assertEqual(outside.read_text(), '{"version":1,"files":{}}')

    def test_reserved_paths_cannot_be_adopted_or_overwritten(self):
        for name in ['.github/workflows/check.yaml', '.gitignore', 'openspec/plan.yaml']:
            self.put(name, 'Git\n', destination=True)
            self.put(name, 'HA\n')
        self.put('.ha-backup/managed-files.json', 'source must not control ownership\n')
        self.commit_fixture()
        self.configure(['*'], ['openspec/', '.github/', '.gitignore'])
        self.backup()
        for name in ['.github/workflows/check.yaml', '.gitignore', 'openspec/plan.yaml']:
            self.assertEqual((self.repo / name).read_text(), 'Git\n')
        self.assertEqual(self.manifest(), {'version': 1, 'files': {}})

    def test_source_deletion_keeps_unmanaged_siblings(self):
        self.put('themes/example/theme.yaml')
        self.backup()
        self.put('themes/example/development.yaml', destination=True)
        self.commit_fixture()
        shutil.rmtree(self.source / 'themes')
        self.backup()
        self.assertFalse((self.repo / 'themes/example/theme.yaml').exists())
        self.assertTrue((self.repo / 'themes/example/development.yaml').exists())
        self.assertEqual(self.manifest()['files'], {})

    def test_exclusions_only_delete_owned_files(self):
        self.put('managed.yaml')
        self.backup()
        self.put('unmanaged.yaml', destination=True)
        self.commit_fixture()
        self.configure(['*.yaml'], ['*.yaml'])
        self.backup()
        self.assertFalse((self.repo / 'managed.yaml').exists())
        self.assertTrue((self.repo / 'unmanaged.yaml').exists())
        self.assertTrue((self.source / 'managed.yaml').exists())

    def test_narrowing_and_reexpanding_allowlist_preserves_then_deletes(self):
        self.put('one.yaml')
        self.put('two.yaml')
        self.backup()
        (self.source / 'two.yaml').unlink()
        self.configure(['one.yaml'], [])
        self.backup()
        self.assertIn('two.yaml', self.manifest()['files'])
        self.assertTrue((self.repo / 'two.yaml').exists())
        self.configure(['*.yaml'], [])
        self.backup()
        self.assertNotIn('two.yaml', self.manifest()['files'])
        self.assertFalse((self.repo / 'two.yaml').exists())

    def test_git_edit_blocks_deletion_and_exclusion_cleanup(self):
        for exclusion in ([], ['*.yaml']):
            with self.subTest(exclusion=exclusion):
                self.configure([], [])
                self.put('configuration.yaml')
                # Identical adoption on the second iteration after manual repair.
                self.put('configuration.yaml', destination=True)
                self.commit_fixture()
                self.backup()
                (self.source / 'configuration.yaml').unlink()
                self.put('configuration.yaml', 'New Git-side work\n', destination=True)
                self.commit_fixture()
                self.configure([], exclusion)
                self.assert_clean_failure()

    def test_git_mode_change_blocks_deletion(self):
        self.put('script.sh')
        self.backup()
        (self.repo / 'script.sh').chmod(0o755)
        self.commit_fixture()
        (self.source / 'script.sh').unlink()
        self.assert_clean_failure()
        self.assertTrue((self.repo / 'script.sh').stat().st_mode & 0o100)

    def test_invalid_approval_cannot_authorize_adoption(self):
        self.put('configuration.yaml', 'Git\n', destination=True)
        self.commit_fixture()
        self.put('configuration.yaml', 'HA\n')
        options = json.loads(self.options.read_text())
        for approval in [True, [{'path': '*', 'repository_fingerprint': '0' * 64,
                                'source_fingerprint': '0' * 64}],
                         [{'path': 'configuration.yaml', 'repository_fingerprint': 'bad',
                           'source_fingerprint': '0' * 64}]]:
            options['adoption_approvals'] = approval
            self.options.write_text(json.dumps(options))
            self.assert_clean_failure()

    def test_missing_source_and_rsync_failure_do_not_delete(self):
        self.put('configuration.yaml')
        self.backup()
        shutil.rmtree(self.source)
        self.assert_clean_failure()
        self.source.mkdir()
        self.put('new.yaml')
        self.assert_clean_failure(fail_sync=True)
        self.assertTrue((self.repo / 'configuration.yaml').exists())
        self.assertFalse((self.repo / 'new.yaml').exists())

    def test_file_directory_collisions_never_remove_unmanaged_contents(self):
        self.put('folder/git.yaml', destination=True)
        self.commit_fixture()
        self.put('folder', 'HA file\n')
        self.assert_clean_failure()
        self.assertTrue((self.repo / 'folder/git.yaml').exists())
        (self.source / 'folder').unlink()
        self.put('parent', 'Git file\n', destination=True)
        self.commit_fixture()
        self.put('parent/child.yaml')
        self.assert_clean_failure()
        self.assertEqual((self.repo / 'parent').read_text(), 'Git file\n')

    def test_destination_symlink_parent_cannot_escape_repository(self):
        outside = self.root / 'outside'
        outside.mkdir()
        (outside / 'file.yaml').write_text('outside\n')
        (self.repo / 'linked').symlink_to(outside, target_is_directory=True)
        self.commit_fixture()
        self.put('linked/file.yaml', 'HA\n')
        self.assert_clean_failure()
        self.assertEqual((outside / 'file.yaml').read_text(), 'outside\n')

    def test_symlinks_modes_and_unusual_filenames(self):
        names = ['file with spaces.yaml', '-leading.yaml', 'line\nbreak.yaml']
        for name in names:
            self.put(name)
        self.put('executable.sh', '#!/bin/sh\n')
        (self.source / 'executable.sh').chmod(0o755)
        (self.source / 'link.yaml').symlink_to('file with spaces.yaml')
        self.backup()
        self.assertTrue((self.repo / 'link.yaml').is_symlink())
        self.assertTrue((self.repo / 'executable.sh').stat().st_mode & 0o100)
        self.assertEqual(set(self.manifest()['files']), set(names + ['link.yaml', 'executable.sh']))
        for name in names + ['link.yaml', 'executable.sh']:
            (self.source / name).unlink()
        self.backup()
        self.assertEqual(self.manifest()['files'], {})

    def test_ignored_files_are_not_copied_or_owned(self):
        self.put('.gitignore', 'ignored.yaml\n', destination=True)
        self.commit_fixture()
        self.put('ignored.yaml')
        self.put('configuration.yaml')
        self.backup()
        self.assertFalse((self.repo / 'ignored.yaml').exists())
        self.assertNotIn('ignored.yaml', self.manifest()['files'])

    def test_ignored_manifest_aborts_before_copying(self):
        self.put('.gitignore', '.ha-backup/\n', destination=True)
        self.commit_fixture()
        self.put('configuration.yaml')
        self.assert_clean_failure()
        self.assertFalse((self.repo / 'configuration.yaml').exists())

    def paused_backup(self, stage):
        marker = self.root / 'backup-paused'
        release = self.root / 'backup-release'
        marker.unlink(missing_ok=True)
        release.unlink(missing_ok=True)
        process = self.backup(background=True, extra_env={
            'PAUSE_STAGE': stage, 'PAUSE_MARKER': str(marker), 'PAUSE_RELEASE': str(release),
        }, action='''
git() {
    if [ "$1" = "$PAUSE_STAGE" ]; then
        echo "$BASHPID" > "$PAUSE_MARKER"
        while [ ! -f "$PAUSE_RELEASE" ]; do sleep 0.05; done
    fi
    command git "$@"
}
do_backup test''')

        def cleanup():
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
            process.communicate(timeout=10)
        self.addCleanup(cleanup)
        deadline = time.monotonic() + 10
        while not marker.exists():
            if process.poll() is not None:
                self.fail(f'Backup exited before pause: {process.communicate()}')
            if time.monotonic() >= deadline:
                self.fail('Backup did not reach pause')
            time.sleep(0.01)
        return process, release

    def test_backup_lock_blocks_concurrent_execution_through_push(self):
        self.put('configuration.yaml')
        self.backup()
        for stage in ('fetch', 'push'):
            with self.subTest(stage=stage):
                self.put('configuration.yaml', stage + '\n')
                process, release = self.paused_backup(stage)
                result = self.assert_clean_failure()
                self.assertIn('Another backup is running', result.stdout + result.stderr)
                release.touch()
                stdout, stderr = process.communicate(timeout=10)
                self.assertEqual(process.returncode, 0, stdout + stderr)
                self.backup()
                self.assertEqual((self.repo / 'configuration.yaml').read_text(), stage + '\n')

    def test_backup_lock_recovers_after_termination_and_retries_pending_push(self):
        self.put('configuration.yaml')
        self.backup()
        # A stale directory left by the previous locking implementation must
        # not prevent migration to the kernel-managed lock.
        (self.root / 'repository.backup-lock').mkdir()
        for termination in (signal.SIGTERM, signal.SIGKILL):
            with self.subTest(termination=termination):
                hook = self.root / 'remote/hooks/pre-receive'
                hook.write_text('#!/bin/sh\nexit 1\n')
                hook.chmod(0o755)
                self.put('configuration.yaml', f'pending {termination}\n')
                self.assertNotEqual(self.backup(success=False).returncode, 0)
                pending = self.git('rev-parse', 'HEAD')
                hook.unlink()
                process, _ = self.paused_backup('fetch')
                os.killpg(process.pid, termination)
                process.communicate(timeout=10)
                self.assertNotEqual(process.returncode, 0)
                self.backup()
                self.assertEqual(self.git('rev-parse', 'HEAD'), pending)
                branch = self.git('symbolic-ref', '--short', 'HEAD')
                remote = subprocess.check_output([
                    'git', '--git-dir', str(self.root / 'remote'),
                    'rev-parse', f'refs/heads/{branch}'], text=True).strip()
                self.assertEqual(remote, pending)

    def test_empty_bootstrap_creates_manifest_without_deleting_unmanaged_files(self):
        self.put('unmanaged.yaml', destination=True)
        self.commit_fixture()
        self.assertEqual(managed.read_manifest(self.repo), ({}, False))
        for includes, excludes in (([], []), (['*.yaml'], ['*.yaml']), (['*.txt'], [])):
            with self.subTest(includes=includes, excludes=excludes):
                if (self.repo / managed.MANIFEST).exists():
                    (self.repo / managed.MANIFEST).unlink()
                    self.commit_fixture()
                self.configure(includes, excludes)
                if excludes or includes:
                    self.put('excluded.yaml')
                else:
                    (self.source / 'excluded.yaml').unlink(missing_ok=True)
                self.backup()
                self.assertTrue((self.repo / managed.MANIFEST).is_file())
                self.assertEqual(self.manifest(), {'version': 1, 'files': {}})
                self.assertEqual(managed.read_manifest(self.repo), ({}, True))
                self.assertEqual((self.repo / 'unmanaged.yaml').read_text(), 'fixture\n')
                head = self.git('rev-parse', 'HEAD')
                self.backup()
                self.assertEqual(self.git('rev-parse', 'HEAD'), head)

    def test_empty_repository_bootstrap_commits_empty_manifest(self):
        self.backup()
        self.assertEqual(self.manifest(), {'version': 1, 'files': {}})
        self.assertEqual(self.git('ls-files'), managed.MANIFEST)
        self.assertEqual(self.git('status', '--porcelain'), '')

    def test_fingerprint_streams_regular_files_without_changing_digest(self):
        content = b'large asset\0' * 300000
        self.put('asset')
        path = self.source / 'asset'
        path.chmod(0o644)

        class BoundedReader(io.BytesIO):
            def read(self, size=-1):
                if not 0 < size <= 1024 * 1024:
                    raise AssertionError(f'Unbounded hashing read: {size}')
                return super().read(size)

        for executable, kind in ((False, b'100644'), (True, b'100755')):
            with self.subTest(executable=executable):
                path.chmod(0o755 if executable else 0o644)
                with patch.object(type(path), 'open', return_value=BoundedReader(content)):
                    self.assertEqual(managed.fingerprint(path),
                                     hashlib.sha256(kind + b'\0' + content).hexdigest())
