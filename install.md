# Install Autoloop

This prompt guides you, a coding agent, to install **Autoloop** — an automated research and experimentation platform that runs iterative optimization loops on [GitHub Agentic Workflows](https://github.github.com/gh-aw/).

## Your Task

Set up Autoloop in this repository by:

1. Installing the gh-aw CLI extension
2. Initializing the repo for agentic workflows
3. Copying the Autoloop workflow and configuration files
4. Compiling the workflows
5. Creating a branch, committing, and opening a pull request
6. Helping create the first Autoloop program

## Step 1: Install gh-aw CLI Extension

Install the gh-aw extension directly via the GitHub CLI:

```bash
gh extension install github/gh-aw
```

<details>
<summary>Alternative: install via shell script</summary>

If `gh extension install` is unavailable, download and run the installation script manually:

```bash
curl -fL https://raw.githubusercontent.com/github/gh-aw/main/install-gh-aw.sh -o /tmp/install-gh-aw.sh
bash /tmp/install-gh-aw.sh
rm -f /tmp/install-gh-aw.sh
```

</details>

**Verify installation**:

```bash
gh aw version
```

You should see version information displayed. If you encounter an error, check that:

- GitHub CLI (`gh`) is installed and authenticated
- The installation completed without errors

## Step 2: Initialize Repository for Agentic Workflows

```bash
gh aw init
```

**What this does**: Configures `.gitattributes`, creates the dispatcher agent, and sets up Copilot setup steps.

## Step 3: Clone Autoloop and Copy Files

Clone the Autoloop repository and copy its files into this repo:

```bash
git clone https://github.com/githubnext/autoloop /tmp/autoloop
```

Copy the workflow definitions:

```bash
cp -r /tmp/autoloop/workflows/ .github/workflows/
```

Copy the issue template and create the Autoloop directories:

```bash
mkdir -p .github/ISSUE_TEMPLATE
cp -r /tmp/autoloop/.github/ISSUE_TEMPLATE/ .github/ISSUE_TEMPLATE/
mkdir -p .autoloop/programs
```

Clean up:

```bash
rm -rf /tmp/autoloop
```

## Step 4: Compile the Workflows

```bash
gh aw compile autoloop
```

**What this does**: Generates `.github/workflows/autoloop.lock.yml` from the workflow definition.

## Step 5: Create a Branch, Commit, and Open a Pull Request

Create a new branch for the installation changes, commit, and push:

```bash
git checkout -b install-autoloop
git add .
git commit -m "Install Autoloop"
git push -u origin install-autoloop
```

Then open a pull request for review:

```bash
gh pr create --title "Install Autoloop" --body "Set up Autoloop workflows and configuration"
```

Report the pull request link to the user.

## Step 6: Create Your First Program

Next, suggest to the user that we create their first program, which will be added to the existing PR. If they decline, we're done. Else, continue.

Help the user create their first Autoloop program as a GitHub issue using the **Autoloop Program** issue template. See `create-program.md` for a detailed guide on writing programs.

A good first program has:

- A **measurable** numeric metric
- A **bounded** set of target files
- An **incremental** goal where small changes can improve the metric

When proposing a program, **always clarify whether it is open-ended or goal-oriented**:

- **Open-ended** programs run indefinitely, always seeking improvement (e.g., "continuously improve algorithm performance"). Omit `target-metric` from the frontmatter.
- **Goal-oriented** programs have a specific finish line (e.g., "reach 95% test coverage"). Set `target-metric` in the frontmatter. When the metric is reached, the program completes automatically — the `autoloop-program` label is removed and `autoloop-completed` is added.

Read the target repo to find good candidates for autoloop programs. Test coverage? Bundle size optimization? Algo improvements? ML pipeline improvements?

Optionally, you may copy existing examples from the [`.autoloop/programs/`](.autoloop/programs/) folder in the Autoloop repo for inspiration.


## Troubleshooting

### gh aw not found

- Verify GitHub CLI is installed: `gh --version`
- Re-run the installation command from Step 1
- Check that `gh auth status` shows a valid session

### Compile fails

- Ensure `.github/workflows/autoloop.md` exists
- Ensure `.github/workflows/shared/` directory was copied
- Re-run `gh aw compile autoloop` with `--verbose` for details

## Reference

- **Autoloop repository**: https://github.com/githubnext/autoloop
- **GitHub Agentic Workflows**: https://github.github.com/gh-aw/
- **Creating programs**: See `create-program.md`
