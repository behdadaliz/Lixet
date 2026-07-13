# Lixet

Lixet is a Linux command-line tool for finding and carefully repairing common configuration problems.

It reads known system configuration files, runs local validation commands when available, and explains what it found before changing anything. Lixet uses deterministic rules only; it does not use AI-generated fixes or guess your system policy.

> **Status:** Lixet `v0.3.0-beta` is beta software. Test it on non-critical systems first and review every repair before applying it.

## What Lixet Can Do

- Scan by service name, alias, file path, or supported directory.
- Detect configuration type from known paths, filenames, parent directories, and bounded content signatures.
- Scan all supported services with `doctor`.
- Show colored unified diffs before any repair.
- Apply only narrow deterministic repairs.
- Keep guarded repairs behind explicit interactive confirmation.
- List protected backups and restore one safely.
- Update an installed copy from published GitHub Releases.

Many findings are report-only because the correct action depends on administrator intent.

## Installation

Lixet requires Linux and Python 3.10 or newer.

```bash
git clone https://github.com/behdadaliz/Lixet.git
cd Lixet
sudo sh install.sh
```

After installation:

```bash
lixet
```

## Basic Usage

```bash
lixet scan ssh
lixet scan /etc/ssh/sshd_config
lixet scan /etc/nginx/nginx.conf
lixet scan /etc/fstab
lixet scan /etc/hosts
lixet scan /etc/systemd/system/example.service
lixet scan /etc/fail2ban
lixet scan /etc/fail2ban/jail.local
lixet scan ./custom-nginx.conf --type nginx
lixet doctor
lixet services
lixet backups
lixet restore <backup-id>
```

Preview repairs without writing:

```bash
lixet scan ssh --dry-run
lixet doctor --dry-run
lixet restore <backup-id> --dry-run
```

Apply supported safe repairs without prompting:

```bash
sudo lixet scan ssh -y
sudo lixet doctor -y
```

`-y` never approves guarded repairs.

Use a custom configuration path for service scans:

```bash
lixet scan nginx --config /path/to/nginx.conf
```

Disable colored output:

```bash
lixet --no-color scan ssh
```

## Type Detection

When `scan` receives a path, Lixet tries to identify the configuration type deterministically. If the result is clear, it scans with that service. If the result is ambiguous in an interactive terminal, Lixet asks you to choose. In non-interactive mode, it refuses to guess and asks for `--type`.

```bash
lixet scan ./custom.conf --type nginx
```

Unknown, empty, binary, unreadable, or broken-symlink targets are handled without tracebacks.

## Doctor

`lixet doctor` scans all registered services. In interactive mode, repair selection supports:

```text
1
1,3,5
1-4
1,3-5,8
a
r
q
```

Report-only findings are explained and skipped. `r` rescans. `q` exits safely.

## Backups And Restore

List protected backups:

```bash
lixet backups
```

Preview a restore:

```bash
lixet restore <backup-id> --dry-run
```

Restore requires an interactive terminal and exact confirmation:

```bash
sudo lixet restore <backup-id>
```

Before restoring an existing target, Lixet creates a new protected backup of the current file so the restore can be undone manually if needed.

## Supported Services

Run `lixet services` for the live registry. This release supports:

| Service | Aliases | Default target |
| --- | --- | --- |
| `ssh` | `sshd`, `openssh` | `/etc/ssh/sshd_config` |
| `nginx` | - | `/etc/nginx/nginx.conf` |
| `ufw` | `firewall` | `/etc/ufw/ufw.conf` |
| `dns` | - | `/etc/resolv.conf` |
| `networking` | `network`, `hosts` | `/etc/hosts` |
| `fail2ban` | `f2b`, `fail2ban-client` | `/etc/fail2ban` |
| `systemd` | - | `/etc/systemd/system` |
| `sudoers` | - | `/etc/sudoers` |
| `fstab` | - | `/etc/fstab` |
| `sysctl` | - | `/etc/sysctl.conf` |

Fail2ban support is conservative: Lixet inspects includes, jails, filters, runtime status, and `fail2ban-client -t` output, but it does not restart Fail2ban, change firewall rules, or rewrite ban policy.

## Safety

- Scans are read-only.
- Repairs require explicit approval unless `-y` is used for supported safe repairs.
- Guarded repairs require typing the exact approval word shown by Lixet.
- Diffs are shown before confirmation.
- Backups are created before writes.
- Lixet does not restart services, change firewall rules, mount filesystems, or apply sysctl values.
- Normal scans do not require internet access.
- `--version` and `--update` contact GitHub Releases.

## Version And Updates

```bash
lixet --version
sudo lixet --update
```

The updater follows the installed release channel and installs the latest compatible published GitHub Release.

## Uninstall

```bash
sudo sh uninstall.sh
```

## Current Limitations

There is no package repository, shell completion, JSON output, backup pruning, backup export, remote backup storage, or automatic service restart support.

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request.

## Support

If Lixet saves you time or helps recover a broken server, you can support the project.

### TON (Gram)

```text
UQANiDCA6hWl7BL0k6iJW9eeJ_BZ207qlrRcK3Fa_K4G_J64
```

## License

Lixet is released under the MIT License. See [LICENSE](LICENSE).
