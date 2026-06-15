"""
Parser para o Informe de Rendimentos (PDF) da B3.
Extrai dividendos, JCP, rendimento FII e posições inferidas.
"""

import re
from typing import Dict, Any, List, Optional, Union, BinaryIO


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
    # Localiza o fim da seção — "Total" em linha própria (seguido de R$ na próxima)
    # ou marcadores de nova seção
    end_match = re.search(
        r'(?:Reembolso|acesse\s+investidor|Você\s+não\s+possui|Voce\s+nao\s+possui)',
        section, re.IGNORECASE
    )
    content = section[:end_match.start()] if end_match else section[:3000]

    records = []
    lines = [l.strip() for l in content.splitlines() if l.strip()]

    i = 0
    while i < len(lines):
        line = lines[i]

        # Padrão direto: "TICKER Tipo R$ valor"
        direct = re.match(
            r'^([A-Z]{4,5}\d{1,2})\s+'
            r'(Dividendo|Rendimento)\s+'
            r'R\$\s*([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2})$',
            line, re.IGNORECASE
        )
        if direct:
            ticker = direct.group(1).upper()
            tp     = direct.group(2)
            value  = _parse_number(direct.group(3))
            type_d = _detect_provento_type(tp) or {'type': tp, 'ir_type': 9}
            if value > 0:
                records.append({
                    'date': f'31/12/{fallback_year}', 'ticker': ticker,
                    'type': type_d['type'], 'ir_type': type_d['ir_type'], 'value': value,
                })
            i += 1
            continue

        # Padrão quebrado com múltiplas linhas de tipo:
        # "Juros"           → linha i
        # "Sobre"           → linha i+1 (intermediária)
        # "ITUB4 R$ 53,37"  → linha i+2
        # "Capital"         → linha i+3
        # "Próprio"         → linha i+4
        #
        # "RestituiþÒo"    → linha i
        # "VIVT3 R$ 25,90"  → linha i+1
        # "de Capital"      → linha i+2

        is_jcp_hint  = bool(re.search(r'juros|jcp', line, re.IGNORECASE))
        is_rest_hint = bool(re.search(r'restituicao|restituição|restituic|restituiþ', line, re.IGNORECASE))

        if is_jcp_hint or is_rest_hint:
            # Procura o ticker+valor nas próximas 3 linhas (pode ter "Sobre" no meio)
            found = False
            for offset in range(1, 4):
                if i + offset >= len(lines):
                    break
                candidate = lines[i + offset]
                ticker_val = re.match(
                    r'^([A-Z]{4,5}\d{1,2})\s+R\$\s*([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2})$',
                    candidate
                )
                if ticker_val:
                    ticker = ticker_val.group(1).upper()
                    value  = _parse_number(ticker_val.group(2))
                    if value > 0:
                        ir_type = 10 if is_jcp_hint else 9
                        tp = 'Juros Sobre Capital Próprio' if is_jcp_hint else 'Restituição de Capital'
                        records.append({
                            'date': f'31/12/{fallback_year}', 'ticker': ticker,
                            'type': tp, 'ir_type': ir_type, 'value': value,
                        })
                    i += offset + 1  # pula até depois do ticker+valor
                    found = True
                    break
                # Se a linha não é ticker+valor mas também não é indicador de tipo, é intermediária — continua
                elif re.search(r'^(sobre|de|pr[oó]prio|capital|proprio)$', candidate, re.IGNORECASE):
                    continue
                else:
                    break  # linha inesperada, para de procurar
            if found:
                continue

        i += 1

    return records


def _extract_positions_acoes(raw_text: str) -> Dict[str, float]:
    """
    Extrai a tabela 'Posição - Ações' do relatório consolidado anual da B3.
    Retorna {ticker: quantidade} conforme o PDF oficial.
    """
    positions: Dict[str, float] = {}

    # Normaliza o texto (remove encoding quebrado e espaços extras)
    normalized = re.sub(r'\s+', ' ', raw_text)

    # Localiza a seção de ações — aceita encoding corrompido (ações → A[^n]*es, etc.)
    start = re.search(
        r'Posi.{1,10}o\s*[-–]\s*A.{1,5}es',
        normalized, re.IGNORECASE
    )
    if not start:
        # Fallback: busca qualquer linha que tenha ticker + quantidade + R$
        start_idx = 0
    else:
        start_idx = start.end()

    # Corta até a próxima seção
    section = normalized[start_idx:]
    end = re.search(
        r'Posi.{1,10}o\s*[-–]\s*(?:CDB|COE|CRA|DEB|LCI|Op|Empr)',
        section, re.IGNORECASE
    )
    content = section[:end.start()] if end else section[:2000]

    # Padrão: TICKER4 ... quantidade R$ preço
    # O texto extraído tem: "AXIA6 - CENTRAIS ELET BRAS S.A. - ELETROBRAS SANTANDER CCVM PNB 27 R$ 52,42 R$ 1.415,34"
    pattern = re.compile(
        r'\b([A-Z]{4,5}\d{1,2})\b'      # ticker
        r'(?:.*?)'                        # nome (lazy)
        r'\b(\d{1,6}(?:[,\.]\d{1,4})?)\b'  # quantidade
        r'\s+R\$\s*[\d,\.]+\s+R\$',     # R$ preço R$ valor
        re.IGNORECASE,
    )
    for match in pattern.finditer(content):
        ticker = match.group(1).upper()
        raw_qty = match.group(2).replace('.', '').replace(',', '.')
        try:
            qty = float(raw_qty)
        except ValueError:
            continue
        if qty > 0 and qty < 1_000_000:
            # Evita capturar preços grandes como quantidade
            positions[ticker] = qty

    return positions


def parse_informe_pdf(file_path: Union[str, BinaryIO]) -> Dict[str, Any]:
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

    inferred_assets = _extract_positions_acoes(full_text)

    # Extrai nome e CPF do titular (padrão B3: "NOME SOBRENOME | CPF/CNPJ: 12345678901")
    nome_titular = ''
    cpf_titular  = ''
    m_cliente = re.search(
        r'^([A-ZÁÀÂÃÉÊÍÓÔÕÚÇ][A-ZÁÀÂÃÉÊÍÓÔÕÚÇ\s]+?)\s*\|?\s*CPF[/\w]*:\s*([\d]{11})',
        normalized, re.IGNORECASE | re.MULTILINE
    )
    if m_cliente:
        nome_titular = m_cliente.group(1).strip().title()
        raw_cpf = m_cliente.group(2).strip()
        # Formata CPF: 12345678901 → 123.456.789-01
        if len(raw_cpf) == 11:
            cpf_titular = f"{raw_cpf[:3]}.{raw_cpf[3:6]}.{raw_cpf[6:9]}-{raw_cpf[9:]}"
        else:
            cpf_titular = raw_cpf

    notes = []
    if not dividendos and not jcp and not rendimento_fii and not proventos:
        notes.append('Não foram extraídos valores de Dividendos, JCP ou Rendimento FII do PDF.')
    if not inferred_assets:
        notes.append('Não foi possível inferir posições de ativos do PDF.')

    return {
        'raw_text':        full_text,
        'nome_titular':    nome_titular,
        'cpf_titular':     cpf_titular,
        'dividendos':      round(dividendos, 2)      if dividendos      else None,
        'jcp':             round(jcp, 2)             if jcp             else None,
        'rendimento_fii':  round(rendimento_fii, 2)  if rendimento_fii  else None,
        'inferred_assets': inferred_assets,
        'proventos':       proventos,
        'notes':           notes,
    }
