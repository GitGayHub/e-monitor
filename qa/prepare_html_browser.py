"""Prepare optional HTML rendering without waiting on apt when it is unnecessary.

The same entrypoint runs on the disposable QA runner and in the monitor job.
Failure leaves HTML HTTP/API retrieval available; only a real render is success.
"""
import subprocess
import sys
import time

SMOKE = """
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=['--disable-dev-shm-usage'])
    page = browser.new_page()
    page.set_content('<h1>eMonitor browser ready</h1>')
    assert page.locator('h1').inner_text() == 'eMonitor browser ready'
    browser.close()
"""


def stage(label, command, seconds):
    # GNU timeout kills the whole installer process group, including apt/node.
    # subprocess's timeout alone would only kill its direct child.
    if sys.platform.startswith('linux'):
        command = ['timeout', '--kill-after=5s', str(seconds)+'s', *command]
    try:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, timeout=seconds+10)
        output = result.stdout or ''
        print(f'{label}: exit={result.returncode}\n{output}', flush=True)
        return result.returncode, output
    except (subprocess.TimeoutExpired, OSError) as exc:
        print(f'{label}: {type(exc).__name__}', flush=True)
        return 1, str(exc)


def prepare():
    started = time.monotonic()
    code, _ = stage('Download headless Chromium',
                    [sys.executable, '-m', 'playwright', 'install', '--only-shell', 'chromium'], 70)
    if code:
        return 1
    code, output = stage('Render HTML', [sys.executable, '-c', SMOKE], 15)
    strategy = 'headless_without_apt'
    if code:
        missing_deps = any(marker in output.lower() for marker in (
            'host system is missing dependencies', 'error while loading shared libraries',
            'cannot open shared object file'))
        if not missing_deps or not sys.platform.startswith('linux'):
            return 1
        code, _ = stage('Install missing browser libraries',
                        [sys.executable, '-m', 'playwright', 'install-deps', 'chromium'], 60)
        if code:
            return 1
        code, _ = stage('Render HTML after dependencies', [sys.executable, '-c', SMOKE], 15)
        if code:
            return 1
        strategy = 'bounded_missing_dependencies'
    print(f'HTML_BROWSER_READY strategy={strategy} elapsed={time.monotonic()-started:.1f}s', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(prepare())
