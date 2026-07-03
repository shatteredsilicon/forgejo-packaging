%define debug_package %{nil}

%{!?upstream_version:%{error:upstream_version must be defined, e.g. rpmbuild --define 'upstream_version 11.0.15'}}

Name:           forgejo
Version:        %{upstream_version}
Release:        1%{?dist}
Summary:        Self-hosted lightweight software forge
License:        MIT
URL:            https://forgejo.org
Source0:        %{name}-%{upstream_version}.tar.gz
Source1:        %{name}-%{upstream_version}-vendor.tar.gz
Source3:        %{name}.service
Source4:        %{name}-user.conf
Source5:        %{name}-app.ini

BuildRequires:  gcc
BuildRequires:  git
BuildRequires:  golang >= 1.24
BuildRequires:  make
BuildRequires:  systemd-rpm-macros
BuildRequires:  tar
BuildRequires:  gzip
%{?sysusers_requires_compat}

Requires:       git
Requires:       git-lfs
Recommends:     openssh-server

%description
Forgejo is a self-hosted lightweight software forge.
It provides Git repository hosting, code review, issue tracking,
package registries, and project collaboration features.

%prep
%setup -q
%setup -q -D -a 1

# The source archive is generated from a branch/ref and excludes .git.
# Keep VERSION present so Forgejo does not try to derive the version from git.
printf '%s\n' "%{upstream_version}" > VERSION

# The frontend is intentionally built by prep-forgejo.sh and stored in Source0.
# mock only builds the backend and embeds these assets with the bindata tag.
test -s public/assets/js/index.js && test -s public/assets/css/index.css || {
  echo "pre-built frontend assets are missing from Source0" >&2
  echo "Re-run SOURCES/prep-forgejo.sh and rebuild the SRPM." >&2
  exit 1
}

%build
export CGO_ENABLED=1

# RPM injects ELF/GCC linker hardening flags through LDFLAGS, for example
# -Wl,-z,relro. Forgejo's Makefile uses LDFLAGS as Go linker flags and passes
# it directly to `go build -ldflags`, where GCC-style -Wl flags are invalid.
#
# Preserve those flags for CGO/external C linking, but remove LDFLAGS from the
# Makefile environment so Forgejo can construct its own Go-compatible LDFLAGS.
rpm_ldflags="${LDFLAGS:-}"
unset LDFLAGS
if [ -n "$rpm_ldflags" ]; then
  export CGO_LDFLAGS="${CGO_LDFLAGS:+${CGO_LDFLAGS} }${rpm_ldflags}"
fi

export GOPROXY=off
export GOSUMDB=off
export GOFLAGS="-mod=vendor -buildvcs=false -trimpath"
export EXTRA_GOFLAGS="-mod=vendor -buildvcs=false -trimpath"
export TAGS="bindata timetzdata sqlite sqlite_unlock_notify"
export FORGEJO_VERSION="%{upstream_version}"
export RELEASE_VERSION="%{upstream_version}"
export VERSION="%{upstream_version}"

# Do not pass %%{?_smp_mflags}; Forgejo's make targets are not needed in
# parallel here, and serial builds are more reliable for generated assets.
make backend TAGS="$TAGS" GOFLAGS="-v -mod=vendor -buildvcs=false -trimpath"
make forgejo TAGS="$TAGS" GOFLAGS="-v -mod=vendor -buildvcs=false -trimpath"

strip forgejo

%install
install -p -D -m 0755 forgejo %{buildroot}%{_bindir}/%{name}
install -p -D -m 0644 %{SOURCE3} %{buildroot}%{_unitdir}/%{name}.service
install -p -D -m 0644 %{SOURCE4} %{buildroot}%{_sysusersdir}/%{name}.conf

install -d -m 0750 %{buildroot}/home/git
install -d -m 0750 %{buildroot}%{_localstatedir}/lib/%{name}
install -d -m 0750 %{buildroot}%{_localstatedir}/log/%{name}
install -d -m 0770 %{buildroot}%{_sysconfdir}/%{name}

# Forgejo's web installer writes into app.ini on first run, so the file must
# stay group-writable by "git" (matching the /etc/forgejo directory) until
# the admin locks it down per the upstream binary-install docs.
install -p -D -m 0660 %{SOURCE5} %{buildroot}%{_sysconfdir}/%{name}/app.ini

%pre
%sysusers_create_compat %{SOURCE4}

%post
%systemd_post %{name}.service

%preun
%systemd_preun %{name}.service

%postun
%systemd_postun %{name}.service

%files
%license LICENSE
%doc README.md
%{_bindir}/%{name}
%{_unitdir}/%{name}.service
%{_sysusersdir}/%{name}.conf
%dir %attr(0750, git, git) /home/git
%dir %attr(0750, git, git) %{_localstatedir}/lib/%{name}
%dir %attr(0750, git, git) %{_localstatedir}/log/%{name}
%dir %attr(0770, root, git) %{_sysconfdir}/%{name}
%config(noreplace) %attr(0660, root, git) %{_sysconfdir}/%{name}/app.ini

%changelog
