# Monitor fix TODO

For the IDE agent:

Apply the logic from monitor_runtime_patch.py directly into monitor.py.

Tasks:

1. Convert every old search location value eu to worldwide before the search runs.
2. For ebay.de worldwide search, use the real eBay worldwide parameter LH_PrefLoc=3.
3. Do not treat unknown auction time as zero minutes left.
4. Send auction notifications only when rules from monitor_runtime_patch.py pass.
5. Recheck price and auction rules after details refresh and before notification sending.
6. Replace visible text Не with Не найдено where it means not found.
7. Keep mode.txt set to statistics.

Run checks:

python -m py_compile monitor.py config_manager.py test_html_details_live.py
python monitor_runtime_patch.py

Commit message: Apply worldwide auction notification fixes
