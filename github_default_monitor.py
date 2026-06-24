"""Run monitor.py in GitHub Actions without forcing statistics mode.

monitor.py currently treats every GitHub Actions run as Statistics/Diagnostic mode.
This wrapper executes the same monitor.py code, but makes the one-shot GitHub
workflow follow mode.txt/config like local/default monitoring does.
"""

from pathlib import Path
import sys

MONITOR_PATH = Path(__file__).with_name("monitor.py")
FORCED_GITHUB_STATISTICS_LINE = (
    '        test_summary_mode = True if os.environ.get("GITHUB_ACTIONS") == "true" else _is_statistics_mode(config)'
)
DEFAULT_MODE_LINE = '        test_summary_mode = _is_statistics_mode(config)'


def main():
    source = MONITOR_PATH.read_text(encoding="utf-8")
    if FORCED_GITHUB_STATISTICS_LINE in source:
        source = source.replace(FORCED_GITHUB_STATISTICS_LINE, DEFAULT_MODE_LINE, 1)
        print("github_default_monitor: GitHub Actions follows mode.txt/default monitoring mode")
    else:
        print("github_default_monitor: forced statistics line not found; running monitor.py unchanged")

    sys.argv[0] = str(MONITOR_PATH)
    namespace = {
        "__name__": "__main__",
        "__file__": str(MONITOR_PATH),
        "__package__": None,
        "__cached__": None,
    }
    exec(compile(source, str(MONITOR_PATH), "exec"), namespace)


if __name__ == "__main__":
    main()
