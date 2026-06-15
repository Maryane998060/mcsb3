#!/usr/bin/env python3
"""
Demo: Calcular CMPA usando IRPF anterior + Transações 2025

Uso:
  python demo_irpf_based_cmpa.py
"""

from pathlib import Path
from parsers.cmpa_with_irpf_base import extract_irpf_positions, apply_transactions_2025
from parsers.excel_parser import parse_negociacao_sheet, parse_movimentacao_sheet
from parsers.pdf_positions_extractor import extract_positions_from_pdf_file


def main():
    root = Path(r'g:\Maryane\calculainvestimentoir\exemplos')
    
    print("="*80)
    print("CALCULADOR DE CMPA COM BASE EM IRPF ANTERIOR")
    print("="*80)
    
    # 1. CARREGA IRPF ANTERIOR
    print("\n[1/4] Carregando IRPF anterior (posição 31/12/2024)...")
    irpf_file = str(root / 'analise_acoes_IRPF2026_paulo_henrique.xlsx')
    irpf_positions = extract_irpf_positions(irpf_file)
    
    print(f"  ✓ {len(irpf_positions)} ativos carregados do IRPF:")
    total_irpf = 0
    for ticker in sorted(irpf_positions.keys()):
        pos = irpf_positions[ticker]
        print(f"    {ticker:10} {pos['quantidade']:10.2f} x R$ {pos['custo_medio']:10.2f} = R$ {pos['custo_total']:12.2f}")
        total_irpf += pos['custo_total']
    print(f"    {'TOTAL':10} {'':10} {'':10} = R$ {total_irpf:12.2f}")
    
    # 2. CARREGA TRANSAÇÕES 2025
    print("\n[2/4] Carregando transações de 2025...")
    neg_file = str(root / 'negociacao-2019 a 2025.xlsx')
    transactions = parse_negociacao_sheet(neg_file)
    
    # Filtra só 2025
    trans_2025 = [t for t in transactions if '2025' in t.get('date', '')]
    print(f"  ✓ {len(trans_2025)} transações de 2025")
    
    for t in trans_2025:
        tipo = "COMPRA" if 'compra' in t['type'].lower() else "VENDA"
        print(f"    {t['date']} {tipo:6} {t['ticker']:10} {t['quantity']:10.2f} @ R$ {t['price']:8.2f}")
    
    # 3. CARREGA MOVIMENTACAO (eventos corporativos)
    print("\n[3/4] Carregando movimentação (eventos corporativos)...")
    mov_file = str(root / 'movimentacao-2026-05-29-20-41-53.xlsx')
    movements = parse_movimentacao_sheet(mov_file)
    mov_2025 = [m for m in movements if '2025' in m.get('date', '')]
    print(f"  ✓ {len(movements)} registros de movimentação")
    print(f"    {len(mov_2025)} eventos em 2025")
    
    # 4. CALCULA NOVO CMPA
    print("\n[4/4] Calculando novo CMPA com transações 2025...")
    
    # Carrega posições finais do PDF (para validação)
    pdf_file = str(root / 'relatorio-consolidado-anual-2025.pdf')
    pdf_positions = extract_positions_from_pdf_file(pdf_file)
    
    # Calcula
    assets = apply_transactions_2025(irpf_positions, transactions, movements, pdf_positions)
    
    # 5. EXIBE RESULTADO
    print("\n" + "="*80)
    print("RESULTADO FINAL - CMPA COM BASE IRPF ANTERIOR")
    print("="*80 + "\n")
    
    print(f"{'Ticker':10} {'Qtd Inicial':>12} {'Qtd Final':>12} {'Custo Medio':>12} {'Custo Total':>12}")
    print("-" * 70)
    
    total_custo_inicial = 0
    total_custo_final = 0
    
    for ticker in sorted(assets.keys()):
        asset = assets[ticker]
        
        qtd_ini = asset['quantidade_inicial']
        qtd_fim = asset['quantidade_atual']
        custo_med = asset['custo_medio']
        custo_tot = asset['custo_total_atual']
        
        total_custo_inicial += asset['custo_total_inicial']
        total_custo_final += custo_tot
        
        warning = ""
        if '_warning' in asset:
            warning = f"  [{asset['_warning']}]"
        
        print(f"{ticker:10} {qtd_ini:12.2f} {qtd_fim:12.2f} R$ {custo_med:11.2f} R$ {custo_tot:11.2f}{warning}")
    
    print("-" * 70)
    print(f"{'TOTAL':10} {'':12} {'':12} {'':12} R$ {total_custo_final:11.2f}")
    
    print(f"\nVariacao de Custo: R$ {total_custo_inicial:,.2f} → R$ {total_custo_final:,.2f}")
    print(f"Diferenca: R$ {total_custo_final - total_custo_inicial:+,.2f}")
    
    # Detalhes das transações 2025
    print("\n" + "="*80)
    print("DETALHES DE TRANSAÇÕES 2025")
    print("="*80 + "\n")
    
    for ticker in sorted(assets.keys()):
        asset = assets[ticker]
        if asset['transacoes_2025']:
            print(f"\n{ticker}:")
            for t in asset['transacoes_2025']:
                print(f"  {t['data']} {t['acao'].upper():6} {t['quantidade']:10.2f} @ R$ {t['preco']:8.2f}")


if __name__ == '__main__':
    main()
