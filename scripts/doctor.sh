#!/usr/bin/env sh
set -eu

fail=0

check_command() {
  if command -v "$1" >/dev/null 2>&1; then
    printf 'ok  %s\n' "$1"
  else
    printf 'missing  %s\n' "$1"
    fail=1
  fi
}

check_command node
check_command pnpm
check_command python3
check_command uv
check_command git

if [ -f .env ]; then
  printf 'ok  .env exists\n'
else
  printf 'note  .env is absent; copy .env.example before local API work\n'
fi

if git status --short >/dev/null 2>&1; then
  printf 'ok  git repository\n'
else
  printf 'missing  git repository\n'
  fail=1
fi

exit "$fail"
