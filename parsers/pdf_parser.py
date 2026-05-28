"""
Parser para o Informe de Rendimentos (PDF) da B3.
Extrai dividendos, JCP, rendimento FII e posições inferidas.
"""

import re
from typing import Dict, Any, List, Optional


def _parse_number(value: str) -> float:
    s = re.sub(r'R\$|\s+', '', str(value))
    s = s.replace('.', '').replace(',', '.')
    s = re.sub(r'[^0-9.\-]', '', s)
    try:
        return float(s)
    except ValueError:
        return 0.0


def _extract_amount(text: str, pattern: re.Pattern) -> Optional[float]:
    match = pattern.search(text)
    if not match:
        return None
    raw = match.group(1) or match.group(0)
    val = _parse_number(raw)
    return val if val != 0 else None


def _detect_provento_type(line: str):
    lower = line.lower()
    if re.search(r'jcp|juros\s+sobre\s+capital', lower):
        return {'type': 'JCP', 'ir_type': 10}
    if re.search(r'dividend', lower):
        return {'type': 'Dividendo', 'ir_type': 9}
    if re.search(r'rendimento', lower):
        return {'type': 'Rendimento', 'ir_type': 26}
    return None


def _extract_proventos_lines(raw_text: str, fallback_year: int) -> List[Dict]:
    start_match = re.search(r'proventos\s+recebidos', raw_text, re.IGNORECASE)
    if not start_match:
        return []

    section = raw_text[start_match.end():]
    normalized = re.sub(r'\s+', ' ', section).strip()
    end_match = re.search(r'\bTotal\b', normalized, re.IGNORECASE)
    content = normalized[:end_match.start()] if end_match else normalized

    records = []
    pattern = re.compile(
        r'\b([A-Z]{4,5}\d{1,2})\b\s+'
        r'(Dividendo|Juros\s+Sobre\s+Capital\s+Pr[oó]prio|Rendimento)\s+'
        r'R\$\s*([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2})',
        re.IGNORECASE,
    )
    for match in pattern.finditer(content):
        ticker   = match.group(1).upper()
        raw_type = match.group(2)
        raw_val  = match.group(3)
        type_data = _detect_provento_type(raw_type)
        if not type_data:
            continue
        value = _parse_number(raw_val)
        if value <= 0:
            continue
        records.append({
            'date':    f'31/12/{fallback_year}',
            'ticker':  ticker,
            'type':    type_data['type'],
            'ir_type': type_data['ir_type'],
            'value':   value,
        })
    return records


def _extract_positions(raw_text: str) -> Dict[str, float]:
    positions: Dict[str, float] = {}
    ticker_re = re.compile(r'\b([A-Z]{4,5}\d{1,2})\b')
    qty_re    = re.compile(
        r'([0-9]{1,3}(?:\.[0-9]{3})*(?:,[0-9]+)?)'
        r'(?=\s*(?:ações|unidades|cotas|qtde|qt|quantidade|qty|shares)?)',
        re.IGNORECASE,
    )
    for line in raw_text.splitlines():
        line = line.strip()
        if not line:
            continue
        ticker_match = ticker_re.search(line)
        if not ticker_match:
            continue
        qty_match = qty_re.search(line)
        if not qty_match:
            continue
        ticker = ticker_match.group(1)
        qty    = _parse_number(qty_match.group(1))
        if qty > 0:
            positions[ticker] = positions.get(ticker, 0) + qty
    return positions


def parse_informe_pdf(file_path: str) -> Dict[str, Any]:
    try:
        import pdfplumber
        full_text = ''
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ''
                full_text += text + '\n'
    except Exception as e:
        return {
            'raw_text': '',
            'dividendos': None,
            'jcp': None,
            'rendimento_fii': None,
            'inferred_assets': {},
            'proventos': [],
            'notes': [f'Falha ao ler o PDF: {e}'],
        }

    normalized = re.sub(r'\s+', ' ', full_text)

    year_match = re.search(r'\b(20\d{2})\b', normalized)
    year_hint  = int(year_match.group(1)) if year_match else 2024

    proventos = _extract_proventos_lines(full_text, year_hint)

    totals = {'dividendos': 0.0, 'jcp': 0.0, 'rendimento_fii': 0.0}
    for row in proventos:
        if row['ir_type'] == 9:
            totals['dividendos'] += row['value']
        elif row['ir_type'] == 10:
            totals['jcp'] += row['value']
        elif row['ir_type'] == 26:
            totals['rendimento_fii'] += row['value']

    dividendos     = _extract_amount(normalized, re.compile(r'dividend(?:os?)?\s*[R$]*\s*([0-9.,]+)', re.I)) \
                     or (totals['dividendos'] or None)
    jcp            = _extract_amount(normalized, re.compile(r'jcp\s*[R$]*\s*([0-9.,]+)', re.I)) \
                     or (totals['jcp'] or None)
    rendimento_fii = _extract_amount(normalized, re.compile(r'rendimento\s+fii\s*[R$]*\s*([0-9.,]+)', re.I)) \
                     or (totals['rendimento_fii'] or None)

    inferred_assets = _extract_positions(full_text)

    notes = []
    if not dividendos and not jcp and not rendimento_fii and not proventos:
        notes.append('Não foram extraídos valores de Dividendos, JCP ou Rendimento FII do PDF.')
    if not inferred_assets:
        notes.append('Não foi possível inferir posições de ativos do PDF.')

    return {
        'raw_text':        full_text,
        'dividendos':      round(dividendos, 2)      if dividendos      else None,
        'jcp':             round(jcp, 2)             if jcp             else None,
        'rendimento_fii':  round(rendimento_fii, 2)  if rendimento_fii  else None,
        'inferred_assets': inferred_assets,
        'proventos':       proventos,
        'notes':           notes,
    }
