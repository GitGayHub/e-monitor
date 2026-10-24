"""Purpose and explicit seller model declarations for whole mice, not compatibility."""
import re

MODEL = re.compile(r'\b(?:superstrike|(?:superlight|gpx)\s*(?:2|ii)c?\b(?:[\s-]+(?:dex|se)\b)?|(?:g\s*)?pro\s*2\s+lightspeed)\b')
CONNECTOR = re.compile(r'\b(?:mit|and|inkl|with|bundle)\b|(?<=\s)\+(?=\s)|(?<=\s)&(?=\s)')
COMPATIBLE = re.compile(r'\b(?:fuer|for|voor|para|pour|per|kompatibel|compatible|fits)\b|\bf\s*\.\s*')
PACKAGING = {'ovp','verpackung','karton','box','originalverpackung'}
BUNDLED = {'skates','skate','glides','glide','feet','mouse feet','mausfuesse','mausgleiter','grip','tape','grip tape','receiver','dongle','empfaenger'}


def _key(value):
    if 'superstrike' in value:
        return 'superstrike'
    if 'lightspeed' in value:
        return 'pro 2 lightspeed'
    compact = bool(re.search(r'(?:2|ii)c\b', value))
    suffix = next((word for word in ('dex','se') if re.search(r'\b'+word+r'\b',value)), '')
    return 'superlight 2'+('c' if compact else '')+(' '+suffix if suffix else '')


def requested_model(query):
    match=MODEL.search(query)
    return _key(match.group()) if match else None


def packaging_only(text):
    pattern=r'\b(?:nur|only|lediglich|ausschliesslich)\s+(?:(?:die|das|der|the)\s+)?(?:originalverpackung|verpackung|ovp|karton|box)\b'
    for match in re.finditer(pattern,text):
        if not re.search(r'\b(?:nicht|not)\s*$',text[max(0,match.start()-12):match.start()]):
            return True
    return bool(re.search(r'\b(?:ohne|without|keine?)\s+(?:die\s+|the\s+)?(?:maus|mouse)\b|\b(?:maus|mouse)\s+(?:(?:ist|is)\s+)?(?:nicht\s+(?:enthalten|dabei)|not\s+included)\b',text))


def bundled_stop_word(title, word, is_bundle=False):
    if word in PACKAGING:
        device=re.search(r'\b(?:maus|mouse)\b',title)
        packaging=re.search(r'\b'+re.escape(word)+r'\b',title)
        return bool(device and packaging and device.start()<packaging.start() and not COMPATIBLE.search(title) and not packaging_only(title))
    if word not in BUNDLED or not is_bundle:
        return False
    connector=CONNECTOR.search(title)
    term=re.compile(r'\b'+re.escape(word)+r'\b')
    return bool(connector and not term.search(title[:connector.start()]) and term.search(title[connector.end():]))


def own_model_conflict(text, query):
    requested=requested_model(query)
    if requested is None:
        return None
    declarations=[]
    heading=re.match(r'^(?:logitech\s+)?(?:g\s+)?(?:pro\s*x\s*)?'+MODEL.pattern,text)
    if heading:
        declarations.append(heading.group())
    intro=r'\b(?:zum\s+verkauf\s+steht|(?:ich\s+)?verkaufe|i\s+am\s+selling|selling\s+my|for\s+sale\s+is|lieferumfang\s*:?|contents\s*:|(?:model|modell)\s*:)\s*'
    for start in re.finditer(intro,text):
        tail=re.split(r'[.!?;]',text[start.end():start.end()+160],maxsplit=1)[0]
        match=MODEL.search(tail)
        if not match:
            continue
        before=tail[:match.start()]
        if re.search(r'\b(?:kein\w*|nicht|no|not|ohne|without)\b',before) or COMPATIBLE.search(before):
            continue
        declarations.append(match.group())
    for declaration in declarations:
        match=MODEL.search(declaration)
        if match and _key(match.group())!=requested:
            return match.group()
    return None
