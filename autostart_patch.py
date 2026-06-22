import os
import runpy

if os.path.exists('monitor_runtime_patch.py'):
    runpy.run_path('monitor_runtime_patch.py', run_name='__main__')
