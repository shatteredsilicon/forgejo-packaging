# forgejo-rpm

RPM packaging for Forgejo 11.x using pre-fetched Go dependencies and a
pre-built frontend.

This package follows Forgejo's binary installation layout:

- service user/group: `git:git`
- work/data directory: `/var/lib/forgejo`
- config directory: `/etc/forgejo`
- config file: `/etc/forgejo/app.ini` (see "Configuration" below)
- binary: `/usr/bin/forgejo`
- systemd service: `forgejo.service`

## Prepare sources

Run the prep script before building in `mock`. This clones Forgejo, vendors
Go modules, and **builds the frontend on the host** (webpack/npm are not run
inside mock; see "Why the frontend is pre-built" below).

~~~~ {.bash}
cd forgejo/rpmbuild/SOURCES
./prep-forgejo.sh 11.0.15
~~~~

By default the prep script clones the moving 11.x branch:

~~~~ {.bash}
FORGEJO_REF=v11.0/forgejo ./prep-forgejo.sh 11.0.15
~~~~

To build a fixed release tag instead:

~~~~ {.bash}
FORGEJO_REF=v11.0.15 ./prep-forgejo.sh 11.0.15
~~~~

The script creates:

- `forgejo-11.0.15.tar.gz` (includes pre-built `public/assets/`)
- `forgejo-11.0.15-vendor.tar.gz`
- `forgejo-11.0.15.commit`

Requires `git`, `go`, `npm`, and `tar` on the host preparing sources. `npm`
and `nodejs` are **not** required inside the mock buildroot, since only the
Go backend is compiled there.

### Why the frontend is pre-built

Running `make frontend` (webpack) inside a `mock` chroot can segfault:
native Node build tools (esbuild, lightningcss, etc.) rely on syscalls,
`/dev/shm`, or memory limits that mock's sandboxing restricts. Building the
frontend on the host and shipping the compiled assets in `Source0` avoids
this; `mock` only ever runs `go build`.

## Build with mock

Replace `your-mock-template` with your mock configuration name.

~~~~ {.bash}
mock -r your-mock-template \
  --buildsrpm \
  --spec rpmbuild/SPECS/forgejo.spec \
  --sources rpmbuild/SOURCES \
  --define 'upstream_version 11.0.15'

mock -r your-mock-template \
  --rebuild /var/lib/mock/your-mock-template/result/forgejo-11.0.15-1*.src.rpm
~~~~

## Install

~~~~ {.bash}
sudo dnf install ./forgejo-11.0.15-1*.rpm
sudo systemctl enable --now forgejo.service
~~~~

## Configuration

The package ships a minimal `/etc/forgejo/app.ini` (SQLite, `localhost`,
port 3000, `INSTALL_LOCK = false`) so that Forgejo's guided web installer at
`http://<host>:3000/` can complete first-time setup — choosing the database,
domain, and admin account, and generating `SECRET_KEY`/`INTERNAL_TOKEN`.
`/etc/forgejo` and `app.ini` are shipped group-writable by `git` for exactly
this reason.

`app.ini` is marked `%config(noreplace)`, so package upgrades never
overwrite your configured file; if the shipped template changes, you'll get
an `app.ini.rpmnew` alongside it instead.

After completing Forgejo's first-run web configuration, tighten permissions
as described by Forgejo's installation guide:

**Only run this after the web installer has finished successfully** (you are
redirected to the normal dashboard, not shown the install form again).
Applying it earlier locks Forgejo out of writing `app.ini` and setup will
fail with `Failed to save configuration: open /etc/forgejo/app.ini: permission denied`.

~~~~ {.bash}
sudo chmod 750 /etc/forgejo
sudo chmod 640 /etc/forgejo/app.ini
~~~~

**NOTE:** See [Guideline to configure forgejo](https://forgejo.org/docs/latest/admin/installation/binary/)

## Testing the RPM

After building with mock:

1. **Verify contents before installing**:
   ~~~~ {.bash}
   rpm -qlp ./forgejo-11.0.15-1*.rpm
   rpm -qp --requires ./forgejo-11.0.15-1*.rpm
   ~~~~
2. **Install** in a VM or systemd-capable container (plain non-privileged
   containers won't run systemd services):
   ~~~~ {.bash}
   sudo dnf install ./forgejo-11.0.15-1*.rpm
   ~~~~
3. **Check ownership/permissions**:
   ~~~~ {.bash}
   id git
   stat -c '%U:%G %a' /var/lib/forgejo /var/log/forgejo /etc/forgejo /etc/forgejo/app.ini /home/git
   ~~~~
4. **Start and inspect logs**:
   ~~~~ {.bash}
   sudo systemctl enable --now forgejo.service
   journalctl -u forgejo.service -e --no-pager
   ~~~~
5. **Complete the web installer** and confirm the service still serves the
   normal UI (not the installer) after `sudo systemctl restart forgejo.service`.
6. **Upgrade test**: build a `-2` release, `rpm -Uvh` it, and confirm your
   edited `app.ini` is untouched (look for `app.ini.rpmnew` instead).
7. **Removal test**: `sudo dnf remove forgejo`, then confirm the unit is
   gone and decide whether `/var/lib/forgejo`, `/etc/forgejo`, and
   `/home/git` should persist (they do by default, to protect data).


## Troubleshooting

### `Failed to save configuration: open /etc/forgejo/app.ini: permission denied`

This means `/etc/forgejo` and/or `app.ini` were locked down (see
"Configuration" above) before the web installer finished, so the `git` user
can no longer write `app.ini`. Confirm and fix:

~~~~ {.bash}
sudo stat -c '%U:%G %a' /etc/forgejo /etc/forgejo/app.ini
# Packaged defaults: /etc/forgejo -> root:git 770, app.ini -> root:git 660
~~~~

Rather than hand-fixing individual `chmod`/`chown` values, restore both to
the package's declared state in one step:

~~~~ {.bash}
sudo rpm --setugids forgejo
sudo rpm --setperms forgejo
sudo systemctl restart forgejo.service
~~~~

Retry the web installer, then re-apply the lock-down steps once setup has
actually completed.

If the save still fails after that, SELinux `dontaudit` rules can suppress
AVC log entries even when SELinux is the cause. Confirm conclusively with a
temporary, reversible test (re-enable immediately after testing either way):

~~~~ {.bash}
sudo setenforce 0
# retry saving the configuration in the web installer
sudo setenforce 1
~~~~

If disabling SELinux temporarily fixes it, restore enforcing mode and run
`restorecon -Rv /etc/forgejo /var/lib/forgejo /var/log/forgejo /home/git`,
then generate a local policy module if denials persist:
`sudo ausearch -m avc -ts recent | audit2allow -M forgejo-local && sudo semodule -i forgejo-local.pp`.
