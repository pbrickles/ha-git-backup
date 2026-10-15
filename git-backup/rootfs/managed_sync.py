#!/usr/bin/env python3
"""Copy selected HA files; remove only files with verified backup ownership.

Rsync owns pattern matching, not deletion authority. The Git-tracked manifest
travels with configuration commits and is read after branch synchronization.
"""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile

MANIFEST = '.ha-backup/managed-files.json'
RESERVED = {'.github', '.gitignore', 'openspec', '.ha-backup'}
DIGEST = re.compile(r'[0-9a-f]{64}\Z')


class SyncError(Exception):
    pass


def reserved(name):
    parts = PurePosixPath(name).parts
    return '.git' in parts or parts[0] in RESERVED


def valid_path(name):
    return (isinstance(name, str) and bool(name) and '\0' not in name
            and not name.startswith('/')
            and all(part not in ('', '.', '..') for part in name.split('/')))


def fingerprint(path):
    """Hash Git-relevant mode plus bytes; never follow a leaf symlink."""
    mode = path.lstat().st_mode
    if stat.S_ISLNK(mode):
        return hashlib.sha256(b'120000\0' + os.fsencode(os.readlink(path))).hexdigest()
    elif stat.S_ISREG(mode):
        kind = b'100755' if mode & stat.S_IXUSR else b'100644'
    else:
        raise SyncError(f'Not a regular file or symlink: {path}')
    digest = hashlib.sha256(kind + b'\0')
    with path.open('rb') as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def safe_path(root, name):
    path = root / name
    for parent in path.parents:
        if parent == root:
            break
        if parent.is_symlink() or (parent.exists() and not parent.is_dir()):
            raise SyncError(f'Unsafe parent or file/directory collision: {name!r}')
    return path


def read_manifest(repo):
    path = safe_path(repo, MANIFEST)
    if not os.path.lexists(path):
        print('[INFO] No ownership manifest: bootstrapping without deletions')
        return {}, False
    try:
        if path.is_symlink() or not path.is_file():
            raise ValueError('manifest must be a regular file')
        def unique_pairs(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError('duplicate JSON key')
                result[key] = value
            return result
        value = json.loads(path.read_text(), object_pairs_hook=unique_pairs)
        if (not isinstance(value, dict) or set(value) != {'version', 'files'}
                or type(value['version']) is not int or value['version'] != 1
                or not isinstance(value['files'], dict)):
            raise ValueError('unsupported manifest schema')
        files = value['files']
        for name, entry in files.items():
            if (not valid_path(name) or reserved(name) or not isinstance(entry, dict)
                    or set(entry) != {'fingerprint'}
                    or not isinstance(entry['fingerprint'], str)
                    or not DIGEST.fullmatch(entry['fingerprint'])):
                raise ValueError(f'invalid ownership entry: {name!r}')
            if any(str(parent) in files for parent in PurePosixPath(name).parents
                   if str(parent) != '.'):
                raise ValueError('overlapping file and directory ownership')
        return files, True
    except (ValueError, OSError, TypeError) as exc:
        raise SyncError(f'Invalid ownership manifest; no files changed: {exc}') from exc


def list_files(root):
    result = set()
    def onerror(exc):
        raise exc
    for parent, dirs, files in os.walk(root, followlinks=False, onerror=onerror):
        for name in dirs[:]:
            path = Path(parent) / name
            if path.is_symlink():
                files.append(name)
                dirs.remove(name)
        for name in files:
            path = Path(parent) / name
            relative = path.relative_to(root).as_posix()
            if not valid_path(relative) or reserved(relative):
                raise SyncError(f'Reserved or invalid source path: {relative!r}')
            fingerprint(path)  # Reject devices and other unsupported entries.
            result.add(relative)
    return result


def snapshot(source, destination, filters):
    destination.mkdir()
    # All transfers target disposable staging, never the repository. No --delete.
    subprocess.run(['rsync', *filters, str(source) + '/', str(destination) + '/'],
                   check=True, stdout=subprocess.DEVNULL)
    return list_files(destination)


def tracked_files(repo):
    data = subprocess.check_output(['git', 'ls-files', '-z'], cwd=repo)
    return {os.fsdecode(name) for name in data.split(b'\0') if name}


def ignored(repo, name):
    result = subprocess.run(['git', 'check-ignore', '-q', '--', name], cwd=repo)
    if result.returncode not in (0, 1):
        raise SyncError('Could not check repository ignore rules')
    return result.returncode == 0


def approvals(options):
    entries = options.get('adoption_approvals', [])
    if not isinstance(entries, list):
        raise SyncError('adoption_approvals must be a list')
    result = {}
    for entry in entries:
        if (not isinstance(entry, dict)
                or set(entry) != {'path', 'repository_fingerprint', 'source_fingerprint'}
                or not valid_path(entry['path']) or reserved(entry['path'])
                or entry['path'] in result
                or any(not isinstance(entry[key], str) or not DIGEST.fullmatch(entry[key])
                       for key in ('repository_fingerprint', 'source_fingerprint'))):
            raise SyncError('Invalid adoption approval; exact paths and fingerprints required')
        result[entry['path']] = entry
    return result


def synchronize(repo, source, options, selection_filters, exclusion_filters):
    repo, source = repo.resolve(), source.resolve()
    if not source.is_dir() or source == repo or source in repo.parents or repo in source.parents:
        raise SyncError('Source must be an accessible directory separate from the repository')
    owned, had_manifest = read_manifest(repo)
    if not isinstance(options, dict):
        raise SyncError('Options must be a JSON object')
    for key in ('include_patterns', 'exclude_patterns'):
        patterns = options.get(key, [])
        if not isinstance(patterns, list) or any(not isinstance(p, str) or '\0' in p for p in patterns):
            raise SyncError(f'{key} must be a list of patterns')
    approved = approvals(options)
    tracked = tracked_files(repo)
    # Ensure metadata can be committed before touching any configuration files.
    if MANIFEST not in tracked and ignored(repo, MANIFEST):
        raise SyncError('Ownership manifest is ignored by Git; allow it before backing up')
    with tempfile.TemporaryDirectory(prefix='ha-backup-') as temporary:
        work = Path(temporary)
        current = snapshot(source, work / 'current', selection_filters)
        # Ask the same rsync filters to classify historical paths, even when
        # their source directories have disappeared. No second glob engine.
        probes = work / 'owned'
        probes.mkdir()
        for name in owned:
            path = probes / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
        selected = snapshot(probes, work / 'selected', selection_filters)
        permitted = snapshot(probes, work / 'permitted', exclusion_filters)
        updates, deletions = [], []
        next_owned = dict(owned)
        for name in sorted(current):
            if name not in tracked and ignored(repo, name):
                continue
            destination = safe_path(repo, name)
            incoming = fingerprint(work / 'current' / name)
            if os.path.lexists(destination):
                existing = fingerprint(destination)
                if name in owned:
                    if existing not in (owned[name]['fingerprint'], incoming):
                        raise SyncError(f'Git-side change conflicts with backup: {name!r}')
                elif existing != incoming:
                    approval = approved.get(name, {})
                    if (approval.get('repository_fingerprint') != existing
                            or approval.get('source_fingerprint') != incoming):
                        raise SyncError(
                            f'Adoption requires explicit approval: {name!r}; '
                            f'repository_fingerprint={existing}; source_fingerprint={incoming}')
                if existing != incoming:
                    updates.append(name)
            else:
                updates.append(name)
            next_owned[name] = {'fingerprint': incoming}
        for name in sorted(owned.keys() - current):
            if name not in selected and name in permitted:
                continue  # Narrowed allowlist retains ownership and old contents.
            destination = safe_path(repo, name)
            if os.path.lexists(destination):
                if fingerprint(destination) != owned[name]['fingerprint']:
                    raise SyncError(f'Git-side change blocks deletion: {name!r}')
                deletions.append(name)
            del next_owned[name]
        # Validate the entire plan before applying any file changes. Never
        # replace directories recursively, including directories of unknown files.
        for name in updates:
            safe_path(repo, name)
        manifest_path = safe_path(repo, MANIFEST)
        for name in deletions:
            destination = safe_path(repo, name)
            if fingerprint(destination) != owned[name]['fingerprint']:
                raise SyncError(f'File changed while preparing deletion: {name!r}')
            destination.unlink()
            parent = (repo / name).parent
            while parent != repo:
                try:
                    parent.rmdir()  # Empty parents only; unmanaged contents survive.
                except OSError:
                    break
                parent = parent.parent
        for name in updates:
            destination = repo / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            incoming = work / 'current' / name
            if os.path.lexists(destination):
                destination.unlink()
            if incoming.is_symlink():
                destination.symlink_to(os.readlink(incoming))
            else:
                shutil.copy2(incoming, destination)
        if next_owned != owned or not had_manifest:
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            text = json.dumps({'version': 1, 'files': next_owned}, indent=2, sort_keys=True) + '\n'
            with tempfile.NamedTemporaryFile(mode='w', dir=manifest_path.parent,
                                             prefix='.managed-', delete=False) as handle:
                temporary_manifest = Path(handle.name)
                handle.write(text)
            try:
                temporary_manifest.replace(manifest_path)
            finally:
                temporary_manifest.unlink(missing_ok=True)
        print(f'[INFO] Managed synchronization: {len(updates)} updates, '
              f'{len(deletions)} verified deletions, {len(next_owned)} owned files')


def main():
    # Shell passes two already-compiled rsync argument arrays. The count avoids
    # reparsing shell syntax or changing rsync wildcard semantics.
    repo, source, config, count, *filters = sys.argv[1:]
    count = int(count)
    try:
        synchronize(Path(repo), Path(source), json.loads(Path(config).read_text()),
                    filters[:count], filters[count:])
    except (SyncError, OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f'[ERROR] Managed synchronization failed: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
