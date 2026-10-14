> **Filtering test fork — v1.0.14-test.1**
>
> Add `https://github.com/pbrickles/ha-git-backup` in Home Assistant:
> Settings → Add-ons → Add-on Store → ⋮ → Repositories. Install
> **Git Config Backup (Filtering Test)** from this repository. Home Assistant
> builds the add-on locally from the patched source; the initial installation
> may take a few minutes.
>
> Stop the upstream add-on before starting this test add-on. Copy its settings
> manually; this separate repository has separate add-on data and SSH keys.
> Add the test add-on's public SSH key to your Git provider if using SSH.
> Use a dedicated backup branch (for example `filtering-test`) for testing.
> Set `backup_on_start: false` while configuring filters, then trigger a manual
> backup after reviewing them. If your saved exclusions contain `.storage/*`,
> remove it to retain Lovelace and core.config backups.
>
> See [filtering documentation](git-backup/DOCS.md#filtering-semantics) for
> precedence, allowlists, and removal of previously tracked excluded files.

# Home Assistant Git Config Backup

[![Build and Publish](https://github.com/sttts/ha-git-backup/actions/workflows/build.yaml/badge.svg)](https://github.com/sttts/ha-git-backup/actions/workflows/build.yaml)

Home Assistant add-on that automatically commits your configuration files to a Git repository with SSH key generation, real-time file watching, and a web UI for setup.

## Features

- **Auto SSH Key Generation** - No manual key management, just copy the public key from the Web UI
- **Real-time File Watching** - Optional inotify-based instant commits on file changes
- **Scheduled Backups** - Configurable interval from 1-168 hours
- **Smart Exclusions** - Databases, logs, and cache files excluded by default
- **Web UI** - View status, copy SSH key, trigger manual backups
- **Multi-arch** - Supports armhf, armv7, aarch64, amd64, i386

## Installation

1. In Home Assistant, go to **Settings → Add-ons → Add-on Store**
2. Click **⋮** (menu) → **Repositories**
3. Add this repository URL:
   ```
   https://github.com/sttts/ha-git-backup
   ```
4. Find "Git Config Backup" and click **Install**

## Quick Start

1. Start the add-on
2. Open the **Web UI** (from the add-on page)
3. Copy the **SSH public key** displayed
4. Add the key to your Git provider:
   - **GitHub**: Settings → SSH and GPG keys → New SSH key
   - **GitLab**: Preferences → SSH Keys → Add new key
5. Create a **private repository** for your backups
6. Configure the add-on with your repository URL:
   ```
   git@github.com:YOUR_USERNAME/ha-config-backup.git
   ```
7. Restart the add-on

## Configuration

| Option | Default | Description |
|--------|---------|-------------|
| `repository_url` | *(required)* | Git repository URL (SSH or HTTPS) |
| `branch` | `main` | Git branch |
| `backup_interval_hours` | `24` | Hours between backups (0 to disable) |
| `backup_on_start` | `true` | Backup when add-on starts |
| `watch_realtime` | `false` | Commit on file changes (inotify) |
| `watch_min_interval` | `30` | Minimum seconds between realtime commits |
| `watch_max_interval` | `1800` | Max backoff interval (loop protection) |
| `watch_burst_limit` | `5` | Allow this many rapid backups before backoff |
| `auto_generate_ssh_key` | `true` | Auto-generate SSH key pair |
| `commit_message` | `Backup: {files}` | Template with `{date}` and `{files}` placeholders |

See [full documentation](git-backup/DOCS.md) for all options including authentication, exclude patterns, and examples.

## What Gets Backed Up?

**Included:** YAML configs, JSON, scripts, blueprints, custom_components, themes, www

**Excluded:** Databases (*.db), logs, TTS cache, backups folder, .cloud

## Documentation

- [Full Documentation](git-backup/DOCS.md)
- [Design Document](doc/DESIGN.md)
- [Changelog](git-backup/CHANGELOG.md)

## License

Apache License 2.0
