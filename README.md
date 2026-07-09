# Lixet

> Deterministic recovery tools for broken Linux configuration.

Lixet is a lightweight command-line tool for finding and safely repairing common Linux configuration problems.

It is built for cases where a service fails because of a bad configuration, a wrong value, a missing line, or a small mistake that is easy to miss manually.

Lixet does not use AI-generated fixes.
It doesn't guess.
It does not rewrite entire configuration files.

Every check is based on deterministic rules, and every repair is limited, explicit, and shown before it is applied.

Lixet is currently in alpha. Use it carefully on important systems and review proposed changes before applying them.

---

# Installation

```bash
git clone https://github.com/behdadaliz/Lixet.git
CD Lixet
sudo sh install.sh
```

After installation, the `lixet` command will be available system-wide:

```bash
lixet
```

To uninstall:

```bash
sudo sh uninstall.sh
```

---

# Basic Usage

Scan one supported service:

```bash
lixet scan ssh
```

Scan all supported services:

```bash
lixet doctor
```

Preview repairs without changing files:

```bash
lixet scan ssh --dry-run
lixet doctor -- dry-run
```

Apply supported repairs without confirmation:

```bash
lixet scan ssh -y
lixet doctor -y
```

Use a custom config path:

```bash
lixet scan ssh --config /path/to/config
```

Disable colored output:

```bash
lixet --no-color scan ssh
```

Check version:

```bash
lixet --version
```

Update the installed copy:

```bash
sudo lixet --update
```

---

# Commands

| command | Description
| ------------------------------------- | ------------------------------------------ |
| ``lixet'' | Show the help page
| `lixet --help` | Show the help page
| `lixet --version` | Show installed and latest version
| `sudo lixet --update` | Update the installed copy
| ``lixet scan <service>'' | Scan one supported service
| `lixet scan <service> --dry-run` | Preview repairs without modifying files
| `lixet scan <service> -y` | Apply supported repairs without prompting
| `lixet scan <service> --config <path>` | Scan using a custom config path
| ``lixet doctor'' | Scan all supported services
| ``lixet doctor --dry-run'' | Preview repairs for all supported services
| ``lixet doctor -y'' | Apply supported repairs without prompting
| `lixet --no-color ...` | Disable colored terminal output

---

# Supported Services

Lixet currently supports checks for:

* SSH
* Nginx
* UFW
* DNS
* Networking
* Systemd

If Lixet cannot prove that a repair is safe, it reports the issue without changing the file.

---

# How Lixet Repairs Files

Lixet follows a strict repair flow:

1. Inspect the target configuration.
2. Detect known problems using deterministic rules.
3. Print the issue, location, and evidence when available.
4. Show the exact planned change.
5. Ask for confirmation unless `-y' is used.
6. Create a backup before writing.
7. Apply a small line-based repair.
8. Verify the result when a reliable verifier is available.
9. Restore the backup if verification fails.

This keeps repairs predictable and easy to review.

---

# Safety Model

Lixet is designed to be conservative.

* No AI-generated repairs
* No guessing
* No hidden changes
* No full-file rewrites
* No repair without backup
* No destructive repair when the safe fix is ​​unclear

The goal is to make common configuration problems easier to detect, understand, and safely repair.

---

# Requirements

* Linux
* Python 3.10+
* Root or sudo privileges for repairing system configuration files

Some checks may use system tools such as `sshd`, `nginx`, `ufw`, `ip`, or `systemctl` when available.

---

# Project Status

Lixet is in active alpha development.

The current version focuses on a small set of supported services and safe deterministic repairs. More checks and repair rules will be added over time, but the project will remain focused on predictable behavior, clear output, and safe changes.

---

# Support

If Lixet saves you time or helps recover a broken server, you can support the project.

### TON (Gram)

``text
UQANiDCA6hWl7BL0k6iJW9eeJ_BZ207qlrRcK3Fa_K4G_J64
```

---

# License

Lixet is released under the MIT License.

See the `LICENSE' file for details.