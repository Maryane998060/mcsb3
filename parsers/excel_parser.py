"""
Parsers para planilhas B3: Negociação e Movimentação.
Suporta os dois formatos (8 e 9 colunas) do investor.b3.com.br.
"""

import re
import unicodedata
from typing import List, Dict, Optional, Any, Union, BinaryIO
import openpyxl


# ── Utilitários ────────────────────────────────────────────────────────────────

def _norm(s: Any) -> str:
    """Normaliza string para comparação: lowercase, sem acento, alfanumérico+underscore."""
    s = unicodedata.normalize('NFD', str(s or ''))
    s = ''.join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = re.sub(r'[^a-z0-9]+', '_', s)
    return s.strip('_')


def _search_norm(s: Any) -> str:
    """Normaliza texto para buscas com espaços e termos legíveis."""
    s = unicodedata.normalize('NFD', str(s or ''))
    s = ''.join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = re.sub(r'[^a-z0-9\s]+', ' ', s)
    s = re.sub(r'\s+', ' ', s)
    return s.strip()


def _parse_number(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if not value:
        return 0.0
    s = str(value)
    s = re.sub(r'R\$\s*', '', s)
    # Formato BR: ponto = milhar, vírgula = decimal
    s = s.replace('.', '').replace(',', '.').strip()
    try:
        return float(s)
    except ValueError:
        return 0.0


def _normalize_ticker(ticker: str) -> str:
    """
    Higieniza o ticker removendo prefixos de Termo de Ação, acentos e
    valores residuais de tabelas, retornando o ticker base válido.
    """
    if not ticker:
        return ''

    t = unicodedata.normalize('NFD', str(ticker or ''))
    t = ''.join(c for c in t if not unicodedata.combining(c))
    t = t.upper().strip()
    t = re.sub(r'\s+', ' ', t)

    # Remove prefixos de termo/opção não relevantes para o ticker base
    t = re.sub(
        r'^(?:TERMO\s+DE\s+ACAO|TERMOA?CAO|TERMO|OPCAO|OPÇÃO|TERMO\s+DE\s+ACAO|TERMO\s+DE\s+ACOES?)\b\s*',
        '',
        t,
        flags=re.IGNORECASE,
    )

    # Extraia o ticker base entre os tokens. Procura um padrão que comece com 2-5 letras,
    # seguido de 1-3 dígitos, e opcionalmente termine com T ou F.
    # Ex: "B3SA3", "VBBR3T", "AXIA11"
    clean = re.sub(r'[^A-Z0-9]+', ' ', t)
    found_ticker = None
    
    # Primeira tentativa: procura entre as palavras separadas
    for part in clean.split():
        if re.match(r'^[A-Z]{2,5}\d{1,3}[TF]?$', part):
            found_ticker = part
            break
    
    # Fallback: procura dentro da string como um todo (para casos como "B3SA3")
    if not found_ticker:
        # Procura uma sequência contínua de letras e dígitos que forme um ticker válido
        # Usa uma busca gulosa para evitar capturar apenas "SA3" em "B3SA3"
        m = re.search(r'([A-Z]+\d+[A-Z]*\d*[TF]?|[A-Z]+\d+)', clean)
        if m and len(m.group(0)) > 2:
            found_ticker = m.group(0)
    
    if found_ticker:
        t = found_ticker

    # Remove sufixos residuais de fração ou tabela
    if t.endswith('T') and len(t) > 4:
        t = t[:-1]
    if re.match(r'^[A-Z]{4,5}\d{1,2}F$', t):
        t = t[:-1]

    tabela_conversao = {
        'ELET6': 'AXIA6',
        'EMBR3': 'EMBJ3',
        'BRDT3': 'VBBR3'
    }

    return tabela_conversao.get(t, t)


def _extract_cnpj(value: Any) -> str:
    text = str(value or '')
    match = re.search(r'\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}', text)
    return match.group(0) if match else ''


def _read_rows(file_path: Union[str, BinaryIO]) -> List[List[Any]]:
    # read_only=True é evitado porque arquivos B3 têm dimensão incorreta (ex: A1:A1)
    # o que faz o openpyxl retornar apenas 1 linha no modo read-only.
    wb = openpyxl.load_workbook(file_path, data_only=True)
    ws = wb.worksheets[0]
    rows = []
    for row in ws.iter_rows(values_only=True):
        rows.append(list(row))
    wb.close()
    return rows


def _find_header_row(rows: List[List[Any]], keywords: List[str]) -> int:
    """Localiza linha de cabeçalho (retorna índice da primeira linha de dados)."""
    norm_kw = [_norm(k) for k in keywords]
    for i, row in enumerate(rows[:30]):
        if not row:
            continue
        row_text = '|'.join(_norm(str(c or '')) for c in row)
        if any(k in row_text for k in norm_kw):
            return i + 1
    return 1


def _build_col_map(header_row: List[Any]) -> Dict[str, int]:
    col_map: Dict[str, int] = {}
    for idx, cell in enumerate(header_row):
        key = _norm(str(cell or ''))
        if key:
            col_map[key] = idx
    return col_map


def _col_idx(col_map: Dict[str, int], *candidates: str) -> int:
    for c in candidates:
        n = _norm(c)
        if n in col_map:
            return col_map[n]
    return -1


# ── Negociação ─────────────────────────────────────────────────────────────────

def parse_negociacao_sheet(file_path: Union[str, BinaryIO]) -> List[Dict]:
    rows = _read_rows(file_path)
    header_idx = _find_header_row(
        rows,
        ['Data do Neg', 'Tipo de Mov', 'Código de Neg', 'Codigo de Neg'],
    )
    header_row = rows[header_idx - 1] if header_idx > 0 else []
    col = _build_col_map(header_row)

    def ci(*names, default: int = -1) -> int:
        idx = _col_idx(col, *names)
        return idx if idx >= 0 else default

    i_date        = ci('Data do Negócio', 'Data Negócio', 'Data do Neg', 'Data Neg',        default=0)
    i_type        = ci('Tipo de Movimentação', 'Tipo Movimentação', 'Tipo Mov', 'Tipo', 'C/V', default=1)
    i_market      = ci('Mercado', 'Market',                                                  default=2)
    i_institution = ci('Instituição', 'Instituicao', 'Corretora', 'Intermediário',           default=4)
    i_product     = ci('Código de Negociação', 'Codigo de Negociacao', 'Codigo Negociacao',
                        'Ativo', 'Ticker', 'Papel', 'Código Ativo',                          default=5)
    i_qty         = ci('Quantidade', 'Qtde', 'Qtd',                                          default=6)
    i_price       = ci('Preço', 'Preco', 'Preço Unitário', 'Valor Unitário', 'Cotação',      default=7)
    i_value       = ci('Valor', 'Valor Total', 'Valor da Operação', 'Valor Operação',         default=8)

    transactions = []
    for row in rows[header_idx:]:
        if not row or len(row) < 4:
            continue

        def cell(idx):
            return str(row[idx]).strip() if idx < len(row) and row[idx] is not None else ''

        date        = cell(i_date)
        op_type     = cell(i_type)
        market      = cell(i_market)
        institution = cell(i_institution)
        raw_product = cell(i_product)

        if not raw_product or not re.search(r'\d{2}/\d{2}/\d{4}', date):
            continue

        product_norm = _search_norm(raw_product)
        if re.search(r'\b(termo|opcao|opção|futuros?|deriv|warrant|common stock|preferred stock)\b', product_norm):
            continue
        if re.search(r'\b(CRA|CRI|DEB|DEBENTURE|FBC|FBP|B[A-Z]{0,3}RUTO|TITULO|TÍTULO|LET|LFT|NTN|TESOURO|CDB)\b', raw_product, re.IGNORECASE):
            continue

        ticker = _normalize_ticker(raw_product)
        parts = re.split(r'\s*-\s*', raw_product)
        full_name = ' - '.join(parts[1:]).strip() or ticker

        type_lower = op_type.lower()
        is_buy  = 'compra' in type_lower or op_type == 'C'
        is_sell = 'venda'  in type_lower or op_type == 'V'
        if not is_buy and not is_sell:
            continue

        asset_cnpj  = _extract_cnpj(raw_product) or _extract_cnpj(full_name)
        broker_cnpj = _extract_cnpj(institution)

        transactions.append({
            'date':              date,
            'type':              op_type,
            'market':            market,
            'institution':       institution,
            'ticker':            ticker,
            'normalized_ticker': ticker,
            'full_name':         full_name,
            'quantity':          _parse_number(row[i_qty]   if i_qty   < len(row) else 0),
            'price':             _parse_number(row[i_price] if i_price < len(row) else 0),
            'value':             _parse_number(row[i_value] if i_value < len(row) else 0),
            'asset_cnpj':        asset_cnpj or None,
            'broker_cnpj':       broker_cnpj or None,
        })

    return transactions


# ── Movimentação ───────────────────────────────────────────────────────────────

def parse_movimentacao_sheet(file_path: Union[str, BinaryIO]) -> List[Dict]:
    rows = _read_rows(file_path)
    header_idx = _find_header_row(
        rows,
        ['Entrada/Saída', 'Entrada/Saida', 'Movimentação', 'Produto'],
    )
    header_row = rows[header_idx - 1] if header_idx > 0 else []
    col = _build_col_map(header_row)

    def ci(*names, default: int = -1) -> int:
        idx = _col_idx(col, *names)
        return idx if idx >= 0 else default

    i_cd          = ci('Entrada/Saída', 'Entrada/Saida', 'Crédito/Débito',
                        'Credito/Debito', 'Tipo Lançamento',                                   default=0)
    i_date        = ci('Data', 'Data do Lançamento', 'Data Lançamento',                        default=1)
    i_type        = ci('Movimentação', 'Movimentacao', 'Tipo', 'Descrição', 'Histórico',       default=2)
    i_product     = ci('Produto', 'Ativo', 'Descrição do Ativo', 'Papel',                      default=3)
    i_institution = ci('Instituição', 'Instituicao', 'Corretora', 'Intermediário',              default=4)
    i_qty         = ci('Quantidade', 'Qtde', 'Qtd',                                            default=5)
    i_unit_price  = ci('Preço Unitário', 'Preco Unitario', 'Valor Unitário', 'Preço',
                        'Cotação',                                                             default=6)
    i_value       = ci('Valor da Operação', 'Valor Operacao', 'Valor Total', 'Valor',          default=7)

    movements = []
    for row in rows[header_idx:]:
        if not row or len(row) < 4:
            continue

        def cell(idx):
            return str(row[idx]).strip() if idx < len(row) and row[idx] is not None else ''

        credit_debit = cell(i_cd)
        date         = cell(i_date)
        op_type      = cell(i_type)
        product      = cell(i_product)
        institution  = cell(i_institution)

        if not date or not product or not re.search(r'\d{2}/\d{2}/\d{4}', date):
            continue
        if re.match(r'^total', product, re.IGNORECASE):
            continue

        product_norm = _search_norm(product)
        type_norm = _search_norm(op_type)
        if re.search(r'\b(termo|opcao|opção|futuros?|deriv|warrant|common stock|preferred stock)\b', product_norm) or \
           re.search(r'\b(liquidacao\s*termo|liquidacao|liquida(c|ç)(ao|ã)o|termo|opcao|opção|futuros?|deriv|warrant)\b', type_norm):
            continue

        # Filtra ativos de renda fixa / instrumentos que não participam do cálculo de CMPA de ações/FII
        if re.search(r'\b(CRA|CRI|DEB|DEBENTURE|FBC|FBP|CRI[\s-]|CRA[\s-]|B[A-Z]{0,3}RUTO|TITULO|TÍTULO|LET|LFT|NTN|TESOURO|CDB)\b', product, re.IGNORECASE):
            continue

        ticker = _normalize_ticker(product)
        asset_cnpj  = _extract_cnpj(product)
        broker_cnpj = _extract_cnpj(institution)

        movements.append({
            'credit_debit':      credit_debit,
            'date':              date,
            'type':              op_type,
            'product':           product,
            'ticker':            ticker,
            'normalized_ticker': ticker,
            'institution':       institution,
            'quantity':          _parse_number(row[i_qty]        if i_qty        < len(row) else 0),
            'unit_price':        _parse_number(row[i_unit_price] if i_unit_price < len(row) else 0),
            'operation_value':   _parse_number(row[i_value]      if i_value      < len(row) else 0),
            'asset_cnpj':        asset_cnpj  or None,
            'broker_cnpj':       broker_cnpj or None,
        })

    return movements