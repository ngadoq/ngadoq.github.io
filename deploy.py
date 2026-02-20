import argparse
import os
import shutil
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from typing import Callable

# ── Try importing dependencies ──────────────────────────────────────────────
try:
    import requests
except ImportError:
    sys.exit("Missing dependency: run  pip install requests gitpython")
try:
    import git
except ImportError:
    sys.exit("Missing dependency: run  pip install requests gitpython")


# ── Config ──────────────────────────────────────────────────────────────────
PORTFOLIO_FILES = [
    "index.html",

]


def run(cmd: list[str], cwd: Path = None, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, check=check, capture_output=True, text=True)


def github_api(method: str, path: str, token: str, json: dict = None) -> requests.Response:
    resp = requests.request(
        method,
        f"https://api.github.com{path}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        json=json,
        timeout=15,
    )
    return resp


def ensure_repo_exists(username: str, repo: str, token: str, private: bool = False) -> str:
    """Create GitHub repo if it doesn't exist. Returns clone URL."""
    resp = github_api("GET", f"/repos/{username}/{repo}", token)
    if resp.status_code == 200:
        print(f"  ✓ Repo '{repo}' already exists on GitHub.")
        return resp.json()["clone_url"]

    print(f"  Creating repo '{repo}' on GitHub...")
    payload = {
        "name": repo,
        "description": "Nga Do — Human-Centered AI Researcher Portfolio",
        "homepage": f"https://{username}.github.io",
        "private": private,
        "auto_init": False,
    }
    resp = github_api("POST", "/user/repos", token, json=payload)
    if resp.status_code not in (200, 201):
        sys.exit(f"  ✗ Could not create repo: {resp.status_code} {resp.text}")

    print(f"  ✓ Repo created.")
    return resp.json()["clone_url"]


def enable_github_pages(username: str, repo: str, token: str) -> str:
    """Enable GitHub Pages on main branch and return the pages URL."""
    resp = github_api(
        "POST",
        f"/repos/{username}/{repo}/pages",
        token,
        json={"source": {"branch": "main", "path": "/"}},
    )
    if resp.status_code in (201, 422):  # 422 = already enabled
        url = f"https://{username}.github.io/" if repo == f"{username}.github.io" else f"https://{username}.github.io/{repo}"
        print(f"  ✓ GitHub Pages enabled → {url}")
        return url
    print(f"  ⚠ Pages API returned {resp.status_code}: {resp.text}")
    print(f"    You can enable Pages manually at: https://github.com/{username}/{repo}/settings/pages")
    return f"https://{username}.github.io/{repo}"


def _handle_remove_readonly(func: Callable, path: str, exc_info) -> None:
    # Windows can mark .git objects as read-only; clear the flag and retry.
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass
    func(path)


def deploy(username: str, repo: str, token: str, source_dir: Path, open_browser: bool):
    print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("  Nga Do — Portfolio Deployer")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")

    # ── 1. Ensure GitHub repo exists ─────────────────────────────────────────
    print("[1/5] Checking GitHub repository...")
    remote_url = ensure_repo_exists(username, repo, token)

    # ── 2. Set up local git repo ──────────────────────────────────────────────
    print("\n[2/5] Preparing local repository...")
    local_dir = Path.home() / f"{repo}_deploy"

    if local_dir.exists():
        shutil.rmtree(local_dir, onerror=_handle_remove_readonly)
    local_dir.mkdir(parents=True)

    local_repo = git.Repo.init(local_dir)
    
    # Configure git identity (required for commits)
    with local_repo.config_writer() as cfg:
        cfg.set_value("user", "name", username)
        cfg.set_value("user", "email", f"{username}@users.noreply.github.com")

    print(f"  ✓ Initialized git repo at {local_dir}")

    # ── 3. Copy portfolio files ───────────────────────────────────────────────
    print("\n[3/5] Copying portfolio files...")
    for item in PORTFOLIO_FILES:
        src = source_dir / item
        dst = local_dir / item
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
            print(f"  ✓ Copied directory: {item}")
        elif src.is_file():
            shutil.copy2(src, dst)
            print(f"  ✓ Copied file: {item}")
        else:
            print(f"  ⚠ Skipping missing file: {item}")

    # ── 4. Commit and push ────────────────────────────────────────────────────
    print("\n[4/5] Committing and pushing to GitHub...")
    local_repo.git.add(A=True)
    local_repo.index.commit("Deploy portfolio 🚀")

    # Embed token in remote URL for auth
    authed_url = remote_url.replace("https://", f"https://{token}@")
    try:
        origin = local_repo.create_remote("origin", authed_url)
    except git.exc.GitCommandError:
        origin = local_repo.remotes.origin
        origin.set_url(authed_url)

    try:
        origin.push(refspec="main:main", force=True)
    except git.exc.GitCommandError:
        # Older git may need to push to master-style branch name
        local_repo.git.branch("-M", "main")
        origin.push(refspec="main:main", force=True)

    print("  ✓ Pushed to GitHub.")

    # ── 5. Enable GitHub Pages ────────────────────────────────────────────────
    print("\n[5/5] Enabling GitHub Pages...")
    pages_url = enable_github_pages(username, repo, token)

    # ── Done ──────────────────────────────────────────────────────────────────
    print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("  ✅ Deployment complete!")
    print(f"  🌐 Your portfolio will be live at:")
    print(f"     {pages_url}")
    print("  ⏳ GitHub Pages can take 1–2 minutes to publish.")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")

    if open_browser:
        print("  Opening browser in 5 seconds...")
        time.sleep(5)
        webbrowser.open(pages_url)


def main():
    parser = argparse.ArgumentParser(
        description="Deploy Nga's portfolio to GitHub Pages",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python deploy.py --username ngado --repo portfolio
  python deploy.py --username ngado --repo ngado.github.io  # apex domain option

Getting a GitHub token:
  1. Go to github.com → Settings → Developer Settings → Personal Access Tokens → Tokens (classic)
  2. Generate new token with scopes: repo, write:pages
  3. Pass it via --token or set env var GITHUB_TOKEN
        """,
    )
    parser.add_argument("--username", required=True, help="Your GitHub username")
    parser.add_argument("--repo", default="portfolio", help="Repo name (default: portfolio)")
    parser.add_argument(
        "--token",
        default=os.environ.get("GITHUB_TOKEN", ""),
        help="GitHub Personal Access Token (or set GITHUB_TOKEN env var)",
    )
    parser.add_argument(
        "--source",
        default=str(Path(__file__).parent),
        help="Folder containing index.html (default: same folder as this script)",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Don't open browser after deploy",
    )

    args = parser.parse_args()

    if not args.token:
        sys.exit(
            "✗ GitHub token required.\n"
            "  Pass --token YOUR_TOKEN  or  export GITHUB_TOKEN=YOUR_TOKEN\n\n"
            "  Create one at: github.com → Settings → Developer Settings → Personal Access Tokens\n"
            "  Required scopes: repo, write:pages"
        )

    deploy(
        username=args.username,
        repo=args.repo,
        token=args.token,
        source_dir=Path(args.source),
        open_browser=not args.no_browser,
    )


if __name__ == "__main__":
    main()
