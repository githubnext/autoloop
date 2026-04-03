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

      failed = []
      for branch in branches:
          print(f"\n--- Syncing {branch} with {default_branch} ---")

          # Fetch both branches
          subprocess.run(["git", "fetch", "origin", branch], capture_output=True)
          subprocess.run(["git", "fetch", "origin", default_branch], capture_output=True)

          # Check out the program branch
          checkout = subprocess.run(
              ["git", "checkout", branch],
              capture_output=True, text=True
          )
          if checkout.returncode != 0:
              # Try creating a local tracking branch
              checkout = subprocess.run(
                  ["git", "checkout", "-b", branch, f"origin/{branch}"],
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
