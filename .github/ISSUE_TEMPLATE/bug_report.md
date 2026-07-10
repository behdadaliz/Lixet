---
name: Bug report
about: Report a problem with Lixet
title: "[BUG] "
labels: bug
assignees: ""
---

## What happened?

Describe the problem clearly.

## Command

Paste the exact command you ran.

```bash
lixet ...
```

## Environment

- Linux distribution:
- Kernel and architecture (`uname -a`):
- Python version:
- Lixet version (`lixet --version`):
- Installation method:
- Interactive terminal, redirected input, or CI/container:

## Service or target

- Service checked: ssh / nginx / ufw / dns / networking / systemd / sudoers / fstab / sysctl
- Config path or target file, if relevant:
- Is the target a symlink? If yes, include `readlink` output after removing private paths:

## Expected behavior

What did you expect Lixet to do?

## Actual behavior

What did Lixet do instead?

- Exit code (`echo $?`):
- Was a repair selected, dry-run used, or `-y` used?
- Was a backup path printed?

## Terminal output

Paste the full output. Use `--no-color` if the colored output is hard to read.

```text
paste output here
```

## Relevant config or logs

Paste only the smallest useful snippet. Remove passwords, tokens, private keys, usernames, IPs, hostnames, paths, or other private data before posting. Do not attach a complete sudoers, SSH, resolver, or environment file.

```text
paste snippet here
```

## Notes

Add the smallest set of steps needed to reproduce the problem. State whether it also happens with `--no-color` and whether the file changed outside Lixet between scanning and repair.
