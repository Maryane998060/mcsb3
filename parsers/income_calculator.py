"""
Classifica proventos (dividendos, JCP, rendimentos FII) a partir da Movimentação.
"""

import unicodedata
from typing import List, Dict, Any, Tuple


def _norm(s: str) -> str:
    s = unicodedata.normalize('NFD', str(s or ''))
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return s.lower()


def _get_year(date_str: str) -> int:
    if not date_str:
        return 0
    parts = date_str.strip().split('/')
    if len(parts) != 3:
        return 0
    try:
        return int(parts[2])
    except ValueError:
        return 0


def _round2(n: float) -> float:
    return round(n, 2)


def _is_fii(ticker: str) -> bool:
    """FII: exatamente 4 letras + 11 ou 12."""
    import re
    return bool(re.match(r'^[A-Z]{4}(11|12)$', ticker))


# Padrões de reconhecimento de provento
_INCOME_PATTERNS = [
    {
        'match': lambda t: 'dividendo' in t,
        'type':    'Dividendo',
        'ir_type': lambda ticker: 9,
    },
    {
        'match': lambda t: 'juros sobre capital' in t or 'jcp' in t or 'juros s/ capital' in t or 'juros s.capital' in t,
        'type':    'Juros Sobre Capital Próprio',
        'ir_type': lambda ticker: 10,
    },
    {
        'match': lambda t: 'rendimento' in t,
        'type':    'Rendimento',
        'ir_type': lambda ticker: 26 if _is_fii(ticker) else 9,
    },
    {
        'match': lambda t: 'remuneracao' in t or 'remuneração' in t,
        'type':    'Rendimento',
        'ir_type': lambda ticker: 26 if _is_fii(ticker) else 9,
    },
]


def calculate_income(movements: List[Dict], year: int) -> List[Dict]:
    events: List[Dict] = []

    for m in movements:
        if _get_year(m['date']) != year:
            continue
        # Só créditos são proventos recebidos
        if m.get('credit_debit') and 'debito' in _norm(m['credit_debit']):
            continue

        type_str = _norm(m['type'])
        ticker   = m['product'].split(' - ')[0].strip().upper()
        if not ticker:
            continue

        matched = None
        for pattern in _INCOME_PATTERNS:
            if pattern['match'](type_str):
                matched = pattern
                break
        if not matched:
            continue

        value = _round2(m['operation_value'])
        if value <= 0:
            continue

        events.append({
            'date':       m['date'],
            'ticker':     ticker,
            'type':       matched['type'],
            'ir_type':    matched['ir_type'](ticker),
            'value':      value,
            'quantity':   m['quantity'],
            'unit_price': m['unit_price'],
        })

    events.sort(key=lambda e: (
        int(e['date'].split('/')[2]),
        int(e['date'].split('/')[1]),
        int(e['date'].split('/')[0]),
    ))
    return events


def aggregate_by_ir_type(events: List[Dict]) -> Dict[str, float]:
    tax9 = tax10 = tax26 = 0.0
    for e in events:
        if e['ir_type'] == 9:
            tax9  += e['value']
        elif e['ir_type'] == 10:
            tax10 += e['value']
        elif e['ir_type'] == 26:
            tax26 += e['value']
    return {
        'tax9':  _round2(tax9),
        'tax10': _round2(tax10),
        'tax26': _round2(tax26),
        'total': _round2(tax9 + tax10 + tax26),
    }


def detect_year_from_movements(movements: List[Dict], fallback: int) -> int:
    """Detecta o ano mais recente dos proventos nos dados."""
    income_types = {'dividendo', 'juros sobre capital', 'jcp', 'rendimento', 'remuneracao', 'remuneração'}
    years = []
    for m in movements:
        if not ('credito' in _norm(m.get('credit_debit', '')) or 'crédito' in m.get('credit_debit', '').lower()):
            continue
        if m.get('operation_value', 0) <= 0:
            continue
        tl = _norm(m.get('type', ''))
        if not any(k in tl for k in income_types):
            continue
        y = _get_year(m['date'])
        if y > 2000:
            years.append(y)
    return max(years) if years else fallback
