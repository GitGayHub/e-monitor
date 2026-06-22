import sys
sys.stdout.reconfigure(encoding='utf-8')

try:
    import monitor_runtime_patch
    monitor_runtime_patch.patch_monitor()
    monitor_runtime_patch.migrate_config()
    print('monitor patch applied')
except Exception as exc:
    print(f'monitor patch skipped: {exc}')
