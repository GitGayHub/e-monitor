"""Merge seen stages without losing uncertain or interrupted Telegram deliveries."""

STAGES = ('initial', 'final_hour', 'final_15m')


def normalize_seen_state(data):
    state = {}
    if isinstance(data, list):
        for raw in data:
            item = str(raw).strip()
            if item:
                state[item] = {'initial': True, 'final_hour': False, 'final_15m': False}
    elif isinstance(data, dict):
        for raw, value in data.items():
            item = str(raw).strip()
            if not item:
                continue
            if not isinstance(value, dict):
                state[item] = {'initial': True, 'final_hour': False, 'final_15m': False}
                continue
            row = {stage: bool(value.get(stage)) for stage in STAGES}
            uncertain = value.get('deliveryUncertain')
            if isinstance(uncertain, dict):
                row['deliveryUncertain'] = {stage: str(reason)[:80] for stage, reason in uncertain.items() if stage in STAGES}
            pending = value.get('deliveryPending')
            if pending in STAGES:
                row.setdefault('deliveryUncertain', {}).setdefault(pending, 'interrupted_before_confirmation')
            state[item] = row
    return state


def merge_seen_state(first, second):
    a, b = normalize_seen_state(first), normalize_seen_state(second)
    merged = {}
    for item in dict.fromkeys((*a, *b)):
        left, right = a.get(item, {}), b.get(item, {})
        row = {stage: bool(left.get(stage) or right.get(stage)) for stage in STAGES}
        reasons = {}
        for source in (left, right):
            for stage, reason in source.get('deliveryUncertain', {}).items():
                if stage not in reasons:
                    reasons[stage] = reason
                elif reason != reasons[stage]:
                    reasons[stage] = '; '.join(sorted({reasons[stage], reason}))[:80]
        if reasons:
            row['deliveryUncertain'] = reasons
        merged[item] = row
    return merged
