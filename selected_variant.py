"""Own, selected phone capacity/colour with an exact live purchase price.

No requests and no guessing from a generic title, a range or recommendation.
Unknown dimension types stay unverified.
"""
import copy
import json
import math
import re
from urllib.parse import urlparse,parse_qs


def _number(raw):
    if isinstance(raw,dict):
        if raw.get('currency','EUR')!='EUR':return None
        raw=raw.get('value')
    if isinstance(raw,bool):return None
    try:value=float(raw)
    except (ValueError,TypeError):return None
    return value if math.isfinite(value) and value>0 else None


def _state(soup,key):
    values=[]
    decoder=json.JSONDecoder()
    for script in soup.find_all('script'):
        for match in re.finditer(r'"'+re.escape(key)+r'"\s*:\s*',script.string or script.get_text()):
            try:values.append(decoder.raw_decode((script.string or script.get_text())[match.end():])[0])
            except (ValueError,TypeError):return None
    return values[0] if len(values)==1 else None


def _parse(soup,details):
    canonical=soup.select_one('link[rel=canonical]')
    if not canonical:return None
    url=urlparse(canonical.get('href',''))
    own=re.fullmatch(r'/itm/(\d{12})',url.path)
    if url.scheme!='https' or url.hostname not in ('www.ebay.de','www.ebay.com','www.ebay.co.uk') or not own:return None
    modules=soup.select('#mainContent .x-msku-evo')
    actions=soup.select('#mainContent .x-bin-action > a[href]')
    if len(modules)!=1 or len(actions)!=1:return None
    action=actions[0]
    if action.get('aria-disabled')=='true' or action.has_attr('disabled'):return None
    target=urlparse(action.get('href',''))
    args=parse_qs(target.query)
    if target.scheme!='https' or target.hostname!=url.hostname or target.path!='/atc/binctr' or args.get('item')!=[own[1]] or args.get('quantity')!=['1']:return None
    values=args.get('var',[])
    if len(values)!=1:return None
    variant=values[0]
    if not re.fullmatch(r'\d{12}',variant):return None
    if str(_state(soup,'selectedVariationId'))!=variant:return None
    items=_state(soup,'menuItemMap');variants=_state(soup,'variationsMap')
    if not isinstance(items,dict) or not isinstance(variants,dict):return None
    selected=variants.get(variant,{})
    quantity=selected.get('quantity',{})
    limits=quantity.get('quantityInput',{}).get('validations',[])
    if quantity.get('outOfStock') is not False or not any((_number(x.get('maxValue')) or 0)>=1 for x in limits):return None
    price=_number(selected.get('binModel',{}).get('price',{}).get('value'))
    if price is None or price!=_number(details.get('price')) or details.get('buyingOptions')!=['FIXED_PRICE']:return None
    attributes=[]
    fields=modules[0].select('.x-sku')
    if not fields:return None
    for field in fields:
        label=field.select_one('.btn__label');native=field.select('select option[selected]')
        active=field.select('[role=option][aria-selected=true]')
        if not label or len(native)!=1 or len(active)!=1:return None
        if native[0].has_attr('disabled') or active[0].get('aria-disabled')=='true':return None
        name=label.get_text(' ',strip=True).rstrip(':').strip()
        record=items.get(native[0].get('value'),{})
        value=active[0].get('data-sku-value-name','').strip()
        if record.get('valueName')!=value or record.get('outOfStock') is not False or int(variant) not in record.get('matchingVariationIds',[]):return None
        kind=re.sub(r'[\s_-]','',name.lower())
        if kind in ('storagecapacity','speicherkapazität','speicherkapazitaet'):
            if not re.fullmatch(r'\d+\s*(?:GB|TB)(?:\s+\d+\s*GB\s*RAM)?',value,re.I):return None
        elif kind in ('color','colour','farbe'):
            if not re.fullmatch(r'(?:(?:titanium|titan|icy|jet|deep|starry|cosmic|natural|midnight)\s*)?(?:black|gold|silver|white|blue|green|grey|gray|violet|purple|orange|yellow|pink|red|night|schwarz|silber|weiss|weiß|blau|gruen|grün|grau|lila|rot)',value,re.I):return None
        else:return None
        attributes.append({'name':name,'value':value})
    return {'itemId':own[1],'id':variant,'url':canonical['href']+'?var='+variant,'price':{'value':price,'currency':'EUR'},'attributes':attributes}


def parse(soup,details):
    try:return _parse(soup,details)
    except (ValueError,TypeError,AttributeError,KeyError,IndexError,OverflowError):return None


def valid(details,item_id=None):
    proof=details.get('selectedVariant')
    if not isinstance(proof,dict) or not proof.get('attributes') or details.get('buyingOptions')!=['FIXED_PRICE']:return False
    if item_id is not None and str(item_id)!=proof.get('itemId'):return False
    return _number(proof.get('price')) is not None and _number(proof['price'])==_number(details.get('price'))


def matches(details,item_id,query):
    if not item_id or not valid(details,item_id):return False
    storage=next((a['value'] for a in details['selectedVariant']['attributes'] if 'capacity' in a['name'].lower() or 'speicher' in a['name'].lower()),'')
    selected=re.match(r'(\d+)\s*(GB|TB)',storage,re.I)
    requested=re.findall(r'\b(64|128|256|512|1024|2048)\s*(gb)\b|\b([12])\s*(tb)\b',query,re.I)
    wanted=[int(gb) if gb else int(tb)*1024 for gb,_,tb,_ in requested]
    actual=int(selected[1])*(1024 if selected[2].lower()=='tb' else 1) if selected else None
    return not wanted or actual is not None and all(x==actual for x in wanted)


def enrich(soup,details):
    proof=parse(soup,details)
    if not proof:return details
    result=copy.deepcopy(details);result['selectedVariant']=proof
    attrs=proof['attributes']
    storage=next((a['value'] for a in attrs if 'capacity' in a['name'].lower() or 'speicher' in a['name'].lower()),'')
    title=result.get('title','');result['originalTitle']=title
    if storage:
        capacity=re.match(r'\d+\s*(?:GB|TB)',storage,re.I)[0]
        title=re.sub(r'\b(?:64|128|256|512|1024|2048)\s*GB\b|\b[12]\s*TB\b',lambda _:capacity,title,flags=re.I)
        ram=re.search(r'\b(\d+)\s*GB\s*RAM\b',storage,re.I)
        if ram:title=re.sub(r'\b\d+\s*GB\s*RAM\b',lambda _:ram[0],title,flags=re.I)
        aspects=[a for a in result.get('localizedAspects',[]) if re.sub(r'\s','',a.get('name','').lower()) not in ('speicherkapazität','speicherkapazitaet','storagecapacity','ram','arbeitsspeicher')]
        aspects.append({'name':'Speicherkapazität','value':capacity})
        if ram:aspects.append({'name':'RAM','value':ram[1]+'GB'})
        result['localizedAspects']=aspects
    result['title']=title+' ['+'; '.join(a['value'] for a in attrs)+']'
    return result
