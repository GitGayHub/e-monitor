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


def strip_previous_fault(text):
    """A sealed manufacturer replacement is not the failed previous mouse.

    Remove only the explicit past-device clause. Any fault of the replacement,
    negation, hypothetical claim or missing contents must remain visible.
    """
    prefix = (r"\b(?:brandneu|nagelneu|neu)\s*(?:&|und|,)\s*"
              r"(?:ungeoeffnet|versiegelt)\s*,\s*(?:direkter\s+)?"
              r"austauschartikel\s+vom\s+hersteller\s*,\s*")
    old = (r"\b(?:da|weil)\s+mein(?:e|en|er|es)?\s+"
           r"(?:urspruengliche[nrs]?|alte[nrs]?|vorherige[nrs]?)\s+"
           r"(?:dex|maus|mouse)\s+(?:einen\s+defekt\s+hatte|defekt\s+war)\b")
    def replace(match):
        before = re.split(r"[.!?;\n]", text[:match.start()])[-1]
        if re.search(r"\b(?:nicht|nie|kein\w*|falls|wenn|sofern|not|never|if)\b", before):
            return match.group()
        return re.sub(old, " ", match.group())
    return re.sub(prefix + old, replace, text)


def device_title(text):
    """A model-led title explicitly calls the offered product a mouse."""
    return bool(re.match(r'^(?:logitech\s+)?(?:g\s+)?(?:pro\s*x\s+)?'+MODEL.pattern,text)
                and re.search(r'\b(?:maus|mouse)\b',text))


def feature_title(text):
    """Mask precise device features locally; keep the displayed title intact."""
    if not device_title(text) or re.search(r'\b(?:fuer|for|fits|compatible|kompatibel|nur|only|ersatz\w*|replacement|spare|repair|reparatur\w*)\b',text):
        return text
    # A wired connection is not a separately sold cable. Bare cable nouns stay.
    result=re.sub(r'\b(?:kabelgebunden(?:e|en|er|es)?|wired)\b',' ',text)
    device=re.search(r'\b(?:maus|mouse)\b',result)
    prefix,tail=result[:device.end()],result[device.end():]
    tail=re.sub(r'\bopen\s*box\b',' ',tail)
    # Runtime next to a complete mouse is a feature, not a spare battery.
    if re.search(r'\b(?:kabellos\w*|wireless|\d+\s*k?dpi)\b',result):
        hours=r'[1-9]\d{0,2}\s*(?:h|std|stunden|hours?)'
        battery=r'(?:akku(?:laufzeit)?|battery(?:\s+life)?)'
        tail=re.sub(rf'\b(?:{hours}\s*{battery}|{battery}\s*:?\s*{hours})\b',' ',tail)
    return prefix+tail


def packaging_only(text):
    pattern=r'\b(?:nur|only|lediglich|ausschliesslich)\s+(?:(?:die|das|der|the)\s+)?(?:originalverpackung|verpackung|ovp|karton|box)\b'
    for match in re.finditer(pattern,text):
        # Only the PACKAGING was opened/missing, not an offer of packaging only.
        # Keep subsequent 'without mouse' and every actual device fault.
        if re.match(r'\s+(?:(?:wurde|ist|war)\s+)?(?:geoeffnet|beschaedigt|fehlt)\b|\s+(?:(?:is|was|has\s+been)\s+)?(?:opened|damaged|missing)\b',text[match.end():]):
            continue
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


def own_model_conflict(text, query, confirmed_model=None):
    requested=requested_model(query)
    if requested is None:
        return None
    declarations=[]
    heading=re.match(r'^(?:logitech\s+)?(?:g\s+)?(?:pro\s*x\s*)?'+MODEL.pattern,text)
    if heading:
        declarations.append(heading.group())
    intro=r'\b(?:zum\s+verkauf\s+steht|(?:ich\s+)?verkaufe|i\s+am\s+selling|selling\s+my|for\s+sale\s+is|lieferumfang\s*:?|contents\s*:|(?:model|modell)\s*:)\s*'
    for start in re.finditer(intro,text):
        # Read the complete model token at the window edge, including DEX/SE.
        tail=re.split(r'[.!?;]',text[start.end():start.end()+240],maxsplit=1)[0]
        match=MODEL.search(tail)
        if not match or match.start()>=160:
            continue
        before=tail[:match.start()]
        if re.search(r'\b(?:kein\w*|nicht|no|not|ohne|without)\b',before) or COMPATIBLE.search(before):
            continue
        # A shortened catalogue label may omit the edition when the item's
        # own manufacturer-number field proves it. Never override selling
        # declarations, headings, explicit other editions or contradictory MPNs.
        if (re.fullmatch(r'(?:model|modell)\s*:\s*',start.group())
                and _key(match.group())=='superlight 2' and confirmed_model==requested):
            continue
        declarations.append(match.group())
    for declaration in declarations:
        match=MODEL.search(declaration)
        if match and _key(match.group())!=requested:
            return match.group()
    return None
