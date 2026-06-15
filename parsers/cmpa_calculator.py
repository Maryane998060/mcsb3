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
    if 'desdobr' in raw or 'desdobro' in raw:
        return {'category': 'split', 'description': 'Desdobramento'}
    if 'agrupamento' in raw or 'grupamento' in raw:
        return {'category': 'merge', 'description': 'Agrupamento'}
    if re.search(r'leil(i|a)o|leilao', raw):
        return {'category': 'auction', 'description': 'Leilão de Frações'}
    if 'fracao' in raw or 'fracao_em_ativos' in raw or re.search(r'fra(c|ç)(ao|ã)o', raw):
        return {'category': 'fraction', 'description': 'Fração em Ativos'}
    if 'amortiz' in raw:
        return {'category': 'amortizacao', 'description': 'Amortização'}
    if re.search(r'cisa(o|ao)|spin.?off', raw):
        return {'category': 'cisao', 'description': 'Cisão'}
    if re.search(r'restituic(a|ã)o.*capital|restituicao', raw):
        return {'category': 'restituicao_capital', 'description': 'Restituição de Capital'}
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
    year: int = 0,
    ajustes_irpf: Dict[str, Dict] = None,
) -> Dict[str, Any]:
    """
    ajustes_irpf: dict opcional, keyed por ticker, com:
        {
          'custo_declarado': float,    # custo total que entra como base para cálculo de 2025
          'custo_irpf_anterior': float, # custo exibido na coluna 31/12/ano-anterior (pode ser 0 = omitido)
          'qty_declarada':  float,     # quantidade declarada no IRPF anterior (opcional)
          'bonus_fiscal': {            # valor fiscal de bonificações sem custo na B3
              'DD/MM/YYYY': float      # data → valor unitário fiscal
          }
        }
    """
    if ajustes_irpf is None:
        ajustes_irpf = {}
    events: List[Dict] = []
    operations: List[Dict] = []
    audit_log: List[Dict] = []
    validation_issues: List[Dict] = []

    has_transaction_data = len(transactions) > 0

    # ── Processa Negociação ────────────────────────────────────────────────────
    for t in transactions:
        tl = t['type'].lower().strip()
        is_buy  = tl == 'compra' or tl == 'c' or 'compra' in tl
        is_sell = tl == 'venda'  or tl == 'v' or 'venda'  in tl
        if not is_buy and not is_sell:
            continue
        kind = 'buy' if is_buy else 'sell'
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
    # REGRAS FUNDAMENTAIS (conforme B3):
    # 1. Transferência entre corretoras → NUNCA altera custo/quantidade. Apenas registro.
    # 2. Compra/Venda na movimentação → só usada quando NÃO há planilha de Negociação.
    #    Quando há Negociação, a movimentação de compra/venda é duplicata — ignorar.
    # 3. Eventos corporativos (bonificação, desdobro, grupamento, etc.) → sempre processam.
    # 4. Restituição de Capital → subtrai do custo total.
    # 5. Proventos (dividendo, JCP, rendimento) → apenas informativo, não altera CMPA.

    for m in movements:
        tl = _norm(m['type'])
        ticker = m.get('normalized_ticker') or _extract_ticker(m['product'])
        if not ticker:
            continue

        classified = _classify_movement(m)
        cat = classified['category']

        # ── Transferência e Custódia: SEMPRE ignorar para cálculo de posição ──
        # São movimentos entre corretoras ou custódia — não representam compra/venda nova.
        if cat in ('transferencia', 'custodia', 'liquidacao'):
            # Não adiciona ao audit_log — transferências são normais, não são erros
            operations.append({
                'date': m['date'], 'ticker': ticker,
                'full_name': _extract_full_name(m['product']),
                'type': classified['description'],
                'quantity': m['quantity'], 'unit_price': m['unit_price'],
                'value': m['operation_value'], 'institution': m['institution'],
                'note': 'Transferência entre corretoras — não altera CMPA.',
            })
            continue

        # ── Compra/Venda na movimentação ──
        is_buy_mov  = tl == 'compra' or tl.startswith('compra') or cat == 'buy'
        is_sell_mov = tl == 'venda'  or tl.startswith('venda')  or cat == 'sell'

        if is_buy_mov or is_sell_mov:
            kind = 'buy' if is_buy_mov else 'sell'
            if has_transaction_data:
                # Com planilha de Negociação: movimentação de compra/venda é sempre duplicata
                operations.append({
                    'date': m['date'], 'ticker': ticker,
                    'full_name': _extract_full_name(m['product']),
                    'type': 'Movimentação Duplicada',
                    'quantity': m['quantity'], 'unit_price': m['unit_price'],
                    'value': m['operation_value'], 'institution': m['institution'],
                    'note': 'Duplicata da Negociação — ignorado no cálculo.',
                })
            else:
                # Sem planilha de Negociação: usa movimentação como fonte primária
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

        # ── Proventos: dividendos, JCP, rendimentos → só informativo ──
        if cat in ('dividendo', 'jcp', 'fiiIncome'):
            # Registrado apenas para exibição — não altera CMPA
            continue

        # Calcula crédito/débito para eventos corporativos que precisam saber a direção
        is_credit = 'credito' in _norm(m['credit_debit']) or 'crédito' in m.get('credit_debit', '').lower()
        is_debit  = 'debito'  in _norm(m['credit_debit']) or 'débito'  in m.get('credit_debit', '').lower()

        if classified['category'] == 'bonus':
            events.append({
                'ts': _parse_date(m['date']), 'date': m['date'],
                'kind': 'bonus', 'ticker': ticker,
                'quantity': m['quantity'],
                'cost_per_share': m['unit_price'] or 0,
                'operation_value': m['operation_value'] or 0,
            })
        elif classified['category'] == 'split':
            delta = m['quantity'] if is_credit else -m['quantity']
            events.append({'ts': _parse_date(m['date']), 'date': m['date'], 'kind': 'split', 'ticker': ticker, 'quantity_delta': delta})
        elif classified['category'] == 'merge':
            delta = m['quantity'] if is_credit else -m['quantity']
            # Grupamento/Agrupamento: crédito de fração pequena = fração gerada indo a leilão
            # Não altera a posição — a fração é processada pelo Leilão de Fração (auction)
            # Apenas grupamentos inteiros (sem fração, débito) ajustam a quantidade
            if abs(delta) < 1.0:
                # Fração de grupamento — apenas registra, não altera posição
                operations.append({
                    'date': m['date'], 'ticker': ticker,
                    'full_name': _extract_full_name(m['product']),
                    'type': 'Grupamento (fração)', 'quantity': delta,
                    'unit_price': 0, 'value': 0, 'institution': m['institution'],
                    'note': 'Fração de grupamento enviada a leilão — não altera CMPA.',
                })
            else:
                events.append({'ts': _parse_date(m['date']), 'date': m['date'], 'kind': 'merge', 'ticker': ticker, 'quantity_delta': delta})
        elif classified['category'] == 'auction':
            # Leilão de Fração: o Crédito é a RECEITA da venda da fração (financeiro)
            # A fração já foi enviada pelo evento de Grupamento/Fração
            # Registramos com delta negativo para indicar saída da fração
            frac_qty = m['quantity']
            frac_val = m['operation_value']
            events.append({
                'ts': _parse_date(m['date']), 'date': m['date'],
                'kind': 'auction', 'ticker': ticker,
                'quantity_delta': -frac_qty,   # fração sai da posição
                'value': frac_val,             # receita recebida
            })
        elif classified['category'] == 'amortizacao':
            events.append({
                'ts': _parse_date(m['date']), 'date': m['date'],
                'kind': 'amortizacao', 'ticker': ticker,
                'value': m['operation_value'],
            })
        elif classified['category'] == 'cisao':
            delta = m['quantity'] if is_credit else -m['quantity']
            cisao_val = m['operation_value'] or 0
            # Cisão com valor zero e crédito = migração de custódia ou reorganização societária
            # sem efeito financeiro — tratar como Transferência (ignorar posição)
            if cisao_val == 0 and is_credit:
                audit_log.append({
                    'date': m['date'], 'ticker': ticker,
                    'event': 'Cisão sem valor', 'action': 'IGNORADO',
                    'reason': 'Cisão com valor zero tratada como migração de custódia.',
                    'details': f"Tipo: {m['type']} / Qtd {m['quantity']}",
                })
                operations.append({
                    'date': m['date'], 'ticker': ticker,
                    'full_name': _extract_full_name(m['product']),
                    'type': 'Cisão (ignorada)',
                    'quantity': m['quantity'], 'unit_price': 0,
                    'value': 0, 'institution': m['institution'],
                    'note': 'Cisão sem valor — migração de custódia, não altera CMPA.',
                })
            else:
                events.append({
                    'ts': _parse_date(m['date']), 'date': m['date'],
                    'kind': 'cisao', 'ticker': ticker,
                    'quantity_delta': delta, 'value': cisao_val,
                })

        elif classified['category'] == 'restituicao_capital':
            # Restituição de Capital: subtrai o valor recebido do custo total acumulado
            # Conforme regra: o valor financeiro deve ser subtraído do Custo Total Acumulado
            if m['operation_value'] > 0:
                events.append({
                    'ts': _parse_date(m['date']), 'date': m['date'],
                    'kind': 'restituicao_capital', 'ticker': ticker,
                    'value': m['operation_value'],
                    'unit_price': m['unit_price'],
                    'quantity': m['quantity'],
                })

        elif classified['category'] == 'fraction':
            # Fração em Ativos: crédito de frações de ações após desdobramento/grupamento
            # Se tem valor, soma ao custo (compra de fração). Se não tem, só ajusta quantidade.
            delta = m['quantity'] if is_credit else -m['quantity']
            frac_value = m['operation_value'] if is_credit else 0.0
            events.append({
                'ts': _parse_date(m['date']), 'date': m['date'],
                'kind': 'fraction', 'ticker': ticker,
                'quantity_delta': delta, 'value': frac_value,
            })

    # ── Ordena e processa timeline ─────────────────────────────────────────────
    # No mesmo dia: compras/vendas (priority 0) antes de eventos corporativos (priority 1)
    _CORP_KINDS = {'bonus', 'split', 'merge', 'auction', 'amortizacao', 'cisao',
                   'restituicao_capital', 'fraction'}
    events.sort(key=lambda e: (e['ts'], 1 if e['kind'] in _CORP_KINDS else 0))

    # Timestamp de virada do ano — para injetar custo declarado no IRPF anterior
    _ts_year_start = 0
    _irpf_injected = set()  # tickers já injetados
    if year:
        try:
            _ts_year_start = int(datetime(year, 1, 1, 0, 0).timestamp())
        except Exception:
            _ts_year_start = 0

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
                'corporate_events_history': [],
            }
        pos = positions[ticker]
        if asset_cnpj and not pos['asset_cnpj']:
            pos['asset_cnpj'] = asset_cnpj
        if broker_cnpj and not pos['broker_cnpj']:
            pos['broker_cnpj'] = broker_cnpj
        return pos

    for ev in events:
        ticker = ev['ticker']

        # ── Injeta custo declarado no IRPF anterior ao entrar no ano selecionado ──
        # Só faz isso uma vez por ticker, na primeira vez que um evento de 2025 aparece
        if (_ts_year_start > 0
                and ev['ts'] >= _ts_year_start
                and ticker not in _irpf_injected
                and ticker in ajustes_irpf
                and 'custo_declarado' in ajustes_irpf[ticker]):
            _irpf_injected.add(ticker)
            ajuste = ajustes_irpf[ticker]
            custo_decl = _round2(float(ajuste['custo_declarado']))
            qty_decl   = ajuste.get('qty_declarada')
            if ticker in positions:
                pos_inj = positions[ticker]
                pos_inj['total_cost']   = custo_decl
                if qty_decl is not None:
                    pos_inj['quantity'] = _round2(float(qty_decl))
                pos_inj['average_cost'] = (
                    pos_inj['total_cost'] / pos_inj['quantity']
                    if pos_inj['quantity'] > 0 else 0.0
                )

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
            # Prorratea valor de venda se vendemos menos do que o registrado
            sale_value = _round2(ev['value'] * (sold_qty / ev['quantity'])) if ev['quantity'] > 0 else ev['value']
            cmpa        = pos['average_cost']
            old_qty     = pos['quantity']
            old_total   = pos['total_cost']
            cost_basis  = _round2(cmpa * sold_qty)
            gain        = _round2(sale_value - cost_basis)
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
            # Redução proporcional do custo total — CMPA não muda após venda parcial.
            # Se a posição zera, custo também zera completamente.
            pos['quantity']   -= sold_qty
            if pos['quantity'] <= 0.0001:
                pos['quantity']   = 0.0
                pos['total_cost'] = 0.0
                pos['average_cost'] = 0.0
            else:
                pos['total_cost'] = _round2(old_total * pos['quantity'] / old_qty) if old_qty > 0 else 0.0

        elif ev['kind'] == 'bonus':
            pos = get_or_create(ticker, ticker, ev['date'])
            qty = ev['quantity']
            # Prioridade: 1) valor fiscal informado via ajuste_irpf, 2) valor da operação, 3) preço unitário
            ajuste_ticker = ajustes_irpf.get(ticker, {})
            bonus_fiscal_map = ajuste_ticker.get('bonus_fiscal', {})
            valor_fiscal_unit = bonus_fiscal_map.get(ev['date'], 0)

            # Se há qty_declarada no ajuste e a bonificação cria o ativo do zero,
            # usa a quantidade declarada (corrige arredondamentos da B3)
            qty_decl = ajuste_ticker.get('qty_declarada')
            if qty_decl is not None and pos['quantity'] == 0.0:
                qty = _round2(float(qty_decl))

            op_val     = ev.get('operation_value') or 0
            unit_price = ev.get('cost_per_share')  or 0

            if valor_fiscal_unit > 0:
                bonus_cost    = _round2(qty * valor_fiscal_unit)
                unit_for_hist = valor_fiscal_unit
            elif op_val > 0:
                bonus_cost    = _round2(op_val)
                unit_for_hist = _round2(op_val / qty) if qty > 0 else unit_price
            elif unit_price > 0:
                bonus_cost    = _round2(qty * unit_price)
                unit_for_hist = unit_price
            else:
                bonus_cost    = 0.0
                unit_for_hist = 0.0
                validation_issues.append({
                    'level':   'warning',
                    'message': (
                        f"Bonificação de {qty} {ticker} em {ev['date']}: custo não informado pela B3. "
                        f"Informe o valor fiscal unitário na seção 'Ajustes' para que o CMPA fique correto."
                    ),
                    'ticker': ticker, 'date': ev['date'],
                })
            pos['quantity']    += qty
            pos['total_cost']   = _round2(pos['total_cost'] + bonus_cost)
            pos['average_cost'] = pos['total_cost'] / pos['quantity'] if pos['quantity'] > 0 else 0.0
            pos['bonus_events'].append({
                'date': ev['date'],
                'quantity': qty,
                'unit_price': unit_for_hist,
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
            delta = ev['quantity_delta']
            # Grupamento/Desdobro de frações pequenas (< 1 ação) = geração de fração
            # que vai a leilão — não altera a posição principal, apenas registra.
            if abs(delta) < 1.0:
                ev_type = 'Desdobramento (fração)' if ev['kind'] == 'split' else 'Grupamento (fração)'
                corporate_events.append({
                    'date': ev['date'], 'type': ev_type, 'ticker': ticker,
                    'details': f"{ev_type}: fração de {delta:+.4f} ação(ões) gerada para leilão",
                    'quantity_change': 0,
                })
            else:
                pos['quantity']    += delta
                pos['average_cost'] = pos['total_cost'] / pos['quantity'] if pos['quantity'] > 0 else 0.0
                ev_type = 'Desdobramento' if ev['kind'] == 'split' else 'Agrupamento'
                corporate_events.append({
                    'date': ev['date'], 'type': ev_type, 'ticker': ticker,
                    'details': f"{ev_type}: {delta:+} ação(ões) — CMPA recalculado para R${pos['average_cost']:.2f}",
                    'quantity_change': delta,
                })
            operations.append({
                'date': ev['date'], 'ticker': ticker, 'full_name': pos['full_name'],
                'type': 'Desdobramento' if ev['kind'] == 'split' else 'Agrupamento',
                'quantity': delta, 'unit_price': 0, 'value': 0, 'institution': pos['institution'],
            })

        elif ev['kind'] == 'auction':
            pos = get_or_create(ticker, ticker, ev['date'])
            frac_val = ev.get('value') or 0
            frac_qty = abs(ev.get('quantity_delta', 0))
            # Leilão de Fração: a fração é residual gerada por grupamento/desdobro.
            # Ela NÃO faz parte das ações inteiras do investidor.
            # Apenas remove se a quantidade atual excede um número inteiro
            # (ou seja, se a fração foi incorporada erroneamente à posição).
            qty_inteira = round(pos['quantity'])  # quantidade inteira esperada
            excesso = pos['quantity'] - qty_inteira
            if excesso > 0.001 and abs(excesso - frac_qty) < 0.01:
                # A fração está sobrando na posição — remover
                pos['quantity']   = _round2(qty_inteira)
                pos['total_cost'] = _round2(pos['average_cost'] * pos['quantity'])
            # Caso contrário: não altera posição (fração era externa)
            corporate_events.append({
                'date': ev['date'], 'type': 'Leilão de Frações', 'ticker': ticker,
                'details': f"Leilão de fração: receita R${frac_val:.2f} (tributação exclusiva)",
                'quantity_change': 0,
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
            # Cisão com Crédito e sem valor = transferência de posição entre empresas
            # (ex: Itaú/Itan). Cria ou ajusta a posição sem alterar custo se valor=0.
            if delta != 0:
                pos['quantity'] = max(pos['quantity'] + delta, 0)
            if cisao_val > 0:
                pos['total_cost']  = _round2(max(pos['total_cost'] - cisao_val, 0))
            pos['average_cost'] = pos['total_cost'] / pos['quantity'] if pos['quantity'] > 0 else 0.0
            corporate_events.append({
                'date': ev['date'], 'type': 'Cisão', 'ticker': ticker,
                'details': f"Cisão: {'+' if delta >= 0 else ''}{delta} cota(s){f', -{cisao_val:.2f} do custo' if cisao_val else ''}",
                'quantity_change': delta,
            })
            operations.append({
                'date': ev['date'], 'ticker': ticker, 'full_name': pos['full_name'],
                'type': 'Cisão', 'quantity': delta,
                'unit_price': 0, 'value': cisao_val, 'institution': pos['institution'],
            })

        elif ev['kind'] == 'restituicao_capital':
            pos = get_or_create(ticker, ticker, ev['date'])
            rest_val  = ev.get('value', 0)
            old_cost  = pos['total_cost']
            # Subtrai o valor recebido do custo total acumulado (não altera quantidade)
            pos['total_cost']   = _round2(max(old_cost - rest_val, 0))
            pos['average_cost'] = pos['total_cost'] / pos['quantity'] if pos['quantity'] > 0 else 0.0
            pos['corporate_events_history'].append({
                'type':  'RESTITUICAO_CAPITAL',
                'date':  ev['date'],
                'value': rest_val,
            })
            corporate_events.append({
                'date':            ev['date'],
                'type':            'Restituição de Capital',
                'ticker':          ticker,
                'details':         (
                    f"Restituição: -{_round2(rest_val):.2f} do custo total "
                    f"(era R${old_cost:.2f} → R${pos['total_cost']:.2f}) — "
                    f"CMPA recalculado para R${pos['average_cost']:.2f}"
                ),
                'quantity_change': 0,
            })
            operations.append({
                'date':        ev['date'],
                'ticker':      ticker,
                'full_name':   pos['full_name'],
                'type':        'Restituição de Capital',
                'quantity':    ev.get('quantity', 0),
                'unit_price':  ev.get('unit_price', 0),
                'value':       rest_val,
                'institution': pos['institution'],
                'note':        f"Redução de custo: -{rest_val:.2f}",
            })

        elif ev['kind'] == 'fraction':
            pos = get_or_create(ticker, ticker, ev['date'])
            delta    = ev.get('quantity_delta', 0)
            frac_val = ev.get('value', 0)
            # Fração em Ativos: fragmento residual de grupamento/desdobro.
            # Só altera posição se há valor financeiro real (compra de fração paga).
            # Débito sem valor = fração enviada a leilão → não remove da posição principal.
            if frac_val > 0 and delta > 0:
                pos['quantity']   = max(pos['quantity'] + delta, 0)
                pos['total_cost'] = _round2(pos['total_cost'] + frac_val)
                pos['average_cost'] = pos['total_cost'] / pos['quantity'] if pos['quantity'] > 0 else 0.0
                corporate_events.append({
                    'date': ev['date'], 'type': 'Fração em Ativos', 'ticker': ticker,
                    'details': f"Fração incorporada: +{delta} ação(ões), custo +R${frac_val:.2f}",
                    'quantity_change': delta,
                })
            else:
                # Fração gerada (vai a leilão) — apenas registra, posição inalterada
                corporate_events.append({
                    'date': ev['date'], 'type': 'Fração em Ativos', 'ticker': ticker,
                    'details': f"Fração de {abs(delta):.2f} ação(ões) gerada — aguarda leilão",
                    'quantity_change': 0,
                })
            operations.append({
                'date': ev['date'], 'ticker': ticker, 'full_name': pos['full_name'],
                'type': 'Fração em Ativos', 'quantity': delta,
                'unit_price': _round2(frac_val / abs(delta)) if delta and frac_val else 0,
                'value': frac_val, 'institution': pos['institution'],
            })

    # ── Aplica ajustes que não foram disparados por evento (ativos sem eventos em 2025) ──
    # Ex: AXIA6 com custo declarado=0 mas sem nenhuma compra/venda em 2025
    if year and ajustes_irpf:
        for ticker_ajuste, ajuste in ajustes_irpf.items():
            if ticker_ajuste not in _irpf_injected and 'custo_declarado' in ajuste:
                if ticker_ajuste in positions:
                    pos_inj = positions[ticker_ajuste]
                    custo_decl = _round2(float(ajuste['custo_declarado']))
                    qty_decl   = ajuste.get('qty_declarada')
                    pos_inj['total_cost'] = custo_decl
                    if qty_decl is not None:
                        pos_inj['quantity'] = _round2(float(qty_decl)) if float(qty_decl) > 0 else pos_inj['quantity']
                    pos_inj['average_cost'] = (
                        pos_inj['total_cost'] / pos_inj['quantity']
                        if pos_inj['quantity'] > 0 else 0.0
                    )

    # ── Monta ativos finais ────────────────────────────────────────────────────
    # Determina timestamps de corte para os dois snapshots temporais
    # Snapshot 1: 31/12 do ano anterior ao selecionado
    # Snapshot 2: 31/12 do ano selecionado (= posição final já calculada acima)
    _year_prev = (year - 1) if year else 0

    def _ts_year_end(y: int) -> int:
        """Retorna timestamp do dia 31/12/yyyy às 23:59."""
        if not y:
            return 0
        try:
            return int(datetime(y, 12, 31, 23, 59).timestamp())
        except Exception:
            return 0

    ts_prev_end = _ts_year_end(_year_prev)   # 31/12/ano-anterior

    # Re-processa a timeline para obter snapshot em 31/12 do ano anterior
    snapshot_prev: Dict[str, float] = {}
    snapshot_prev_qty: Dict[str, float] = {}

    if year and ts_prev_end > 0:
        _pos_snap: Dict[str, Dict] = {}

        def _get_snap(t: str) -> Dict:
            if t not in _pos_snap:
                _pos_snap[t] = {'quantity': 0.0, 'total_cost': 0.0, 'average_cost': 0.0}
            return _pos_snap[t]

        for ev in events:
            if ev['ts'] > ts_prev_end:
                break
            t = ev['ticker']
            p = _get_snap(t)

            if ev['kind'] == 'buy':
                new_qty  = p['quantity'] + ev['quantity']
                new_cost = p['total_cost'] + ev['value']
                p['quantity']     = new_qty
                p['total_cost']   = new_cost
                p['average_cost'] = new_cost / new_qty if new_qty > 0 else 0.0

            elif ev['kind'] == 'sell':
                old_qty  = p['quantity']
                sold_qty = min(ev['quantity'], old_qty)
                if sold_qty > 0 and old_qty > 0:
                    p['total_cost'] = _round2(p['total_cost'] * (old_qty - sold_qty) / old_qty)
                p['quantity']   -= sold_qty
                p['average_cost'] = p['total_cost'] / p['quantity'] if p['quantity'] > 0 else 0.0

            elif ev['kind'] == 'bonus':
                qty        = ev['quantity']
                op_val     = ev.get('operation_value') or 0
                unit_price = ev.get('cost_per_share')  or 0
                bonus_cost = _round2(op_val if op_val > 0 else (qty * unit_price if unit_price > 0 else 0.0))
                p['quantity']   += qty
                p['total_cost']  = _round2(p['total_cost'] + bonus_cost)
                p['average_cost'] = p['total_cost'] / p['quantity'] if p['quantity'] > 0 else 0.0

            elif ev['kind'] in ('split', 'merge'):
                p['quantity']   += ev['quantity_delta']
                p['average_cost'] = p['total_cost'] / p['quantity'] if p['quantity'] > 0 else 0.0

            elif ev['kind'] == 'auction':
                delta = ev.get('quantity_delta', 0)
                if delta < 0:
                    qty = abs(delta)
                    p['quantity']  -= qty
                    p['total_cost'] = _round2(p['average_cost'] * p['quantity'])
                else:
                    p['quantity']   += delta
                    p['average_cost'] = p['total_cost'] / p['quantity'] if p['quantity'] > 0 else 0.0

            elif ev['kind'] == 'amortizacao':
                p['total_cost']   = _round2(max(p['total_cost'] - ev.get('value', 0), 0))
                p['average_cost'] = p['total_cost'] / p['quantity'] if p['quantity'] > 0 else 0.0

            elif ev['kind'] == 'cisao':
                delta = ev.get('quantity_delta', 0)
                if delta != 0:
                    p['quantity'] = max(p['quantity'] + delta, 0)
                p['total_cost']   = _round2(max(p['total_cost'] - ev.get('value', 0), 0))
                p['average_cost'] = p['total_cost'] / p['quantity'] if p['quantity'] > 0 else 0.0

            elif ev['kind'] == 'restituicao_capital':
                p['total_cost']   = _round2(max(p['total_cost'] - ev.get('value', 0), 0))
                p['average_cost'] = p['total_cost'] / p['quantity'] if p['quantity'] > 0 else 0.0

            elif ev['kind'] == 'fraction':
                delta = ev.get('quantity_delta', 0)
                p['quantity']   = max(p['quantity'] + delta, 0)
                p['total_cost'] = _round2(p['total_cost'] + ev.get('value', 0))
                p['average_cost'] = p['total_cost'] / p['quantity'] if p['quantity'] > 0 else 0.0

        for t, p in _pos_snap.items():
            snapshot_prev[t]     = _round2(p['total_cost'])
            snapshot_prev_qty[t] = _round2(p['quantity'])

        # Sobrescreve o snapshot com custo declarado no IRPF anterior, se informado
        for ticker_ajuste, ajuste in ajustes_irpf.items():
            # custo_irpf_anterior = valor exibido na coluna 31/12/ano-anterior (pode ser 0 = omitido)
            # custo_declarado = base para cálculo dos eventos de 2025
            # Se só tem custo_declarado (sem custo_irpf_anterior), usa o mesmo para ambos
            if 'custo_irpf_anterior' in ajuste:
                snapshot_prev[ticker_ajuste] = _round2(float(ajuste['custo_irpf_anterior']))
            elif 'custo_declarado' in ajuste:
                snapshot_prev[ticker_ajuste] = _round2(float(ajuste['custo_declarado']))
            if 'qty_declarada' in ajuste:
                snapshot_prev_qty[ticker_ajuste] = _round2(float(ajuste['qty_declarada']))

    assets = []
    for pos in positions.values():
        if pos['quantity'] < 0.0001:
            continue
        asset_type = _detect_type(pos['ticker'], pos.get('full_name', ''))
        irpf       = _get_irpf_code(asset_type)
        total_cost = _round2(pos['total_cost'])

        ticker = pos['ticker']
        cost_prev_year = snapshot_prev.get(ticker, 0.0)
        qty_prev_year  = snapshot_prev_qty.get(ticker, 0.0)

        assets.append({
            'ticker':                  ticker,
            'reference_ticker':        pos.get('reference_ticker'),
            'full_name':               pos['full_name'],
            'quantity':                _round2(pos['quantity']),
            'average_cost':            _round2(pos['average_cost']),
            'total_cost':              total_cost,
            # Snapshots temporais para a tabela IRPF
            'cost_prev_year':          cost_prev_year,   # Situação em 31/12/ano-anterior
            'qty_prev_year':           qty_prev_year,    # Quantidade em 31/12/ano-anterior
            'cost_curr_year':          total_cost,       # Situação em 31/12/ano-selecionado
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
            'corporate_events_history': pos.get('corporate_events_history', []),
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
