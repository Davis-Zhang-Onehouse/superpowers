# tests/sync/test_manifest_resolver.sh — S6 RV-S6Y-2/4: resolve_manifest_versions changes only the DECLARED field,
# exactly one line, and never rewrites line endings.
# shellcheck shell=bash
DIR="$(cd "$(dirname "$0")" && pwd)"; . "$DIR/harness.sh"
. "$SCRIPTS/lib.sh"
case_repo() { # case_repo <base> <upstream> <fork> [file] -> rebased repo path in $R with the conflict in place
  local f="${4:-package.json}"; R="$(mktemp -d "$SANDBOX/case.XXXX")"
  git init -q "$R"; g "$R" config user.email a@a; g "$R" config user.name a
  echo '{ "files": [ { "path": "package.json", "field": "version" }, { "path": "p.yaml", "field": "version" } ] }' > "$R/.version-bump.json"
  printf '%b' "$1" > "$R/$f"; g "$R" add -A; g "$R" commit -qm base; g "$R" branch -q fork
  printf '%b' "$2" > "$R/$f"; g "$R" commit -qam up; g "$R" checkout -q fork; printf '%b' "$3" > "$R/$f"; g "$R" commit -qam fork
  g "$R" rebase -q master >/dev/null 2>&1 || true
}
refuses() { local before; before="$(cat "$R/${1:-package.json}")"; if resolve_manifest_versions "$R" >/dev/null 2>&1; then echo "FAIL: $2 was resolved"; exit 1; fi
            [ "$before" = "$(cat "$R/${1:-package.json}")" ] || { echo "FAIL: $2 touched the file"; exit 1; }; }
case_repo '{\n  "version": "1.0.0",\n  "dep": {\n    "version": "2.0.0"\n  }\n}\n' \
          '{\n  "version": "1.0.1",\n  "dep": {\n    "version": "3.0.0"\n  }\n}\n' \
          '{\n  "version": "1.0.0+fleet.1",\n  "dep": {\n    "version": "2.5.0"\n  }\n}\n'
refuses package.json "a nested dependency version next to the top one"
case_repo '{\n  "version": "1.0.0",\n  "dep": {\n    "version": "2.0.0"\n  }\n}\n' \
          '{\n  "version": "1.0.0",\n  "dep": {\n    "version": "3.0.0"\n  }\n}\n' \
          '{\n  "version": "1.0.0",\n  "dep": {\n    "version": "2.5.0"\n  }\n}\n'
refuses package.json "a nested dependency version alone"
case_repo 'version: 1.0.0\ndeps:\n  version: 2.0\n' 'version: 1.0.1\ndeps:\n  version: 3.0\n' 'version: 1.0.0+fleet.1\ndeps:\n  version: 2.5\n' p.yaml
refuses p.yaml "a nested YAML version"
case_repo '{\r\n  "version": "1.0.0",\r\n  "a": 1\r\n}\r\n' '{\r\n  "version": "1.0.1",\r\n  "a": 1\r\n}\r\n' '{\r\n  "version": "1.0.0+fleet.1",\r\n  "a": 1\r\n}\r\n'
refuses package.json "a CRLF manifest"
case_repo '{\n  "version": "1.0.0",\n  "a": 1\n}\n' '{\n  "version": "1.0.1",\n  "a": 1\n}\n' '{\n  "version": "1.0.0+fleet.1",\n  "a": 1\n}\n'
resolve_manifest_versions "$R" > /dev/null
assert_grep '"version": "1.0.1+fleet.1",' "$R/package.json"                 # the control resolves
pass
