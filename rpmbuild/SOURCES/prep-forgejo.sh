#!/usr/bin/env bash

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
spec_file="$script_dir/../SPECS/forgejo.spec"

read_version_from_spec() {
  awk '
    /^%global[[:space:]]+upstream_version[[:space:]]+/ { print $3; found=1; exit }
    /^Version:[[:space:]]+/ && !found { print $2; exit }
  ' "$spec_file"
}

VERSION="${1:-${VERSION:-$(read_version_from_spec)}}"

if [[ -z "$VERSION" || "$VERSION" == *'%'* || "$VERSION" == *'{'* ]]; then
  echo "Usage: $0 <11.0.y>" >&2
  echo "Example: FORGEJO_REF=v11.0/forgejo $0 11.0.15" >&2
  exit 1
fi

name="forgejo"
repo="${FORGEJO_REPO:-https://codeberg.org/forgejo/forgejo.git}"
ref="${FORGEJO_REF:-v11.0/forgejo}"
workdir="$script_dir/${name}-${VERSION}"

for tool in git go npm tar; do
  command -v "$tool" >/dev/null 2>&1 || {
    echo "Missing required tool: $tool" >&2
    exit 1
  }
done

cd "$script_dir"

rm -rf "$workdir"
rm -f \
  "${name}-${VERSION}.tar.gz" \
  "${name}-${VERSION}-vendor.tar.gz" \
  "${name}-${VERSION}.commit"

git clone --depth 1 --branch "$ref" "$repo" "$workdir"

pushd "$workdir" >/dev/null
commit="$(git rev-parse HEAD)"

# The release-source target writes VERSION before creating source archives.
# Do the same here because the RPM source archive intentionally excludes .git.
printf '%s\n' "$VERSION" > VERSION

go mod vendor

# Build the frontend during source preparation, not inside mock.
#
# The Alma/EPEL 10 mock chroot can run into native Node/esbuild crashes during
# webpack. Forgejo supports building only the backend when pre-built frontend
# assets are present, so Source0 should contain public/assets already generated.
#
# node_modules is still excluded from Source0 below.
unset NODE_ENV
export npm_config_include=dev
export npm_config_omit=
export SHARP_IGNORE_GLOBAL_LIBVIPS="${SHARP_IGNORE_GLOBAL_LIBVIPS:-1}"

npm ci --include=dev --no-audit --no-fund
touch node_modules

if [[ ! -s web_src/fomantic/build/semantic.js || ! -s web_src/fomantic/build/semantic.css ]]; then
  make fomantic
fi

NODE_ENV=production make frontend

test -s public/assets/js/index.js
test -s public/assets/css/index.css

rm -rf node_modules web_src/fomantic/node_modules

popd >/dev/null

tar -C "$workdir" -zcf "${name}-${VERSION}-vendor.tar.gz" vendor

tar \
  --exclude="${name}-${VERSION}/.git" \
  --exclude="${name}-${VERSION}/vendor" \
  --exclude="${name}-${VERSION}/node_modules" \
  --exclude="${name}-${VERSION}/web_src/fomantic/node_modules" \
  --exclude="${name}-${VERSION}/.npm" \
  -zcf "${name}-${VERSION}.tar.gz" \
  "${name}-${VERSION}"

printf 'ref=%s\ncommit=%s\n' "$ref" "$commit" > "${name}-${VERSION}.commit"

rm -rf "$workdir"

cat <<EOF
Prepared Forgejo RPM sources:
  ${name}-${VERSION}.tar.gz
  ${name}-${VERSION}-vendor.tar.gz
  ${name}-${VERSION}.commit

Source ref:    ${ref}
Source commit: ${commit}
EOF
