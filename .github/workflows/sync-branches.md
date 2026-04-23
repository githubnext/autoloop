---
description: |
  Keeps Autoloop program branches up to date with the default branch.
  Runs whenever the default branch changes and merges it into all active
  autoloop/* branches so that program iterations always build on the latest code.

on:
  push:
    branches: [main]  # ← update this if your default branch is not 'main'
  workflow_dispatch:

permissions: read-all

timeout-minutes: 10

tools:
  github:
    toolsets: [repos]
  bash: true

steps:
  - name: Merge default branch into all autoloop program branches
    env:
      GITHUB_REPOSITORY: ${{ github.repository }}
      DEFAULT_BRANCH: ${{ github.event.repository.default_branch }}
    run: |
      python3 - << 'PYEOF'
      import os, subprocess, sys

      token = os.environ.get("GITHUB_TOKEN", "")
      repo = os.environ.get("GITHUB_REPOSITORY", "")
      default_branch = os.environ.get("DEFAULT_BRANCH", "main")

      # List all remote branches matching the autoloop/* pattern
      result = subprocess.run(
          ["git", "branch", "-r", "--list", "origin/autoloop/*"],
          capture_output=True, text=True
      )
      if result.returncode != 0:
          print(f"Failed to list remote branches: {result.stderr}")
          sys.exit(0)

      branches = [b.strip().replace("origin/", "") for b in result.stdout.strip().split("\n") if b.strip()]

      if not branches:
          print("No autoloop/* branches found. Nothing to sync.")
          sys.exit(0)

      print(f"Found {len(branches)} autoloop branch(es) to sync: {branches}")

      def rev_count(range_spec):
          r = subprocess.run(
              ["git", "rev-list", "--count", range_spec],
              capture_output=True, text=True
          )
          if r.returncode != 0:
              return None
          try:
              return int(r.stdout.strip())
          except ValueError:
              return None

      failed = []
      for branch in branches:
          print(f"\n--- Syncing {branch} with {default_branch} ---")

          # Fetch both branches so the ahead/behind counts below are computed
          # against up-to-date local copies of the remote tips.
          subprocess.run(["git", "fetch", "origin", branch], capture_output=True)
          subprocess.run(["git", "fetch", "origin", default_branch], capture_output=True)

          # Compute ahead/behind counts using the remote-tracking refs so we
          # make a decision based on commit delta (not content delta).
          ahead = rev_count(f"origin/{default_branch}..origin/{branch}")
          behind = rev_count(f"origin/{branch}..origin/{default_branch}")
          if ahead is None or behind is None:
              print(f"  Failed to compute ahead/behind for {branch}")
              failed.append(branch)
              continue
          print(f"  ahead={ahead} behind={behind}")

          if ahead == 0 and behind > 0:
              # All of the branch's commits are already in the default branch.
              # Merging would produce a noisy "Merge main into branch" commit
              # that re-exposes every historical file as a patch touch — the
              # failure mode that triggers gh-aw's E003 (>100 files) when a
              # new PR is opened. Fast-forward the canonical branch instead.
              # This is lossless because ahead=0 proves every commit on the
              # branch is already reachable from the default branch.
              ff = subprocess.run(
                  ["git", "checkout", "-B", branch, f"origin/{default_branch}"],
                  capture_output=True, text=True
              )
              if ff.returncode != 0:
                  print(f"  Failed to fast-forward {branch}: {ff.stderr}")
                  failed.append(branch)
                  continue
              # Use --force-with-lease so that if anyone else is simultaneously
              # pushing to the branch, the update is rejected rather than
              # overwriting their commits.
              push = subprocess.run(
                  ["git", "push", "--force-with-lease", "origin", branch],
                  capture_output=True, text=True
              )
              if push.returncode != 0:
                  print(f"  Failed to force-push {branch}: {push.stderr}")
                  failed.append(branch)
                  continue
              print(f"  Fast-forwarded {branch} to origin/{default_branch}")
              continue

          if ahead == 0 and behind == 0:
              # Already at default branch — nothing to do.
              print(f"  {branch} is already up to date with origin/{default_branch}")
              continue

          if ahead > 0 and behind == 0:
              # Unique work preserved; no upstream drift to merge.
              print(f"  {branch} is ahead of origin/{default_branch} with no upstream drift; nothing to merge.")
              continue

          # True divergence (ahead > 0 and behind > 0): check out and merge.
          checkout = subprocess.run(
              ["git", "checkout", "-B", branch, f"origin/{branch}"],
              capture_output=True, text=True
          )
          if checkout.returncode != 0:
              print(f"  Failed to checkout {branch}: {checkout.stderr}")
              failed.append(branch)
              continue

          # Merge the default branch into the program branch
          merge = subprocess.run(
              ["git", "merge", f"origin/{default_branch}", "--no-edit",
               "-m", f"Merge {default_branch} into {branch}"],
              capture_output=True, text=True
          )
          if merge.returncode != 0:
              print(f"  Merge conflict or failure for {branch}: {merge.stderr}")
              # Abort the merge to leave a clean state
              subprocess.run(["git", "merge", "--abort"], capture_output=True)
              failed.append(branch)
              continue

          # Push the updated branch
          push = subprocess.run(
              ["git", "push", "origin", branch],
              capture_output=True, text=True
          )
          if push.returncode != 0:
              print(f"  Failed to push {branch}: {push.stderr}")
              failed.append(branch)
              continue

          print(f"  Successfully synced {branch}")

      # Return to default branch
      subprocess.run(["git", "checkout", default_branch], capture_output=True)

      if failed:
          print(f"\n⚠️ Failed to sync {len(failed)} branch(es): {failed}")
          print("These branches may need manual conflict resolution.")
          # Don't fail the workflow — log the issue but continue
      else:
          print(f"\n✅ All {len(branches)} branch(es) synced successfully.")
      PYEOF
---

Sync all autoloop/* branches with the default branch.
