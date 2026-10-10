"""Alternate spellings retain the same generation and modification."""
import re


def api_query_batches(aliases, max_length=100):
    """Pack simple OR alternatives within Browse's documented100-character cap.

    An existing parenthesized expression keeps its original grouping. No alias
    or model qualifier is truncated or silently discarded.
    """
    result, group = [], []
    def flush():
        if group:
            result.append(group[0] if len(group)==1 else '('+','.join(group)+')')
            group.clear()
    for raw in aliases:
        alias=raw.strip()
        if not alias: continue
        if any(character in alias for character in '(),'):
            flush();result.append(alias);continue
        proposed='('+','.join(group+[alias])+')'
        if group and len(proposed)>max_length:
            flush()
        group.append(alias)
    flush()
    return result

def api_discovery_queries(aliases):
    """Keep a precise primary request; OR expansion must not drown it in parts."""
    aliases=list(dict.fromkeys(q.strip() for q in aliases if q.strip()))
    if not aliases:return []
    return list(dict.fromkeys([aliases[0], *api_query_batches(aliases[1:])]))


def stored_aliases(query):
    query=query.strip()
    whole=re.fullmatch(r'\((.*)\)',query)
    if whole:return [q.strip().strip('"') for q in whole[1].split(',') if q.strip()]
    embedded=re.fullmatch(r'(.*?)\(([^()]*)\)',query)
    if embedded:return [(embedded[1].strip()+' '+q.strip().strip('"')).strip() for q in embedded[2].split(',') if q.strip()]
    return None

def phone_aliases(query):
    q=' '.join(query.lower().replace('-', ' ').split())
    if re.search(r'\bvivobook\s*14\s*x\b',q) and 'oled' in q:
        return ['asus vivobook 14x oled','asus vivobook14x oled','vivobook 14 x oled']
    m=re.search(r'\biphone\s*(\d{1,2})(?:\s*(pro\s*max|pro|plus|mini|air))?\b',q)
    if m:
        n=m[1];mod=' '.join((m[2] or '').split());suffix=(' '+mod) if mod else ''
        return [f'iphone {n}{suffix}',f'apple iphone {n}{suffix}',f'iphone{n}{suffix}',f'iphone{n}{mod.replace(" ","")}']
    m=re.search(r'\b(?:galaxy\s*)?s(\d{2})(?:\s*(ultra|plus|fe|edge))?\b',q)
    if m:
        n=m[1];mod=m[2] or '';suffix=(' '+mod) if mod else ''
        return [f'samsung galaxy s{n}{suffix}',f'samsung s{n}{suffix}',f'galaxy s{n}{suffix}',f's{n}{mod}']
    m=re.search(r'\bpixel\s*(\d+[a-z]?)(?:\s*(pro\s*xl|pro|xl|fold))?\b',q)
    if m:
        n=m[1];mod=' '.join((m[2] or '').split());suffix=(' '+mod) if mod else ''
        return [f'google pixel {n}{suffix}',f'pixel {n}{suffix}',f'pixel{n}{suffix}']
    m=re.search(r'\b(?:nubia\s+)?z\s*(\d{2})\s*([a-z]?)(?:\s*(ultra|pro))?(?:\s*(leading))?\b',q)
    if m:
        n=m[1];letter=m[2] or '';mod=m[3] or '';leading=' leading' if m[4] or re.search(r'\b(?:lv|leading)\b',q) else '';suffix=(' '+mod) if mod else ''
        if leading:return [f'nubia z{n}{letter}{suffix}{leading}',f'zte nubia z{n}{letter}{suffix}{leading}',f'nubia z{n}{letter}{suffix}{leading} version',f'nubia z{n}{letter}{suffix} lv leading version']
        return [f'nubia z{n}{letter}{suffix}{leading}',f'zte nubia z{n}{letter}{suffix}{leading}',f'nubia z{n} {letter}{suffix}{leading}'.replace('  ',' ')]
    m=re.search(r'\b(?:red\s*magic)\s*(\d{1,2})\s*(s)?(?:\s*(pro|air))?\b',q)
    if m:
        n=m[1];s=m[2] or '';mod=m[3] or '';suffix=(' '+mod) if mod else ''
        return [f'redmagic {n}{s}{suffix}',f'red magic {n}{s}{suffix}',f'nubia redmagic {n}{s}{suffix}',f'redmagic {n} {s}{suffix}'.replace('  ',' ')]
    m=re.search(r'\b(?:(wh|wf)[\s-]*1000[\s-]*)?xm(\d+)\b',q)
    # eBay sellers also omit WH entirely: "Sony 1000XM6".
    unprefixed = re.search(r'\b1000\s*xm(\d+)\b',q) if not m else None
    if m or unprefixed:
        family = (m[1] or 'wh') if m else 'wh'
        generation = m[2] if m else unprefixed[1]
        aliases = [f'sony {family}-1000xm{generation}',
                   f'sony {family}1000xm{generation}',
                   f'sony {family} 1000 xm{generation}']
        if family == 'wh':
            aliases += [f'sony 1000xm{generation}', f'1000xm{generation}']
        return aliases
    return None


def gpu_pc_model(query):
    """GPU plus a whole-PC term; bare graphics-card searches are unchanged."""
    q = query.lower()
    if not re.search(r"\b(?:pc|rechner|computer|desktop)\b", q):
        return None
    match = re.search(r"(?<![a-z0-9])(?:rtx\s*)?(5070\s*ti|4080)\b", q)
    return match[1].replace(' ', '') if match else None


def gpu_pc_aliases(query):
    model = gpu_pc_model(query)
    if not model:
        return None
    gpu = '5070 ti' if model == '5070ti' else model
    aliases = (stored_aliases(query) or []) + [
        f'{gpu} pc', f'{gpu} rechner', f'{gpu} computer', f'{gpu} desktop',
        f'gaming pc {gpu}', f'rtx {gpu} gaming pc', f'RTX{model.upper()}',
    ]
    return list({alias.lower(): alias for alias in aliases}.values())
