---
description: |
  Keeps Autoloop program branches up to date with the default branch.
  Runs whenever the default branch changes and merges it into all active
  autoloop/* branches so that program iterations always build on the latest code.

on:
  push:
    branches: [main]  # ← update this if your default branch is not 'main'
  workflow_dispatch:

permissions:
  contents: write

timeout-minutes: 10

tools:
  github:
    toolsets: [repos]
  bash: true

steps:
  - name: Merge default branch into all autoloop program branches
    env:
      GITHUB_REPOSITORY: ${{ github.repository }}
      GITHUB_TOKEN: ${{ github.token }}
      DEFAULT_BRANCH: ${{ github.event.repository.default_branch }}
    run: |
      git config user.name "github-actions[bot]"
      git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
      git remote set-url origin "https://x-access-token:${GITHUB_TOKEN}@github.com/${GITHUB_REPOSITORY}.git"
      node - << 'JSEOF'
      const { execSync, spawnSync } = require('child_process');

      const defaultBranch = process.env.DEFAULT_BRANCH || 'main';

      function git(...args) {
          const result = spawnSync('git', args, { encoding: 'utf-8' });
          return { returncode: result.status, stdout: result.stdout || '', stderr: result.stderr || '' };
      }

      // Discover all remote branches matching the autoloop/* pattern.
      // Use ls-remote instead of 'git branch -r' so we don't depend on
      // pre-fetched remote-tracking refs (shallow checkouts won't have them).
      const listResult = git('ls-remote', '--heads', 'origin', 'autoloop/*');
      if (listResult.returncode !== 0) {
          console.log('Failed to list remote branches: ' + listResult.stderr);
          process.exit(0);
      }

      const branches = listResult.stdout.trim().split('\n')
          .map(b => b.trim())
          .filter(b => b)
          .map(b => b.replace(/^.*refs\/heads\//, ''));

      if (branches.length === 0) {
          console.log('No autoloop/* branches found. Nothing to sync.');
          process.exit(0);
      }

      console.log('Found ' + branches.length + ' autoloop branch(es) to sync: ' + JSON.stringify(branches));

      const failed = [];
      for (const branch of branches) {
          console.log('\n--- Syncing ' + branch + ' with ' + defaultBranch + ' ---');

          // Fetch both branches
          git('fetch', 'origin', branch);
          git('fetch', 'origin', defaultBranch);

          // Check out the program branch
          let checkout = git('checkout', branch);
          if (checkout.returncode !== 0) {
              // Try creating a local tracking branch
              checkout = git('checkout', '-b', branch, 'origin/' + branch);
          }
          if (checkout.returncode !== 0) {
              console.log('  Failed to checkout ' + branch + ': ' + checkout.stderr);
              failed.push(branch);
              continue;
          }

          // Merge the default branch into the program branch
          const merge = git('merge', 'origin/' + defaultBranch, '--no-edit',
              '-m', 'Merge ' + defaultBranch + ' into ' + branch);
          if (merge.returncode !== 0) {
              console.log('  Merge conflict or failure for ' + branch + ': ' + merge.stderr);
              // Abort the merge to leave a clean state
              git('merge', '--abort');
              failed.push(branch);
              continue;
          }

          // Push the updated branch
          const push = git('push', 'origin', branch);
          if (push.returncode !== 0) {
              console.log('  Failed to push ' + branch + ': ' + push.stderr);
              failed.push(branch);
              continue;
          }

          console.log('  Successfully synced ' + branch);
      }

      // Return to default branch
      git('checkout', defaultBranch);

      if (failed.length > 0) {
          console.log('\n\u26a0\ufe0f Failed to sync ' + failed.length + " branch(es): " + JSON.stringify(failed)); // \u26a0\ufe0f = warning sign
          console.log('These branches may need manual conflict resolution.');
          // Don't fail the workflow -- log the issue but continue
      } else {
          console.log('\n\u2705 All ' + branches.length + " branch(es) synced successfully."); // \u2705 = checkmark
      }
      JSEOF
---

Sync all autoloop/* branches with the default branch.
