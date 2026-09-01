#!/usr/bin/env bash
#
# One-shot developer environment setup for the Shelving Workbench.
#
# Provisions the pixi environment (dev toolchain plus FreeCAD 1.0) and is safe
# to re-run: each step is a no-op when already satisfied.
#
# When pixi is not already on PATH it downloads a pinned release for the host
# architecture, verifies its published .sha256, installs it into ~/.local/bin,
# and adds that directory to ~/.bashrc and ~/.profile.
#
set -euo pipefail

# Keep in step with pixi.toml's expectations and tools/ documentation.
PIXI_VERSION="v0.78.0"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

LOCAL_BIN="$HOME/.local/bin"
pixi_installed_now=0

add_local_bin_to_rc() {
	local rc="$1"
	# The rc file must receive $HOME and $PATH literally, to be expanded by the
	# future shell that sources it, not by this script.
	# shellcheck disable=SC2016
	local line='export PATH="$HOME/.local/bin:$PATH"'
	if [ ! -f "$rc" ] || ! grep -qxF "$line" "$rc"; then
		printf '\n# added by tools/install-deps.sh\n%s\n' "$line" >>"$rc"
	fi
}

install_pinned_pixi() {
	local arch asset base_url tmp expected actual
	case "$(uname -m)" in
	x86_64) arch="x86_64" ;;
	aarch64) arch="aarch64" ;;
	*)
		echo "ERROR: unsupported host architecture $(uname -m); install pixi manually from https://pixi.sh" >&2
		exit 1
		;;
	esac
	asset="pixi-${arch}-unknown-linux-musl"
	base_url="https://github.com/prefix-dev/pixi/releases/download/${PIXI_VERSION}"

	tmp="$(mktemp -d)"
	trap 'rm -rf "$tmp"' RETURN
	curl -fsSL "${base_url}/${asset}" -o "$tmp/pixi"
	curl -fsSL "${base_url}/${asset}.sha256" -o "$tmp/pixi.sha256"
	expected="$(awk '{print $1}' "$tmp/pixi.sha256")"
	actual="$(sha256sum "$tmp/pixi" | awk '{print $1}')"
	if [ "$expected" != "$actual" ]; then
		echo "ERROR: pixi checksum mismatch (expected ${expected}, got ${actual})" >&2
		exit 1
	fi
	mkdir -p "$LOCAL_BIN"
	install -m 0755 "$tmp/pixi" "$LOCAL_BIN/pixi"
	add_local_bin_to_rc "$HOME/.bashrc"
	add_local_bin_to_rc "$HOME/.profile"
	pixi_installed_now=1
}

if ! command -v pixi >/dev/null 2>&1 && [ ! -x "$LOCAL_BIN/pixi" ]; then
	install_pinned_pixi
fi

# The rc edits above only reach future shells; make pixi callable now.
case ":$PATH:" in
*":$LOCAL_BIN:"*) ;;
*) export PATH="$LOCAL_BIN:$PATH" ;;
esac

pixi install

echo
echo "Setup complete."
echo "  enter the environment:  pixi shell"
echo "  run the checks:         pixi run tests"
if [ "$pixi_installed_now" -eq 1 ]; then
	echo
	echo "pixi was installed to ${LOCAL_BIN}. Open a new shell (or run"
	echo "'source ~/.profile') so it is on PATH."
fi
