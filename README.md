# Lixet

> The First-Aid Kit for Broken Linux Servers.

Lixet is a lightweight Linux command-line tool that detects, explains, and safely repairs common configuration problems.

It is deterministic by design. Lixet does not guess, does not use AI for repairs, and does not rewrite whole configuration files. It applies small, explicit fixes only after showing the problem and asking for approval.

Lixet is currently in alpha. Review every proposed repair before applying it on important systems.

---

# Installation

```bash
git clone https://github.com/behdadaliz/Lixet.git
cd Lixet
sudo sh install.sh
```

After installation, use:

```bash
lixet scan ssh
lixet doctor
```

To update Lixet later:

```bash
sudo lixet --update
```

To uninstall:

```bash
sudo sh uninstall.sh
```

---

# Commands

## Scan

Scan one service:

```bash
lixet scan ssh
lixet scan nginx
lixet scan ufw
lixet scan dns
lixet scan networking
lixet scan systemd
```

When issues are found, Lixet lets you choose one problem number, choose all repairable problems, or skip repair.

Preview repairs without changing files:

```bash
lixet scan ssh --dry-run
```

Disable colored output:

```bash
lixet --no-color scan ssh
```

Show the latest version name from GitHub:

```bash
lixet --version
```

Apply supported repairs without prompting:

```bash
lixet scan ssh -y
```

## Doctor

Scan all supported services:

```bash
lixet doctor
```

Lixet lists detected problems and lets you choose what to repair.

## Update

Update the installed copy:

```bash
sudo lixet --update
```

---

# How Repair Works

For every supported repair, Lixet follows the same flow:

1. Inspect the service configuration.
2. Detect deterministic issues.
3. Explain the problem and location.
4. Show the exact planned change.
5. Ask before applying the fix.
6. Create a backup.
7. Apply the repair safely.
8. Verify the result when a service verifier is available.

If verification fails, Lixet restores the original file from backup.

Example repair prompt:

```text
1. [HIGH] ssh - SSH_INVALID_PORT
  Problem: Invalid Port value 'nope'. Must be an integer between 1 and 65535.
  Location: /etc/ssh/sshd_config:1
  Repair: replace 'Port 22'

Choose a problem number, 'a' for all repairable, or Enter to abort: 1

Planned Changes
---------------
  File: /etc/ssh/sshd_config
  - replace line 1: Port nope -> Port 22

Apply repairs? [Y/n]:
```

Choose a problem number to repair one issue, choose `a` for all repairable issues, or press Enter to skip.

---

# Supported Services

Lixet currently supports:

- SSH
- Nginx
- UFW
- DNS resolver configuration
- Basic networking and hosts file checks
- Systemd service units

---

# Safety

Lixet is built to be conservative.

- No AI-generated fixes
- No full-file rewrites
- No repair without backup
- No hidden changes
- No destructive repair when the safe fix is unclear

When Lixet cannot safely repair a problem, it reports the issue without modifying the file.

---

# Requirements

- Python 3.10+
- Linux
- Root or sudo privileges for repairing system configuration files

---

# Support

If Lixet saves you time or helps recover a broken server, consider supporting the project.

### TON (Gram)

```text
UQANiDCA6hWl7BL0k6iJW9eeJ_BZ207qlrRcK3Fa_K4G_J64
```

---

# License

Lixet is released under the MIT License.

See the `LICENSE` file for details.
