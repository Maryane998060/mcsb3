"""
Calculador de DARF — Renda Variável (Pessoa Física)
====================================================
Regras aplicadas (legislação vigente 2025):

SWING TRADE (ações mercado à vista):
  - Isenção: total de VENDAS no mês <= R$ 20.000,00 → lucro isento
  - Tributação: total de VENDAS > R$ 20.000,00 → alíquota 15% sobre lucro líquido
  - Prejuízos de meses anteriores podem ser compensados
  - Código DARF: 6015

DAY TRADE:
  - Alíquota 20% sobre o lucro — SEM isenção de R$20k
  - Prejuízos só compensam lucros de day trade (não de swing)
  - Código DARF: 6015 (mesmo código, base separada)

FII, ETF, BDR:
  - FII: 20% sem isenção, código DARF 6015
  - ETF: 15% sem isenção (ETF renda variável nacional)
  - BDR: 15% sem isenção

IMPORTANTE: O sistema não diferencia day trade das planilhas da B3 (não há
essa informação nas planilhas de negociação exportadas). Todas as vendas são
tratadas como swing trade. Para day trade, o usuário deve informar
manualmente o IRRF retido na nota de corretagem.
"""

from typing import List, Dict, Any
from collections import defaultdict


LIMITE_ISENCAO_SWING = 20_000.00   # R$20.000 mensais em vendas
ALIQUOTA_SWING       = 0.15        # 15%
ALIQUOTA_DAY_TRADE   = 0.20        # 20%
ALIQUOTA_FII         = 0.20        # 20%
ALIQUOTA_ETF         = 0.15        # 15%
CODIGO_DARF          = '6015'
VENCIMENTO_DIA       = 31          # último dia útil do mês seguinte (simplificado)


def _round2(v: float) -> float:
    return round(v, 2)


def _get_mes_ano(date_str: str) -> str:
    """Extrai MM/YYYY de DD/MM/YYYY."""
    parts = date_str.strip().split('/')
    if len(parts) == 3:
        return f"{parts[1]}/{parts[2]}"
    return ''


def _asset_type_category(ticker: str, asset_type: str = '') -> str:
    """
    Categoriza o ativo para fins de tributação.
    Returns: 'swing', 'fii', 'etf', 'bdr'
    """
    t = (asset_type or '').upper()
    if t == 'FII':
        return 'fii'
    if t == 'ETF':
        return 'etf'
    if t == 'BDR':
        return 'bdr'
    return 'swing'


def calcular_darf_mensal(
    sales: List[Dict],
    asset_map: Dict[str, str] = None,
) -> List[Dict]:
    """
    Calcula o DARF por mês a partir da lista de vendas.

    sales: lista de dicts com:
        - date: DD/MM/YYYY
        - ticker: str
        - sale_price: float (valor total de venda)
        - gain: float (lucro ou prejuízo)
        - quantity: float

    asset_map: {ticker: asset_type} para identificar FII/ETF/BDR.
               Se None, trata tudo como swing trade.

    Retorna lista de dicts por mês com:
        - mes_ano: str  MM/YYYY
        - total_vendas_swing: float
        - total_vendas_fii: float
        - lucro_bruto_swing: float
        - lucro_bruto_fii: float
        - isento_swing: bool  (vendas <= 20k)
        - prejuizo_compensado_swing: float
        - base_calculo_swing: float
        - imposto_swing: float
        - imposto_fii: float
        - imposto_total: float
        - codigo_darf: str
        - saldo_prejuizo_acumulado: float  (carregado para o mês seguinte)
        - detalhes: List[Dict]  (vendas individuais do mês)
    """
    if asset_map is None:
        asset_map = {}

    # Agrupa vendas por mês
    por_mes: Dict[str, List[Dict]] = defaultdict(list)
    for sale in sales:
        mes = _get_mes_ano(sale['date'])
        if mes:
            por_mes[mes].append(sale)

    meses_ordenados = sorted(por_mes.keys(), key=lambda m: (int(m.split('/')[1]), int(m.split('/')[0])))

    resultado: List[Dict] = []
    prejuizo_acumulado_swing = 0.0   # saldo negativo a compensar em meses futuros
    prejuizo_acumulado_fii   = 0.0

    for mes in meses_ordenados:
        vendas = por_mes[mes]

        # Separa por categoria
        swing_vendas = [v for v in vendas if _asset_type_category(v['ticker'], asset_map.get(v['ticker'], '')) == 'swing']
        fii_vendas   = [v for v in vendas if _asset_type_category(v['ticker'], asset_map.get(v['ticker'], '')) == 'fii']
        etf_vendas   = [v for v in vendas if _asset_type_category(v['ticker'], asset_map.get(v['ticker'], '')) == 'etf']
        bdr_vendas   = [v for v in vendas if _asset_type_category(v['ticker'], asset_map.get(v['ticker'], '')) == 'bdr']

        # ── SWING TRADE ──────────────────────────────────────────────────────
        total_vendas_swing = _round2(sum(v['sale_price'] for v in swing_vendas))
        lucro_bruto_swing  = _round2(sum(v['gain'] for v in swing_vendas))

        # Verifica isenção: total de VENDAS (não lucro) <= 20k
        isento_swing = total_vendas_swing <= LIMITE_ISENCAO_SWING and lucro_bruto_swing > 0

        imposto_swing = 0.0
        prejuizo_compensado_swing = 0.0
        base_calculo_swing = 0.0

        if not isento_swing and lucro_bruto_swing != 0:
            if lucro_bruto_swing < 0:
                # Acumula prejuízo para compensar futuramente
                prejuizo_acumulado_swing = _round2(prejuizo_acumulado_swing + lucro_bruto_swing)
            else:
                # Compensa prejuízos anteriores
                if prejuizo_acumulado_swing < 0:
                    prejuizo_compensado_swing = min(abs(prejuizo_acumulado_swing), lucro_bruto_swing)
                    prejuizo_acumulado_swing   = _round2(prejuizo_acumulado_swing + prejuizo_compensado_swing)
                    prejuizo_compensado_swing  = _round2(prejuizo_compensado_swing)

                base_calculo_swing = _round2(lucro_bruto_swing - prejuizo_compensado_swing)
                imposto_swing = _round2(max(base_calculo_swing * ALIQUOTA_SWING, 0))

        # ── FII ───────────────────────────────────────────────────────────────
        total_vendas_fii = _round2(sum(v['sale_price'] for v in fii_vendas))
        lucro_bruto_fii  = _round2(sum(v['gain'] for v in fii_vendas))
        imposto_fii = 0.0
        prejuizo_compensado_fii = 0.0
        base_calculo_fii = 0.0

        if lucro_bruto_fii != 0:
            if lucro_bruto_fii < 0:
                prejuizo_acumulado_fii = _round2(prejuizo_acumulado_fii + lucro_bruto_fii)
            else:
                if prejuizo_acumulado_fii < 0:
                    prejuizo_compensado_fii = min(abs(prejuizo_acumulado_fii), lucro_bruto_fii)
                    prejuizo_acumulado_fii   = _round2(prejuizo_acumulado_fii + prejuizo_compensado_fii)
                base_calculo_fii = _round2(lucro_bruto_fii - prejuizo_compensado_fii)
                imposto_fii = _round2(max(base_calculo_fii * ALIQUOTA_FII, 0))

        # ── ETF / BDR (15% sem isenção) ───────────────────────────────────────
        lucro_etf = _round2(sum(v['gain'] for v in etf_vendas + bdr_vendas))
        imposto_etf = _round2(max(lucro_etf * ALIQUOTA_ETF, 0)) if lucro_etf > 0 else 0.0

        imposto_total = _round2(imposto_swing + imposto_fii + imposto_etf)

        # Monta detalhes de cada venda
        detalhes = []
        for v in sorted(vendas, key=lambda x: x['date']):
            cat  = _asset_type_category(v['ticker'], asset_map.get(v['ticker'], ''))
            det  = {
                'date':        v['date'],
                'ticker':      v['ticker'],
                'quantidade':  v['quantity'],
                'sale_price':  v['sale_price'],
                'cost_basis':  v['cost_basis'],
                'gain':        v['gain'],
                'categoria':   cat,
                'isento':      isento_swing and cat == 'swing',
            }
            detalhes.append(det)

        resultado.append({
            'mes_ano':                   mes,
            'total_vendas_swing':         total_vendas_swing,
            'total_vendas_fii':           total_vendas_fii,
            'lucro_bruto_swing':          lucro_bruto_swing,
            'lucro_bruto_fii':            lucro_bruto_fii,
            'lucro_etf_bdr':              lucro_etf,
            'isento_swing':               isento_swing,
            'motivo_isencao':             f'Vendas R${total_vendas_swing:.2f} <= R$20.000' if isento_swing else '',
            'prejuizo_compensado_swing':  prejuizo_compensado_swing,
            'prejuizo_compensado_fii':    prejuizo_compensado_fii,
            'base_calculo_swing':         base_calculo_swing,
            'base_calculo_fii':           base_calculo_fii,
            'imposto_swing':              imposto_swing,
            'imposto_fii':                imposto_fii,
            'imposto_etf_bdr':            imposto_etf,
            'imposto_total':              imposto_total,
            'saldo_prejuizo_swing':       _round2(prejuizo_acumulado_swing),
            'saldo_prejuizo_fii':         _round2(prejuizo_acumulado_fii),
            'codigo_darf':                CODIGO_DARF if imposto_total > 0 else '',
            'deve_pagar':                 imposto_total > 0,
            'detalhes':                   detalhes,
        })

    return resultado


def resumo_darf_ano(darfs: List[Dict]) -> Dict[str, Any]:
    """Consolida os DARFs do ano em um resumo."""
    return {
        'total_imposto_devido':    _round2(sum(d['imposto_total'] for d in darfs)),
        'total_imposto_swing':     _round2(sum(d['imposto_swing'] for d in darfs)),
        'total_imposto_fii':       _round2(sum(d['imposto_fii'] for d in darfs)),
        'total_imposto_etf_bdr':   _round2(sum(d['imposto_etf_bdr'] for d in darfs)),
        'meses_com_imposto':       sum(1 for d in darfs if d['deve_pagar']),
        'meses_isentos':           sum(1 for d in darfs if d['isento_swing'] and not d['deve_pagar']),
        'meses_com_prejuizo':      sum(1 for d in darfs if d['lucro_bruto_swing'] < 0 or d['lucro_bruto_fii'] < 0),
        'saldo_prejuizo_final':    darfs[-1]['saldo_prejuizo_swing'] if darfs else 0.0,
        'total_vendas_swing':      _round2(sum(d['total_vendas_swing'] for d in darfs)),
        'total_lucro_bruto_swing': _round2(sum(d['lucro_bruto_swing'] for d in darfs)),
        'total_compensado':        _round2(sum(d['prejuizo_compensado_swing'] for d in darfs)),
    }
