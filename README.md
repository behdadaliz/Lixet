# Lixet

Lixet is a small Linux command-line tool for checking common service configuration problems and applying a limited set of safe, deterministic repairs.

It is meant for the situations where a server is misconfigured and you want a quick second pair of eyes: show me what looks wrong, where it is, and what can be repaired safely.

Lixet does not use AI, does not guess fixes, and does not rewrite entire configuration files. When an issue is not safe to repair automatically, it reports the problem and leaves the file alone.

Lixet is currently in alpha. Review every proposed repair before using it on important systems.

---

# Installation

```bash
git clone https://github.com/behdadaliz/Lixet.git
cd Lixet
sudo sh install.sh
```

After installation, the command is available as:

```bash
lixet
```

To uninstall:

```bash
sudo sh uninstall.sh
```

---

# Commands

Show help:

```bash
lixet
lixet --help
```

Check the installed version:

```bash
lixet --version
```

Update the installed version:

```bash
sudo lixet --update
```

Scan one service:

```bash
lixet scan ssh
lixet scan nginx
lixet scan ufw
lixet scan dns
lixet scan networking
lixet scan systemd
```

Scan all supported services:

```bash
lixet doctor
```

Preview repair actions without changing files:

```bash
lixet scan ssh --dry-run
lixet doctor --dry-run
```

Apply supported repairs without prompting:

```bash
lixet scan ssh -y
lixet doctor -y
```

Use a custom config path when a command supports it:

```bash
lixet scan ssh --config /path/to/sshd_config
```

Disable colored output:

```bash
lixet --no-color scan ssh
```

---

# Supported Checks

Lixet currently has checks for:

- SSH
- Nginx
- UFW
- DNS resolver configuration
- Basic networking and `/etc/hosts`
- Systemd service units

Some checks are diagnostic only. Some can propose a small repair. Lixet shows which issues are repairable before it changes anything.

---

# How Repairs Work

When Lixet finds an issue, it prints the problem, location, evidence when available, and any safe repair it can offer.

If a repair is selected, Lixet:

1. Shows the planned file change.
2. Creates a backup before writing.
3. Applies a small line-based edit.
4. Runs a verifier when the service has one available.
5. Restores the backup if verification fails.

Not every issue has an automatic repair. For example, syntax failures from `sshd -t` or `nginx -t` are reported with evidence, but unknown or unsafe fixes are not applied automatically.

---

# Safety

Lixet is intentionally conservative.

- No AI-generated fixes
- No hidden edits
- No full-file rewrites
- No repair without a backup
- No automatic service restarts for risky cases
- No automatic repair when the safe change is unclear

The goal is not to replace an administrator. The goal is to make common configuration problems easier to see and safer to fix.

---

# Requirements

- Linux
- Python 3.10+
- Root or sudo privileges for repairing system configuration files
- Relevant system tools for some checks, such as `sshd`, `nginx`, `ufw`, `ip`, or `systemctl`

---

# Project Status

Lixet is an alpha project. It already performs deterministic checks for several common Linux services, but the supported repair set is intentionally limited.

Please report issues with the exact command, target system, and terminal output so problems can be reproduced.

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
