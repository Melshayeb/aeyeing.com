"""
GitHub Pages deployment guard for OzMoEg Money Maker.

Uses only the public GitHub API (no tokens) to detect when GitHub Pages is
already deploying or has just failed, so we can skip pushing and avoid the
"Deployment failed, try again later" race.
"""
import json
import logging
import urllib.request
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

REPO = "Melshayeb/aeyeing.com"
WORKFLOW = "pages build and deployment"


def _parse_iso(ts: str) -> datetime:
    if not ts:
        return datetime.min.replace(tzinfo=timezone.utc)
    s = ts.replace('Z', '+00:00')
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return datetime.min.replace(tzinfo=timezone.utc)


def _minutes_ago(ts: str) -> float:
    try:
        dt = _parse_iso(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 60.0
    except Exception:
        return float('inf')


def _api_json(url: str, timeout: int = 15) -> dict:
    """Fetch a GitHub API endpoint without authentication."""
    try:
        req = urllib.request.Request(
            url,
            headers={
                'Accept': 'application/vnd.github+json',
                'User-Agent': 'ozmoeg-pages-guard/1.0',
                'X-GitHub-Api-Version': '2022-11-28',
            }
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        if e.code == 403:
            body = e.read().decode('utf-8', errors='ignore')
            logger.warning("GitHub API rate limited or blocked: %s | %s", url, body[:200])
            return {'__rate_limited__': True, '__error__': str(e)}
        logger.warning("GitHub API HTTP error (%s): %s %s", url, e.code, e.reason)
        return {}
    except Exception as e:
        logger.warning("GitHub API call failed (%s): %s", url, e)
        return {}


def get_latest_pages_run(repo: str = REPO, workflow: str = WORKFLOW) -> dict:
    """Return the most recent Pages workflow run."""
    url = f"https://api.github.com/repos/{repo}/actions/runs?per_page=20&branch=main"
    data = _api_json(url)
    if data.get('__rate_limited__'):
        return {'__rate_limited__': True}
    runs = data.get('workflow_runs', [])
    if not runs:
        return {}
    workflow_lower = workflow.lower()
    for run in runs:
        if workflow_lower in str(run.get('name', '')).lower():
            return run
    return runs[0]


def should_skip_push(min_recent_failure_minutes: float = 8.0) -> tuple[bool, str]:
    """
    Return (skip, reason).  Skip the push when:
    - A Pages run is currently in_progress / queued / requested / waiting.
    - The latest Pages run failed very recently.

    Rate-limiting or other API errors no longer block deployment: the local
    directory lock and cool-down in website_updater._git_push() are enough
    to prevent scanner races, and stale data on the website is worse than a
    possible Pages build collision.
    """
    run = get_latest_pages_run()
    if run.get('__rate_limited__'):
        return False, "GitHub API rate-limited — proceeding with local lock/cool-down only"
    if not run:
        return False, "GitHub API unreachable — proceeding with existing lock/cool-down"

    status = str(run.get('status', '')).lower()
    conclusion = str(run.get('conclusion') or '').lower()
    run_num = run.get('run_number', '?')
    html_url = run.get('html_url', '')
    created_at = run.get('created_at', '')

    in_flight = status in {'in_progress', 'queued', 'requested', 'waiting', 'pending'}
    if in_flight:
        return True, f"GitHub Pages run #{run_num} is {status} ({html_url}) — skipping push"

    if conclusion == 'failure':
        age_min = _minutes_ago(created_at)
        if age_min <= min_recent_failure_minutes:
            return True, (
                f"GitHub Pages run #{run_num} failed {age_min:.1f}m ago "
                f"({html_url}) — cooling off before next push"
            )

    return False, f"GitHub Pages run #{run_num} status={status} conclusion={conclusion} — push ok"


def main():
    skip, reason = should_skip_push()
    print(f"skip={skip} | {reason}")
    return 1 if skip else 0


if __name__ == "__main__":
    raise SystemExit(main())
