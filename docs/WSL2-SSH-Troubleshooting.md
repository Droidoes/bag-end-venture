# WSL2 SSH Troubleshooting — "Bad owner or permissions on ssh_config.d"

Symptom (2026-09-08): every `ssh`/`git push` in the WSL2 distro fails with

```
Bad owner or permissions on /etc/ssh/ssh_config.d/20-systemd-ssh-proxy.conf
```

## Diagnosis

```
ls -l /etc/ssh/ssh_config.d/20-systemd-ssh-proxy.conf \
      /etc/ssh/ssh_config /etc/ssh/ssh_config.d \
      /usr/lib/systemd/ssh_config.d/20-systemd-ssh-proxy.conf
```

If any of them shows `nobody nogroup` (instead of `root root`), OpenSSH
refuses to read the config chain — it requires every config file and its
containing directory to be owned by root (or the current user) and not
group/world-writable.

## Real fix (run INSIDE the Ubuntu WSL terminal, not Windows)

```
sudo chown -h root:root /etc/ssh/ssh_config /etc/ssh/ssh_config.d \
  /etc/ssh/ssh_config.d/20-systemd-ssh-proxy.conf \
  /usr/lib/systemd/ssh_config.d/20-systemd-ssh-proxy.conf
```

`-h` matters: the first path is a symlink and `-h` changes the link itself,
not its target (include the target path in the list too, as above).

Verify:

```
ssh -T git@github.com
# expect: Hi <user>! You've successfully authenticated…
```

If ownership does not stick across reboots, the WSL systemd integration may be
recreating the file — re-run the chown after each boot or disable the
systemd ssh-proxy (`/etc/wsl.conf` `[boot] systemd=false` trade-offs apply;
not recommended without testing other systemd-dependent tools).

## Git-only workaround (in use since 2026-09-08)

If the real fix can't be applied right away, git can bypass the broken
system config entirely:

```
git config --global core.sshCommand "ssh -F /dev/null -o StrictHostKeyChecking=accept-new"
```

- `-F /dev/null` skips BOTH the system and user ssh configs (defaults still
  apply: `~/.ssh/id_*` keys and `~/.ssh/known_hosts`).
- Covers git only — GitHub CLI, scp, and other ssh tools still need the real
  fix.
- To remove later: `git config --global --unset core.sshCommand`.

## Verification

```
ssh -T git@github.com              # direct auth check
git push                           # repo-level check
git config --global --get core.sshCommand   # workaround present?
```
