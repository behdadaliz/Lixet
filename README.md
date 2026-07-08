# Lixet

> The First-Aid Kit for Broken Linux Servers.

Lixet is a lightweight Linux command-line tool that detects, explains, and safely repairs common configuration problems.

It is deterministic by design. Lixet does not guess, does not use AI for repairs, and does not rewrite whole configuration files. It applies small, explicit fixes only after showing the problem and asking for approval.

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

Preview repairs without changing files:

```bash
lixet scan ssh --dry-run
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
Issue: high SSH_INVALID_PORT
Description: Invalid Port value 'nope'. Must be an integer between 1 and 65535.
Location: /etc/ssh/sshd_config:1
Proposed repair:
  - replace line 1: Port nope -> Port 22
Repair this issue? [y/N]:
```

Press `y` to apply the repair, or press Enter to skip it.

---

# Supported Services

Lixet currently supports:

- SSH
- Nginx
- UFW
- DNS resolver configuration
- Basic networking hosts file
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
