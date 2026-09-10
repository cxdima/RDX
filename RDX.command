#!/bin/zsh
set -eu
cd "${0:A:h}"
if ! command -v node >/dev/null 2>&1; then
  export NVM_DIR="$HOME/.nvm"
  if [[ -s "$NVM_DIR/nvm.sh" ]]; then
    source "$NVM_DIR/nvm.sh"
  fi
fi
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
export RDX_OPEN_BROWSER=1
exec node scripts/start.mjs
