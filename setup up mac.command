#!/bin/zsh
set -e
cd "${0:A:h}"
exec "./setup_mac.command" "$@"
