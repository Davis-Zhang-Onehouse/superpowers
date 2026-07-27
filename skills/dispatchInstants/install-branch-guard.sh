#!/usr/bin/env bash
#
# install-branch-guard.sh — make it IMPOSSIBLE for a worker to push a shared base branch.
#
# In parallel dev each worker owns its own branch; two workers pushing one shared branch
# collide (non-fast-forward) and can clobber each other. That rule used to live in a brief and
# depend on every worker remembering it. This installs a pre-push hook that simply refuses.
#
# Usage:  install-branch-guard.sh <repo-dir> <protected-branch> [<protected-branch>...]
# Exit:   0 installed (idempotent)   2 bad input
set -uo pipefail

repo="${1:-}"; shift || true
[ -n "$repo" ] && [ $# -ge 1 ] || { echo "usage: install-branch-guard.sh <repo> <branch>..." >&2; exit 2; }
[ -d "$repo/.git" ] || { echo "not a git repo: $repo" >&2; exit 2; }

hooks="$repo/.git/hooks"; mkdir -p "$hooks"
hook="$hooks/pre-push"
list="$*"

cat > "$hook" <<EOF
#!/usr/bin/env bash
# Installed by superpowers install-branch-guard.sh — refuses pushes to shared base branches.
# Each parallel worker pushes its OWN branch; the shared base is restacked at compaction only.
PROTECTED="$list"
rc=0
while read -r local_ref local_sha remote_ref remote_sha; do
  [ -n "\$remote_ref" ] || continue
  b="\${remote_ref#refs/heads/}"
  for p in \$PROTECTED; do
    if [ "\$b" = "\$p" ]; then
      echo "pre-push: REFUSED — '\$b' is a shared base branch." >&2
      echo "  Push your own per-worker branch instead; the base is restacked at compaction." >&2
      rc=1
    fi
  done
done
exit \$rc
EOF
chmod +x "$hook"
echo "branch guard installed in $repo (protected: $list)"
