"""
Calcula posições (CMPA), vendas, eventos corporativos e operações
a partir das listas de transações e movimentações B3.
"""

import re
import unicodedata
from datetime import datetime
from typing import List, Dict, Any


def _parse_date(date_str: str) -> int:
    if not date_str:
        return 0
    parts = date_str.strip().split('/')
    if len(parts) != 3:
        return 0
    d, m, y = parts
    try:
        return int(datetime(int(y), int(m), int(d), 12).timestamp())
    except Exception:
        return 0


def _round2(n: float) -> float:
    return round(n, 2)


def _norm(s: str) -> str:
    s = unicodedata.normalize('NFD', str(s or ''))
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return s.lower()


def _extract_ticker(product: str) -> str:
    return product.split(' - ')[0].strip().upper() if product else ''


def _extract_full_name(product: str) -> str:
    parts = product.split(' - ')
    return ' - '.join(parts[1:]).strip() or parts[0].strip()


def _detect_type(ticker: str, full_name: str = '') -> str:
    if not ticker:
        return 'Ação'
    fn = (full_name or '').upper()
    if any(k in fn for k in ('FUNDO DE INDICE', 'FUNDO DE ÍNDICE', 'FUNDO DE INVESTIMENTO EM INDICE',
                              'FUNDO DE INVESTIMENTO EM ÍNDICE', 'ISHARES', ' ETF ')):
        return 'ETF'
    if ticker.endswith('11') or ticker.endswith('12'):
        return 'FII'
    if re.match(r'^[A-Z]{4}3[2-9]$', ticker) or re.match(r'^[A-Z]{4}34$', ticker):
        return 'BDR'
    return 'Ação'


def _get_irpf_code(asset_type: str) -> dict:
    # Grupos e códigos conforme IRPF 2026 — Bens e Direitos
    mapping = {
        'FII': ('07', '03'),  # Cotas de FII negociadas em bolsa
        'ETF': ('07', '02'),  # Fundos de renda variável (ETF)
        'BDR': ('03', '01'),  # Ações (BDR negociado em bolsa)
    }
    grupo, codigo = mapping.get(asset_type, ('03', '01'))  # Ação: 03/01
    return {'grupo': grupo, 'codigo': codigo, 'code': f'{grupo}/{codigo}'}


def _classify_movement(m: Dict) -> Dict:
    raw = _norm(m['type'])
    if 'bonifica' in raw:
        return {'category': 'bonus', 'description': 'Bonificação'}
    if 'desdobr' in raw:
        return {'category': 'split', 'description': 'Desdobramento'}
    if 'agrupamento' in raw or 'grupamento' in raw:
        return {'category': 'merge', 'description': 'Agrupamento'}
    if re.search(r'leil(i|a)o|leilao', raw):
        return {'category': 'auction', 'description': 'Leilão de Frações'}
    if 'amortiz' in raw:
        return {'category': 'amortizacao', 'description': 'Amortização'}
    if re.search(r'cisa(o|ão)|spin.?off', raw):
        return {'category': 'cisao', 'description': 'Cisão'}
    if re.search(r'juros.*capital|jcp', raw):
        return {'category': 'jcp', 'description': 'JCP'}
    if 'dividend' in raw or 'dividendo' in raw:
        return {'category': 'dividendo', 'description': 'Dividendos'}
    if 'rendimento' in raw or 'remunera' in raw:
        ticker = m.get('normalized_ticker', '')
        cat = 'fiiIncome' if (ticker.endswith('11') or ticker.endswith('12')) else 'dividendo'
        return {'category': cat, 'description': 'Rendimento FII' if cat == 'fiiIncome' else 'Dividendos'}
    if 'custodi' in raw:
        return {'category': 'custodia', 'description': 'Custódia', 'suspicious': True}
    if 'transferen' in raw:
        return {'category': 'transferencia', 'description': 'Transferência', 'suspicious': True}
    if 'liquidac' in raw:
        return {'category': 'liquidacao', 'description': 'Liquidação', 'suspicious': True}
    if 'compra' in raw:
        return {'category': 'buy', 'description': 'Compra'}
    if 'venda' in raw:
        return {'category': 'sell', 'description': 'Venda'}
    return {'category': 'other', 'description': 'Outro'}


def calculate_positions(
    transactions: List[Dict],
    movements: List[Dict],
) -> Dict[str, Any]:
    events: List[Dict] = []
    operations: List[Dict] = []
    audit_log: List[Dict] = []
    validation_issues: List[Dict] = []

    has_transaction_data = len(transactions) > 0

    # Mapa de deduplicação: "tipo|ticker|qty" → contador
    nego_count: Dict[str, int] = {}

    def add_nego_key(kind: str, ticker: str, qty: float):
        key = f'{kind}|{ticker}|{round(qty)}'
        nego_count[key] = nego_count.get(key, 0) + 1

    def consume_nego_key(kind: str, ticker: str, qty: float) -> bool:
        key = f'{kind}|{ticker}|{round(qty)}'
        n = nego_count.get(key, 0)
        if n > 0:
            nego_count[key] = n - 1
            return True
        return False

    # ── Processa Negociação ────────────────────────────────────────────────────
    for t in transactions:
        tl = t['type'].lower().strip()
        is_buy  = tl == 'compra' or tl == 'c' or 'compra' in tl
        is_sell = tl == 'venda'  or tl == 'v' or 'venda'  in tl
        if not is_buy and not is_sell:
            continue
        kind = 'buy' if is_buy else 'sell'
        add_nego_key(kind, t['normalized_ticker'], t['quantity'])
        events.append({
            'ts':               _parse_date(t['date']),
            'date':             t['date'],
            'kind':             kind,
            'ticker':           t['normalized_ticker'],
            'full_name':        t.get('full_name') or t['ticker'],
            'quantity':         t['quantity'],
            'value':            t['value'],
            'institution':      t['institution'],
            'reference_ticker': t['ticker'],
            'asset_cnpj':       t.get('asset_cnpj'),
            'broker_cnpj':      t.get('broker_cnpj'),
        })

    # ── Processa Movimentação ──────────────────────────────────────────────────
    for m in movements:
        tl = _norm(m['type'])
        ticker = m.get('normalized_ticker') or _extract_ticker(m['product'])
        if not ticker:
            continue

        is_buy_mov  = tl == 'compra' or tl.startswith('compra')
        is_sell_mov = tl == 'venda'  or tl.startswith('venda')

        if is_buy_mov or is_sell_mov:
            kind = 'buy' if is_buy_mov else 'sell'
            if has_transaction_data:
                if not consume_nego_key(kind, ticker, m['quantity']):
                    audit_log.append({
                        'date':   m['date'], 'ticker': ticker,
                        'event':  f"{'Compra' if kind == 'buy' else 'Venda'} sem negociação correspondente",
                        'action': 'IGNORADO',
                        'reason': 'Movimentação contém operação que não está em Negociação.',
                        'details': f"Tipo: {m['type']} / Qtd {m['quantity']}",
                    })
                    validation_issues.append({
                        'level':   'warning',
                        'message': f"Movimentação {kind} para {ticker} em {m['date']} sem correspondência em Negociação.",
                        'ticker':  ticker, 'date': m['date'],
                    })
                operations.append({
                    'date': m['date'], 'ticker': ticker,
                    'full_name': _extract_full_name(m['product']),
                    'type': 'Movimentação Duplicada',
                    'quantity': m['quantity'], 'unit_price': m['unit_price'],
                    'value': m['operation_value'], 'institution': m['institution'],
                    'note': 'Compra/venda da Movimentação deduplicada com Negociação.',
                })
            else:
                events.append({
                    'ts': _parse_date(m['date']), 'date': m['date'],
                    'kind': kind, 'ticker': ticker,
                    'full_name': _extract_full_name(m['product']),
                    'quantity': m['quantity'], 'value': m['operation_value'],
                    'institution': m['institution'],
                    'asset_cnpj': m.get('asset_cnpj'), 'broker_cnpj': m.get('broker_cnpj'),
                })
                operations.append({
                    'date': m['date'], 'ticker': ticker,
                    'full_name': _extract_full_name(m['product']),
                    'type': 'Compra' if is_buy_mov else 'Venda',
                    'quantity': m['quantity'], 'unit_price': m['unit_price'],
                    'value': m['operation_value'], 'institution': m['institution'],
                })
            continue

        classified = _classify_movement(m)
        is_credit = 'credito' in _norm(m['credit_debit']) or 'crédito' in m['credit_debit'].lower()
        is_transfer_liq = classified['category'] in ('transferencia', 'liquidacao')
        is_auction = classified['category'] == 'auction'
        is_valid_credit = is_credit and m['quantity'] > 0 and m['unit_price'] > 0 and (is_transfer_liq or is_auction)

        if is_valid_credit:
            if has_transaction_data and is_transfer_liq:
                operations.append({
                    'date': m['date'], 'ticker': ticker,
                    'full_name': _extract_full_name(m['product']),
                    'type': 'Movimentação Duplicada',
                    'quantity': m['quantity'], 'unit_price': m['unit_price'],
                    'value': m['operation_value'], 'institution': m['institution'],
                    'note': 'Transferência/Liquidação ignorada — já em Negociação.',
                })
                continue
            if has_transaction_data and consume_nego_key('buy', ticker, m['quantity']):
                operations.append({
                    'date': m['date'], 'ticker': ticker,
                    'full_name': _extract_full_name(m['product']),
                    'type': 'Movimentação Duplicada',
                    'quantity': m['quantity'], 'unit_price': m['unit_price'],
                    'value': m['operation_value'], 'institution': m['institution'],
                })
                continue
            events.append({
                'ts': _parse_date(m['date']), 'date': m['date'],
                'kind': 'buy', 'ticker': ticker,
                'full_name': _extract_full_name(m['product']),
                'quantity': m['quantity'], 'value': m['operation_value'],
                'institution': m['institution'],
                'asset_cnpj': m.get('asset_cnpj'), 'broker_cnpj': m.get('broker_cnpj'),
            })
            operations.append({
                'date': m['date'], 'ticker': ticker,
                'full_name': _extract_full_name(m['product']),
                'type': 'Compra', 'quantity': m['quantity'],
                'unit_price': m['unit_price'], 'value': m['operation_value'],
                'institution': m['institution'],
            })
            continue

        if classified.get('suspicious'):
            audit_log.append({
                'date': m['date'], 'ticker': ticker,
                'event': classified['description'], 'action': 'AVALIADO',
                'reason': 'Movimentação suspeita — não altera CMPA.',
                'details': f"Tipo: {m['type']} / Qtd {m['quantity']}",
            })
            validation_issues.append({
                'level': 'warning',
                'message': f"Evento suspeito de {classified['description']} em {m['date']} para {ticker}.",
                'ticker': ticker, 'date': m['date'],
            })
            type_map = {'Transferência': 'Transferência', 'Custódia': 'Custódia', 'Liquidação': 'Liquidação'}
            operations.append({
                'date': m['date'], 'ticker': ticker,
                'full_name': _extract_full_name(m['product']),
                'type': type_map.get(classified['description'], 'Evento Suspeito'),
                'quantity': m['quantity'], 'unit_price': m['unit_price'],
                'value': m['operation_value'], 'institution': m['institution'],
            })
            continue

        if classified['category'] == 'bonus':
            events.append({
                'ts': _parse_date(m['date']), 'date': m['date'],
                'kind': 'bonus', 'ticker': ticker,
                'quantity': m['quantity'], 'cost_per_share': m['unit_price'] or 0,
            })
        elif classified['category'] == 'split':
            delta = m['quantity'] if is_credit else -m['quantity']
            events.append({'ts': _parse_date(m['date']), 'date': m['date'], 'kind': 'split', 'ticker': ticker, 'quantity_delta': delta})
        elif classified['category'] == 'merge':
            delta = m['quantity'] if is_credit else -m['quantity']
            events.append({'ts': _parse_date(m['date']), 'date': m['date'], 'kind': 'merge', 'ticker': ticker, 'quantity_delta': delta})
        elif classified['category'] == 'auction':
            delta = m['quantity'] if is_credit else -m['quantity']
            events.append({'ts': _parse_date(m['date']), 'date': m['date'], 'kind': 'auction', 'ticker': ticker, 'quantity_delta': delta, 'value': m['operation_value']})
        elif classified['category'] == 'amortizacao':
            events.append({
                'ts': _parse_date(m['date']), 'date': m['date'],
                'kind': 'amortizacao', 'ticker': ticker,
                'value': m['operation_value'],
            })
        elif classified['category'] == 'cisao':
            delta = m['quantity'] if is_credit else -m['quantity']
            events.append({
                'ts': _parse_date(m['date']), 'date': m['date'],
                'kind': 'cisao', 'ticker': ticker,
                'quantity_delta': delta, 'value': m['operation_value'],
            })

    # ── Ordena e processa timeline ─────────────────────────────────────────────
    # No mesmo dia: compras/vendas (priority 0) antes de eventos corporativos (priority 1)
    _CORP_KINDS = {'bonus', 'split', 'merge', 'auction', 'amortizacao', 'cisao'}
    events.sort(key=lambda e: (e['ts'], 1 if e['kind'] in _CORP_KINDS else 0))

    positions: Dict[str, Dict] = {}
    sales: List[Dict] = []
    corporate_events: List[Dict] = []

    def get_or_create(ticker, full_name, date, ref_ticker=None, asset_cnpj=None, broker_cnpj=None):
        if ticker not in positions:
            positions[ticker] = {
                'ticker': ticker, 'reference_ticker': ref_ticker,
                'full_name': full_name or ticker,
                'quantity': 0.0, 'total_cost': 0.0, 'average_cost': 0.0,
                'institution': '', 'asset_cnpj': asset_cnpj, 'broker_cnpj': broker_cnpj,
                'first_purchase_date': date, 'last_purchase_date': date,
                'first_purchase_quantity': 0.0,
                'buy_events': [],
                'bonus_events': [],
            }
        pos = positions[ticker]
        if asset_cnpj and not pos['asset_cnpj']:
            pos['asset_cnpj'] = asset_cnpj
        if broker_cnpj and not pos['broker_cnpj']:
            pos['broker_cnpj'] = broker_cnpj
        return pos

    for ev in events:
        ticker = ev['ticker']

        if ev['kind'] == 'buy':
            pos = get_or_create(ticker, ev.get('full_name', ticker), ev['date'],
                                ev.get('reference_ticker'), ev.get('asset_cnpj'), ev.get('broker_cnpj'))
            new_qty  = pos['quantity'] + ev['quantity']
            new_cost = pos['total_cost'] + ev['value']
            pos['quantity']     = new_qty
            pos['total_cost']   = new_cost
            pos['average_cost'] = new_cost / new_qty if new_qty > 0 else 0.0
            if pos['first_purchase_quantity'] == 0 and ev['quantity'] > 0:
                pos['first_purchase_quantity'] = ev['quantity']
            pos['institution']        = ev.get('institution') or pos['institution']
            pos['last_purchase_date'] = ev['date']
            if ev.get('full_name') and ev.get('full_name') != ticker:
                pos['full_name'] = ev['full_name']
            pos['buy_events'].append({
                'date': ev['date'],
                'quantity': ev['quantity'],
                'total_cost': _round2(ev['value']),
            })
            operations.append({
                'date': ev['date'], 'ticker': ticker, 'full_name': pos['full_name'],
                'type': 'Compra', 'quantity': ev['quantity'],
                'unit_price': _round2(ev['value'] / ev['quantity']) if ev['quantity'] > 0 else 0,
                'value': ev['value'], 'institution': ev.get('institution', ''),
            })

        elif ev['kind'] == 'sell':
            pos = get_or_create(ticker, ticker, ev['date'])
            sold_qty = min(ev['quantity'], pos['quantity'])
            if sold_qty <= 0:
                continue
            if sold_qty < ev['quantity']:
                validation_issues.append({
                    'level': 'warning',
                    'message': (
                        f"Venda de {ev['quantity']} {ticker} em {ev['date']}, "
                        f"mas posição tem apenas {pos['quantity']:.2f}. "
                        f"Verifique se o arquivo de Movimentação cobre todo o período histórico "
                        f"(possível evento corporativo ausente, ex: split ou bonificação)."
                    ),
                    'ticker': ticker, 'date': ev['date'],
                })
            # Prorratea o valor de venda se vendemos menos do que o registrado
            sale_value = _round2(ev['value'] * (sold_qty / ev['quantity'])) if ev['quantity'] > 0 else ev['value']
            cmpa       = pos['average_cost']
            cost_basis = _round2(cmpa * sold_qty)
            gain       = _round2(sale_value - cost_basis)
            sales.append({
                'date': ev['date'], 'ticker': ticker,
                'quantity': sold_qty, 'sale_price': sale_value,
                'cmpa_at_sale': _round2(cmpa), 'cost_basis': cost_basis, 'gain': gain,
            })
            operations.append({
                'date': ev['date'], 'ticker': ticker, 'full_name': pos['full_name'],
                'type': 'Venda', 'quantity': sold_qty,
                'unit_price': _round2(sale_value / sold_qty) if sold_qty > 0 else 0,
                'value': sale_value, 'institution': pos['institution'],
                'cmpa_at_sale': _round2(cmpa), 'gain': gain,
            })
            pos['quantity']   -= sold_qty
            pos['total_cost']  = _round2(pos['average_cost'] * pos['quantity'])

        elif ev['kind'] == 'bonus':
            pos = get_or_create(ticker, ticker, ev['date'])
            bonus_cost = _round2(ev['quantity'] * ev.get('cost_per_share', 0))
            pos['quantity']     += ev['quantity']
            pos['total_cost']   = _round2(pos['total_cost'] + bonus_cost)
            pos['average_cost']  = pos['total_cost'] / pos['quantity'] if pos['quantity'] > 0 else 0.0
            pos['bonus_events'].append({
                'date': ev['date'],
                'quantity': ev['quantity'],
                'unit_price': ev.get('cost_per_share', 0),
                'total_cost': bonus_cost,
            })
            corporate_events.append({
                'date': ev['date'], 'type': 'Bonificação', 'ticker': ticker,
                'details': f"Bonificação: +{ev['quantity']} cota(s) — CMPA recalculado para R${pos['average_cost']:.2f}",
                'quantity_change': ev['quantity'],
            })
            operations.append({
                'date': ev['date'], 'ticker': ticker, 'full_name': pos['full_name'],
                'type': 'Bonificação', 'quantity': ev['quantity'],
                'unit_price': ev.get('cost_per_share', 0),
                'value': bonus_cost,
                'institution': pos['institution'],
            })

        elif ev['kind'] in ('split', 'merge'):
            pos = get_or_create(ticker, ticker, ev['date'])
            pos['quantity']     += ev['quantity_delta']
            pos['average_cost']  = pos['total_cost'] / pos['quantity'] if pos['quantity'] > 0 else 0.0
            ev_type = 'Desdobramento' if ev['kind'] == 'split' else 'Agrupamento'
            delta   = ev['quantity_delta']
            corporate_events.append({
                'date': ev['date'], 'type': ev_type, 'ticker': ticker,
                'details': f"{ev_type}: {'+' if delta > 0 else ''}{delta} cota(s)",
                'quantity_change': delta,
            })
            operations.append({
                'date': ev['date'], 'ticker': ticker, 'full_name': pos['full_name'],
                'type': ev_type, 'quantity': delta,
                'unit_price': 0, 'value': 0, 'institution': pos['institution'],
            })

        elif ev['kind'] == 'auction':
            pos = get_or_create(ticker, ticker, ev['date'])
            delta = ev.get('quantity_delta', 0)
            if delta < 0:
                qty        = abs(delta)
                cost_basis = _round2(pos['average_cost'] * qty)
                gain       = _round2((ev.get('value') or 0) - cost_basis)
                sales.append({
                    'date': ev['date'], 'ticker': ticker,
                    'quantity': qty, 'sale_price': ev.get('value', 0),
                    'cmpa_at_sale': _round2(pos['average_cost']),
                    'cost_basis': cost_basis, 'gain': gain,
                })
                pos['quantity']  -= qty
                pos['total_cost'] = _round2(pos['average_cost'] * pos['quantity'])
            else:
                pos['quantity']     += delta
                pos['average_cost']  = pos['total_cost'] / pos['quantity'] if pos['quantity'] > 0 else 0.0
            corporate_events.append({
                'date': ev['date'], 'type': 'Leilão de Frações', 'ticker': ticker,
                'details': f"Leilão: {'+' if delta >= 0 else ''}{delta} cota(s)",
                'quantity_change': delta,
            })

        elif ev['kind'] == 'amortizacao':
            pos = get_or_create(ticker, ticker, ev['date'])
            amort_val = ev.get('value', 0)
            pos['total_cost']   = _round2(max(pos['total_cost'] - amort_val, 0))
            pos['average_cost']  = pos['total_cost'] / pos['quantity'] if pos['quantity'] > 0 else 0.0
            corporate_events.append({
                'date': ev['date'], 'type': 'Amortização', 'ticker': ticker,
                'details': f"Amortização: -R${amort_val:.2f} do custo total — CMPA recalculado para R${pos['average_cost']:.2f}",
                'quantity_change': 0,
            })
            operations.append({
                'date': ev['date'], 'ticker': ticker, 'full_name': pos['full_name'],
                'type': 'Amortização', 'quantity': 0,
                'unit_price': 0, 'value': amort_val, 'institution': pos['institution'],
            })

        elif ev['kind'] == 'cisao':
            pos = get_or_create(ticker, ticker, ev['date'])
            delta     = ev.get('quantity_delta', 0)
            cisao_val = ev.get('value', 0)
            if delta != 0:
                pos['quantity']   = max(pos['quantity'] + delta, 0)
            pos['total_cost']  = _round2(max(pos['total_cost'] - cisao_val, 0))
            pos['average_cost'] = pos['total_cost'] / pos['quantity'] if pos['quantity'] > 0 else 0.0
            corporate_events.append({
                'date': ev['date'], 'type': 'Cisão', 'ticker': ticker,
                'details': f"Cisão: {'+' if delta >= 0 else ''}{delta} cota(s), -R${cisao_val:.2f} do custo",
                'quantity_change': delta,
            })
            operations.append({
                'date': ev['date'], 'ticker': ticker, 'full_name': pos['full_name'],
                'type': 'Cisão', 'quantity': delta,
                'unit_price': 0, 'value': cisao_val, 'institution': pos['institution'],
            })

    # ── Monta ativos finais ────────────────────────────────────────────────────
    assets = []
    for pos in positions.values():
        if pos['quantity'] < 0.0001:
            continue
        asset_type = _detect_type(pos['ticker'], pos.get('full_name', ''))
        irpf       = _get_irpf_code(asset_type)
        total_cost = _round2(pos['total_cost'])
        assets.append({
            'ticker':                  pos['ticker'],
            'reference_ticker':        pos.get('reference_ticker'),
            'full_name':               pos['full_name'],
            'quantity':                _round2(pos['quantity']),
            'average_cost':            _round2(pos['average_cost']),
            'total_cost':              total_cost,
            'dividends':               0.0,
            'jcp':                     0.0,
            'fii_income':              0.0,
            'institution':             pos['institution'],
            'asset_cnpj':              pos.get('asset_cnpj'),
            'broker_cnpj':             pos.get('broker_cnpj'),
            'type':                    asset_type,
            'irpf_grupo':              irpf['grupo'],
            'irpf_codigo':             irpf['codigo'],
            'irpf_code':               irpf['code'],
            'first_purchase_date':     pos['first_purchase_date'],
            'first_purchase_quantity': _round2(pos['first_purchase_quantity']),
            'last_purchase_date':      pos['last_purchase_date'],
            'year_end_total':          total_cost,
            'buy_events':              pos.get('buy_events', []),
            'bonus_events':            pos.get('bonus_events', []),
        })

    assets.sort(key=lambda a: a['ticker'])
    sales.sort(key=lambda s: _parse_date(s['date']))

    return {
        'assets':            assets,
        'sales':             sales,
        'corporate_events':  corporate_events,
        'operations':        operations,
        'audit_log':         audit_log,
        'validation_issues': validation_issues,
    }
