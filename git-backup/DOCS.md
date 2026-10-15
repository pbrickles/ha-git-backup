# Git Config Backup

Automatically backup your Home Assistant configuration files to a Git repository.

## Why use this add-on?

- **Version History**: Track all changes to your configuration over time
- **Easy Recovery**: Restore any previous configuration version
- **Off-site Backup**: Your configuration is safely stored in the cloud
- **Meaningful Diffs**: See exactly what changed between versions (unlike binary backups)

## Quick Start (SSH - Recommended)

The easiest way to get started:

1. **Install and start** the add-on
2. **Open the Web UI** from the add-on page
3. **Copy the SSH public key** displayed
4. **Add the key** to your Git provider:
   - GitHub: Settings → SSH and GPG keys → New SSH key
   - GitLab: Preferences → SSH Keys → Add new key
5. **Create a private repository** on your Git provider
6. **Configure** the repository URL in the add-on settings:
   ```
   git@github.com:YOUR_USERNAME/ha-config-backup.git
   ```
7. **Restart** the add-on

That's it! The add-on will automatically backup your configuration.

## Authentication Methods

### Option 1: Auto-generated SSH Key (Recommended)

The simplest method. The add-on generates an SSH key pair automatically.

1. Set `auto_generate_ssh_key: true` (default)
2. Copy the public key from the Web UI
3. Add it to your Git provider
4. Use SSH URL format: `git@github.com:user/repo.git`

### Option 2: Your Own SSH Key

If you have an existing SSH key:

1. Set `auto_generate_ssh_key: false`
2. Paste your private key into the `ssh_key` field (include BEGIN/END lines)
3. Use SSH URL format: `git@github.com:user/repo.git`

### Option 3: HTTPS with Token

For HTTPS authentication:

1. Create a Personal Access Token on your Git provider:
   - GitHub: Settings → Developer settings → Personal access tokens → Generate new token (with `repo` scope)
   - GitLab: Preferences → Access Tokens → Add new token (with `write_repository` scope)
2. Configure:
   - `repository_url`: `https://github.com/user/repo.git`
   - `username`: Your username
   - `password`: Your token (not your password!)

## Configuration Reference

### Repository Settings

| Option | Default | Description |
|--------|---------|-------------|
| `repository_url` | *(required)* | Git repository URL. Use SSH format (`git@github.com:user/repo.git`) or HTTPS (`https://github.com/user/repo.git`) |
| `branch` | `main` | Git branch to use for backups |

### Branch synchronization and push retries

At setup and before every backup, the add-on checks out the configured branch
and fetches its current remote tip. Existing local branches are retained; a
remote-only branch gets a local tracking branch. If the branch does not exist
on either side, it starts from the current committed HEAD (or empty history in
a new repository) and is published on the first successful backup with commits.

Remote advances are fast-forwarded when possible. Diverged branches are merged
with a merge commit, preserving both histories. A conflicting merge is aborted
and reported as an error; resolve the divergence manually before retrying.
Unrelated histories and rejected remote-tracking updates also stop the backup.
No force-push, automatic stash, rebase, or history reset is performed.

Uncommitted tracked or untracked changes and unfinished Git operations stop the
backup before branch switching or copying. Commit or resolve that work manually.
A failed push retains local commits. Every subsequent successful synchronization
attempts to push them, even if no files have changed since the last backup.
If the remote advances between fetch and push, the rejected push is reported;
the next backup fetches and integrates the new commits before retrying.

Remote commits are integrated before managed configuration synchronization.
Selected source files are synchronized subject to ownership and conflict checks;
source deletions apply only to verified managed files. Repository-owned files
remain protected, including changes fetched from GitHub.

Commit author name and email are set in the backup repository itself, so they
also apply to merge commits. Git's global configuration uses
`/data/gitconfig` (or an existing `GIT_CONFIG_GLOBAL` override), allowing Git to
operate when the add-on environment has no `HOME`. SSH and HTTPS credential
selection are otherwise unchanged.

### Authentication

| Option | Default | Description |
|--------|---------|-------------|
| `auto_generate_ssh_key` | `true` | Automatically generate an ED25519 SSH key pair. The public key is shown in the Web UI |
| `ssh_key` | | SSH private key (paste entire key including `-----BEGIN/END-----` lines). Only needed if `auto_generate_ssh_key` is false |
| `username` | | Username for HTTPS authentication |
| `password` | | Password or Personal Access Token for HTTPS authentication |

### Commit Settings

| Option | Default | Description |
|--------|---------|-------------|
| `commit_message` | `Backup: {files}` | Commit message template. Placeholders: `{date}` for timestamp, `{files}` for changed file names |
| `commit_user_name` | `Home Assistant` | Git author name for commits |
| `commit_user_email` | | Git author email for commits |

**Commit Message Examples:**

```yaml
# Default - shows changed files
commit_message: "Backup: {files}"
# Result: "Backup: configuration.yaml, automations.yaml (+2 more)"

# With timestamp
commit_message: "{date}: {files}"
# Result: "2025-01-21 14:30:00: configuration.yaml, scripts.yaml"

# Simple timestamp only
commit_message: "Backup {date}"
# Result: "Backup 2025-01-21 14:30:00"
```

### Backup Schedule

| Option | Default | Description |
|--------|---------|-------------|
| `backup_interval_hours` | `24` | Hours between automatic backups. Set to `0` to disable scheduled backups |
| `backup_on_start` | `true` | Perform a backup when the add-on starts |
| `cron_schedule` | | Optional cron expression for custom schedules (e.g., `0 2 * * *` for 2 AM daily) |

### Real-time File Watching

Enable real-time backups that trigger when files change:

| Option | Default | Description |
|--------|---------|-------------|
| `watch_realtime` | `false` | Enable inotify-based file watching for instant commits |
| `watch_min_interval` | `30` | Minimum seconds between commits (5-300) |
| `watch_max_interval` | `1800` | Maximum backoff interval in seconds (60-3600). Prevents commit loops |
| `watch_burst_limit` | `5` | Allow this many rapid backups before backing off (1-50) |

**How the burst and backoff works:**

1. **Normal editing**: When you edit files, the add-on commits at `watch_min_interval` (default 30s)
2. **Burst allowance**: If you make many quick edits, the first `watch_burst_limit` rapid backups (default 5) proceed normally
3. **Backoff**: After exceeding the burst limit, the interval increases by 1.5x for each subsequent rapid backup:
   ```
   Backup 6:  30s × 1.5¹ = 45s
   Backup 7:  30s × 1.5² = 68s
   Backup 8:  30s × 1.5³ = 101s
   ...continues up to watch_max_interval (30min)
   ```
4. **Reset**: After a calm period (4× min interval = 2 minutes by default), everything resets

This design allows normal editing activity while preventing infinite commit loops if something keeps modifying files.

### File Patterns

| Option | Default | Description |
|--------|---------|-------------|
| `exclude_patterns` | *(see below)* | Gitignore-style patterns for files to exclude |
| `include_patterns` | *(see below)* | Patterns for files to include |

### Filtering semantics

File selection is enforced by rsync before Git staging, independently of
`.gitignore`. Exclusions always take precedence over inclusions. Built-in
protections cannot be overridden by an inclusion.

- An empty or missing `include_patterns` list backs up all files except configured
  exclusions and built-in protections.
- A non-empty list is an allowlist. Only matching files are copied. Parent
  directories are traversed automatically; unmatched empty directories may be
  created but Git does not track them.
- `themes/*`, `custom_components/*`, and similar patterns include the entire
  directory tree, including files several levels deep. A trailing `/` also
  includes a complete directory tree.
- Patterns without a slash, such as `*.yaml`, match names at any depth. Patterns
  containing a slash are relative to `/config`; a leading `/` anchors a pattern
  at that root. A trailing `/` on an exclusion excludes a directory and its
  descendants at any depth when no other slash is present.
- Patterns use rsync wildcards: `*`, `?`, character classes, and `**` for matching
  across directory boundaries. Quote wildcard patterns in YAML. Spaces are
  literal and supported. These are individual patterns, not `.gitignore` lines:
  comments, negation in `exclude_patterns`, and ordered re-inclusion are not
  supported. For compatibility, a leading `!` in `include_patterns` is stripped
  and treated as an inclusion, as intended by the old storage defaults.

The Lovelace `.storage/lovelace*` files and `.storage/core.config` are included
alongside any allowlist. Other `.storage` contents remain protected. Explicit
user exclusions, including `.storage/*`, override these exceptions.

**Upgrade consideration:** Older installations may retain `.storage/*` in their
configured exclusion list. Remove that entry to retain Lovelace and core.config
backups; the built-in storage restriction already protects all other storage
files. New defaults omit this conflicting entry. Inclusion patterns previously
had no effect; enabling them now means files outside the configured allowlist
will stop updating.

### Managed files, deletions, and migration

The add-on copies the filtered `/config` contents into disposable staging. Rsync
never runs `--delete` against the Git repository. A Git-tracked ownership manifest
at `.ha-backup/managed-files.json` authorizes exact file updates and deletions.
Each entry fingerprints the file's bytes and Git-relevant mode. The manifest is
committed in the same backup commit as configuration changes, and follows the
configured branch through fresh clones, remote synchronization, and push retries.
Do not hand-edit it to claim ownership of repository-only files.

- New selected files are copied and recorded as managed. Selected existing files
  with identical contents and mode are adopted automatically.
- A selected existing file with conflicting contents requires explicit adoption
  approval (below). The whole plan is checked before files are changed.
- Only managed files whose destination still matches the recorded fingerprint
  may be deleted. A source deletion deletes a managed backup while the path is
  selected. Explicit exclusions and built-in exclusions remove only verified
  managed backups; unowned repository files matching an exclusion are preserved.
- Narrowing an allowlist retains older managed backups outside that allowlist,
  including their ownership records. Re-expanding the allowlist resumes updates
  and reflects source deletions. Explicit exclusions take precedence.
- Git-side changes conflicting with a managed update or deletion stop the backup.
  Review and reconcile the Git and Home Assistant versions before retrying.
  Matching the source version is sufficient for a safe managed update.
- Only empty parent directories are removed after deleting managed files. No
  recursive directory replacement is allowed; file/directory collisions stop
  the backup, preserving unmanaged descendants.

The first backup without a manifest performs no absence-based deletions. It
adopts matching selected files, copies new ones, and preserves destination-only
files, even when they match broad inclusion or exclusion patterns. Files already
removed from `/config` before migration cannot be safely identified as old HA
backups and may require one-time manual cleanup. A removed manifest returns to
this conservative bootstrap behavior. A successful bootstrap always commits a
valid manifest, even when its owned file set is empty; an empty manifest grants
no deletion authority. An invalid manifest stops the backup without copying or
deleting configuration files. Unsupported versions, duplicate
keys, invalid fingerprints, unsafe paths, reserved paths, symlink manifests, and
overlapping file/directory entries are rejected. Existing deletions in branch
history are not repaired automatically.

Root `.github/`, `.gitignore`, `openspec/`, and `.ha-backup/` are reserved for the
repository owner and app metadata. Git metadata named `.git` is also reserved at
any depth. Source copies cannot overwrite these paths, inclusions cannot adopt
them, and exclusions cannot delete them. Other repository-only files are
preserved automatically because the app has no ownership record for them; users
do not need to enumerate all development directories.

Git ignore rules remain an additional restriction: ignored untracked files are
neither copied nor owned. The manifest must be permitted by `.gitignore`, or the
backup stops before changing configuration files. Tracked files remain tracked
regardless of later ignore rules. Exclusions do not purge historical Git commits.

Source enumeration or rsync failures prevent all planned changes. The source
must exist as a directory separate from the destination. An accessible but
unexpectedly empty mount cannot be distinguished reliably from intentional
source removals; verify mount health before running a backup. Symlinks are
backed up as links, never traversed to adopt external contents. Destination
symlink parents and file/directory collisions are rejected.

Backups are serialized across startup, watcher, and manual triggers using
`flock` on `/data/repository.backup.lock`. The lock is held through branch
synchronization, commit, and push, and the OS releases it when the backup and
its active child processes exit, including after forced termination. The lock
file stays on disk; do not remove it. Legacy `.backup-lock` directories are no
longer used and cannot block backups. Do not reset or clean the backup checkout.
Partial application failures leave work for manual review; the existing
dirty-worktree check prevents automatic retries
from committing it. A failed push retains a clean local commit and is retried
normally, even when no new configuration changes are found.

### Approving a conflicting adoption

An error identifies the exact path, `repository_fingerprint`, and
`source_fingerprint`. Review both versions, then add that exact triple to the
add-on options to approve replacing the Git version with the source version:

```yaml
adoption_approvals:
  - path: configuration.yaml
    repository_fingerprint: "<64-character fingerprint from the error>"
    source_fingerprint: "<64-character fingerprint from the error>"
```

These are SHA-256 fingerprints of `Git-mode + NUL + bytes` (or symlink target
bytes), not ordinary file-only checksums. Approvals use exact relative paths;
no wildcard adoption is supported. Both fingerprints must still match when the
backup runs. A stale approval cannot approve different contents. Remove the
entry after successful adoption. Reserved paths and file/directory collisions
cannot be approved. The default `adoption_approvals: []` approves no conflicts.


Synchronization errors abort the backup before staging or committing.

## What Gets Backed Up?

### Included by Default

- Configuration files: `*.yaml`, `*.yml`, `*.json`
- Scripts: `*.py`, `*.sh`, `*.js`
- Directories: `scripts/`, `blueprints/`, `custom_components/`, `themes/`, `www/`
- Lovelace dashboards: `.storage/lovelace*`
- Core config: `.storage/core.config`

### Excluded by Default

| Excluded | Reason |
|----------|--------|
| `*.db`, `*.db-shm`, `*.db-wal` | Database files are large, binary, change constantly |
| `*.log`, `home-assistant.log*` | Log files are temporary, not needed for recovery |
| `tts/` | Text-to-speech cache, regenerated automatically |
| `backups/` | Use Home Assistant's backup system for full backups |
| `.cloud/` | Cloud connection data, recreated on login |
| `.storage/*` (except Lovelace and core.config) | Most storage files are regenerated or contain transient state |

Built-in protections also exclude Git metadata, Python and temporary caches,
`backup/`, Node-RED credentials (`flows_cred.json`), ESPHome secrets
(`esphome/secrets.yaml`), common audio/video files, IDE files, swap files, and OS
metadata. These retain the protections previously supplied by the generated
`.gitignore`, now enforced during synchronization.

### Default Exclude Patterns

```yaml
exclude_patterns:
  - "*.db"
  - "*.db-shm"
  - "*.db-wal"
  - "*.log"
  - "home-assistant.log*"
  - "OZW_Log.txt"
  - "tts/*"
  - "backups/*"
  - ".cloud/*"
```

### Default Include Patterns

```yaml
include_patterns:
  - "*.yaml"
  - "*.yml"
  - "*.json"
  - "*.js"
  - "*.py"
  - "*.sh"
  - "scripts/*"
  - "blueprints/*"
  - "custom_components/*"
  - "themes/*"
  - "www/*"
  - "!.storage/lovelace*"
  - "!.storage/core.config"
```

## Web UI

The add-on includes a web interface accessible from the Home Assistant sidebar or the add-on page. Features:

- **Status display**: Current backup status, last commit, repository info
- **SSH public key**: Copy the auto-generated public key to add to your Git provider
- **Manual backup**: Trigger a backup immediately

## Example Configurations

### Minimal (SSH with auto-generated key)

```yaml
repository_url: "git@github.com:username/ha-backup.git"
```

### Daily backup with custom message

```yaml
repository_url: "git@github.com:username/ha-backup.git"
branch: "main"
backup_interval_hours: 24
commit_message: "Daily backup: {date}"
```

### Real-time watching

```yaml
repository_url: "git@github.com:username/ha-backup.git"
backup_interval_hours: 0
watch_realtime: true
watch_min_interval: 60
watch_max_interval: 1800
commit_message: "Config update: {files}"
```

### HTTPS with token

```yaml
repository_url: "https://github.com/username/ha-backup.git"
username: "username"
password: "ghp_xxxxxxxxxxxxxxxxxxxx"
backup_interval_hours: 12
```

### GitHub-managed configuration with deployment infrastructure

For a `/config` containing configuration alongside deployment repositories and
SSH keys, use an explicit allowlist and exclusions:

```yaml
repository_url: "git@github.com:username/ha-config-backup.git"
include_patterns:
  - automations.yaml
  - scripts.yaml
  - configuration.yaml
  - blueprints/*
  - custom_components/*
  - themes/*
  - www/*
exclude_patterns:
  - .ha-deploy/
  - .ssh/
  - deploy/
  - secrets.yaml
  - '*.pre-deploy'
  - '*.pub'
```

The deployment directories and keys are excluded even if you later add
`*.yaml` or `*` to the allowlist. Previously managed excluded files are removed
from the branch on the next backup, while remaining in older commits.

### Exclude secrets

```yaml
repository_url: "git@github.com:username/ha-backup.git"
exclude_patterns:
  - "secrets.yaml"
  - "esphome/secrets.yaml"
  - ".storage/auth*"
```

## Security Considerations

### Secrets

Your `secrets.yaml` file **is included** by default. This is intentional because:

1. The repository should be **private**
2. You need secrets to fully restore your configuration
3. Without secrets, your configuration won't work after restore

To exclude secrets, add them to `exclude_patterns`.

### Private Repository

**Always use a private repository!** Your configuration may contain:

- Network information and IP addresses
- Device names and locations
- Automation logic revealing your habits
- API keys and tokens (in secrets.yaml)
- Integration credentials

### SSH Key Security

The auto-generated SSH key is stored in `/data/ssh/` within the add-on's persistent storage. The public key is also copied to `/share/git_backup_ssh_key.pub` for easy access.

## Troubleshooting

### "Failed to push to remote"

- Verify your credentials/SSH key are correct
- Check that the repository exists and you have write access
- For SSH: ensure the public key is added to your Git provider
- For HTTPS: ensure you're using a token, not your password

### "Could not clone"

- The add-on will initialize an empty repo if the remote is empty
- Check the repository URL format is correct
- Verify network connectivity
- For SSH: check the host key is accepted

### No changes detected

- The backup only commits when files actually change
- Check that your files aren't in the exclude patterns
- Verify the files are in the Home Assistant config directory

### Repository growing too large

1. Check if any large files were accidentally included
2. Add more patterns to `exclude_patterns`
3. Consider starting fresh: delete and recreate the repository

### Real-time watching not triggering

- Ensure `watch_realtime: true` is set
- Check that the file type isn't excluded
- The debounce interval may be delaying commits
- Check the add-on logs for "File change detected" messages

## Restoring Configuration

To restore from your Git backup:

1. Clone your repository locally
2. Copy the files to your Home Assistant config directory (`/config/`)
3. Restart Home Assistant

For a fresh installation:

```bash
cd /config
git clone git@github.com:username/ha-backup.git .
```

## API

The add-on provides a simple HTTP API on port 8099 (accessible via Ingress):

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Web UI |
| `/api/status` | GET | JSON status (status, message, last_commit, repository, branch) |
| `/api/ssh-key` | GET | Public SSH key as text |
| `/api/backup` | POST | Trigger a manual backup |

## Support

- [Issue Tracker](https://github.com/sttts/ha-git-backup/issues)
- [Changelog](CHANGELOG.md)
