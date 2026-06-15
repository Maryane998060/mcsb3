"""
Validador que avisa quando há ativos com custo zero (dados faltando).
Ajuda a identificar quais ativos precisam de dados históricos de compra.
"""

def validate_costs(assets: list) -> dict:
    """
    Valida e agrupa ativos por status de custo.
    Retorna dicts com avisos detalhados.
    """
    with_cost = [a for a in assets if a['total_cost'] > 0]
    zero_cost = [a for a in assets if a['total_cost'] == 0]
    
    result = {
        'total_assets': len(assets),
        'with_cost': len(with_cost),
        'zero_cost': len(zero_cost),
        'with_cost_total': sum(a['total_cost'] for a in with_cost),
        'zero_cost_tickers': [a['ticker'] for a in zero_cost],
        'coverage_percent': round(100 * len(with_cost) / len(assets), 1) if assets else 0,
        'warning': None,
        'action_needed': False,
    }
    
    if zero_cost:
        result['action_needed'] = True
        result['warning'] = (
            f"AVISO: {len(zero_cost)} ativos têm custo ZERO (dados de compra faltando).\n"
            f"Cobertura: {result['coverage_percent']}% dos ativos com custo calculado.\n"
            f"Custo total calculado: R$ {result['with_cost_total']:,.2f}\n\n"
            f"Ativos faltando dados históricos:\n"
        )
        for ticker in sorted(result['zero_cost_tickers']):
            qty = next((a['quantity'] for a in zero_cost if a['ticker'] == ticker), 0)
            result['warning'] += f"  - {ticker:10} ({qty:8.2f} ações)\n"
        
        result['warning'] += (
            f"\nSOLUÇÃO:\n"
            f"1. Exporte um novo arquivo de Negociação completo (2019-2025) do portal B3/Santander\n"
            f"2. Certifique-se de incluir TODAS as compras históricas de cada ativo\n"
            f"3. Atualize o arquivo 'negociacao-XXXX.xlsx' com esses dados\n"
            f"4. Reprocesse a análise\n\n"
            f"OU\n\n"
            f"Use um arquivo IRPF anterior como referência de posições iniciais."
        )
    else:
        result['warning'] = "OK: Todos os ativos têm dados de custo."
    
    return result


if __name__ == '__main__':
    # Test
    test_assets = [
        {'ticker': 'VALE3', 'total_cost': 1000, 'quantity': 50},
        {'ticker': 'PETR4', 'total_cost': 0, 'quantity': 100},
        {'ticker': 'ITUB4', 'total_cost': 500, 'quantity': 25},
    ]
    
    result = validate_costs(test_assets)
    print(result['warning'])
