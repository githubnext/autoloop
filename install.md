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

## Step 3: Download Autoloop and Copy Files

Download the Autoloop source as a zip and copy the files you need into this repo. This avoids a `git clone` (no `.git` history is downloaded, and `git` is not required) and works on Linux, macOS, and Windows.

Use the snippet for your shell:

<details open>
<summary><strong>Linux &amp; macOS (bash / zsh)</strong></summary>

```bash
# Download and extract (no git history)
curl -fL https://github.com/githubnext/autoloop/archive/refs/heads/main.zip -o /tmp/autoloop.zip
unzip -q /tmp/autoloop.zip -d /tmp/autoloop_extract

# Create target directories
mkdir -p .github/workflows .github/ISSUE_TEMPLATE .autoloop/programs

# Copy files
cp -R /tmp/autoloop_extract/autoloop-main/workflows/. .github/workflows/
cp -R /tmp/autoloop_extract/autoloop-main/.github/ISSUE_TEMPLATE/. .github/ISSUE_TEMPLATE/

# Clean up
rm -rf /tmp/autoloop.zip /tmp/autoloop_extract
```

If `unzip` is not available (e.g. some minimal Linux images), `tar` can extract a zip on macOS and most modern Linux distributions:

```bash
mkdir -p /tmp/autoloop_extract && tar -xf /tmp/autoloop.zip -C /tmp/autoloop_extract
```

</details>

<details>
<summary><strong>Windows (PowerShell)</strong></summary>

```powershell
# Download and extract (no git history)
Invoke-WebRequest -Uri "https://github.com/githubnext/autoloop/archive/refs/heads/main.zip" -OutFile "$env:TEMP\autoloop.zip"
Expand-Archive -Path "$env:TEMP\autoloop.zip" -DestinationPath "$env:TEMP\autoloop_extract" -Force

# Create target directories
New-Item -ItemType Directory -Force -Path ".github/workflows", ".github/ISSUE_TEMPLATE", ".autoloop/programs" | Out-Null

# Copy files
Copy-Item -Path "$env:TEMP\autoloop_extract\autoloop-main\workflows\*" -Destination ".github/workflows/" -Recurse -Force
Copy-Item -Path "$env:TEMP\autoloop_extract\autoloop-main\.github\ISSUE_TEMPLATE\*" -Destination ".github/ISSUE_TEMPLATE/" -Recurse -Force

# Clean up
Remove-Item -Path "$env:TEMP\autoloop.zip", "$env:TEMP\autoloop_extract" -Recurse -Force
```

</details>

> **Note:** The snippets above download the latest `main` branch. To pin to a specific version, replace `refs/heads/main` with `refs/tags/<tag>` and the `autoloop-main` folder name with `autoloop-<tag>`.

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
