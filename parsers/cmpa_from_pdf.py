"""
Calculador de CMPA baseado em posição final (PDF) + Negociações + Movimentação

Algoritmo:
1. Extrai quantidade FINAL de cada ativo do PDF (posição em 31/12/2025)
2. Lê TODAS as negociações (compras/vendas) do arquivo
3. Rastreia eventos corporativos (bonificação, desdobro, etc) da movimentação
4. Calcula quantidade acumulada até 31/12/2025
5. Calcula CMPA = custo total acumulado / quantidade final
"""

from datetime import datetime
from collections import defaultdict


def extract_positions_from_pdf(pdf_text: str) -> dict:
    """
    Extrai posições finais do PDF.
    Retorna: {ticker: {quantidade: float, valor_atualizado: float}}
    """
    import re
    
    positions = {}
    lines = pdf_text.split('\n')
    
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        
        # Procura ticker no padrão TICKER - NOME
        if re.match(r'^[A-Z]{1,6}\d{1,2}\s*-', line):
            match = re.match(r'^([A-Z]{1,6}\d{1,2})\s*-\s*(.+)$', line)
            if match:
                ticker = match.group(1)
                
                i += 1
                if i < len(lines):
                    next_line = lines[i].strip()
                    # Procura: "TIPO QTD R$ PREÇO R$ VALOR"
                    qty_match = re.search(
                        r'(\d+[\.,]\d+|\d+)\s+R\$\s+([\d\.]+,\d+)\s+R\$\s+([\d\.]+,\d+)',
                        next_line
                    )
                    
                    if qty_match:
                        qty_str = qty_match.group(1).replace('.', '').replace(',', '.')
                        qty = float(qty_str)
                        
                        valor_str = qty_match.group(3).replace('.', '').replace(',', '.')
                        valor = float(valor_str)
                        
                        positions[ticker] = {
                            'quantidade_final': qty,
                            'valor_atualizado': valor,
                            'preco_atual': valor / qty if qty > 0 else 0
                        }
        i += 1
    
    return positions


def calculate_cmpa_from_pdf(
    pdf_positions: dict,
    transactions: list,
    movements: list
) -> dict:
    """
    Calcula CMPA baseado em posição final do PDF.
    
    Algoritmo:
    1. Começa com quantidade final (PDF)
    2. Subtrai vendas para chegar à quantidade em cada data de compra
    3. Acumula custos de compra e eventos corporativos
    4. Calcula CMPA final
    """
    
    assets = {}
    
    # Inicializa com dados do PDF
    for ticker, pos in pdf_positions.items():
        # pos tem chaves: quantidade, valor_atualizado, preco_atual
        qtd = pos.get('quantidade', pos.get('quantidade_final', 0))
        
        assets[ticker] = {
            'ticker': ticker,
            'quantidade_final': qtd,
            'quantidade_atual': qtd,  # Será recalculado
            'custo_total': 0.0,
            'custo_medio': 0.0,
            'compras': [],
            'vendas': [],
            'eventos_corporativos': [],
            'valor_atualizado': pos.get('valor_atualizado', 0),
        }
    
    # Agrupa transações por ticker
    transactions_by_ticker = defaultdict(list)
    for trans in transactions:
        ticker = trans.get('ticker', '').upper()
        if ticker:
            transactions_by_ticker[ticker].append(trans)
    
    # Agrupa movimentações por ticker
    movements_by_ticker = defaultdict(list)
    for mov in movements:
        ticker = mov.get('ticker', '').upper()
        if ticker:
            movements_by_ticker[ticker].append(mov)
    
    # Processa cada ativo encontrado no PDF
    for ticker in pdf_positions.keys():
        if ticker not in assets:
            continue
        
        asset = assets[ticker]
        compras = transactions_by_ticker.get(ticker, [])
        eventos = movements_by_ticker.get(ticker, [])
        
        # Ordena compras por data
        compras_ordenadas = sorted(compras, key=lambda x: x.get('date', ''))
        
        # Calcula quantidade acumulada e custos
        qtd_acum = 0.0
        custo_acum = 0.0
        
        for compra in compras_ordenadas:
            # Pula vendas (ir_type == 2)
            if 'type' in compra and 'venda' in compra['type'].lower():
                continue
            
            qty = float(compra.get('quantity', 0))
            preco = float(compra.get('price', 0))
            valor = qty * preco
            
            qtd_acum += qty
            custo_acum += valor
            
            asset['compras'].append({
                'data': compra.get('date', ''),
                'quantidade': qty,
                'preco': preco,
                'valor': valor,
            })
        
        # Processa eventos corporativos que afetam quantidade
        for evento in eventos:
            tipo = evento.get('type', '').lower()
            
            if 'bonificação' in tipo or 'bonificacao' in tipo:
                # Bonificação aumenta quantidade
                qty_bonus = float(evento.get('quantity', 0))
                qtd_acum += qty_bonus
                asset['eventos_corporativos'].append({
                    'data': evento.get('date', ''),
                    'tipo': 'Bonificação',
                    'quantidade': qty_bonus,
                })
            
            elif 'desdobro' in tipo:
                # Desdobro: quantidade aumenta
                qty_desdobro = float(evento.get('quantity', 0))
                qtd_acum += qty_desdobro
                asset['eventos_corporativos'].append({
                    'data': evento.get('date', ''),
                    'tipo': 'Desdobro',
                    'quantidade': qty_desdobro,
                })
            
            elif 'grupamento' in tipo or 'agrupamento' in tipo:
                # Grupamento: quantidade diminui (proporção inversa)
                # Para simplificar, usando como quantidade negativa
                qty_grupo = float(evento.get('quantity', 0))
                if qty_grupo > 0:
                    qtd_acum -= qty_grupo
                asset['eventos_corporativos'].append({
                    'data': evento.get('date', ''),
                    'tipo': 'Grupamento',
                    'quantidade': -qty_grupo,
                })
        
        # Processa vendas (reduz quantidade mas não afeta custo)
        vendas_ordenadas = sorted(
            [t for t in compras_ordenadas if 'venda' in t.get('type', '').lower()],
            key=lambda x: x.get('date', '')
        )
        
        for venda in vendas_ordenadas:
            qty = float(venda.get('quantity', 0))
            qtd_acum -= qty
            asset['vendas'].append({
                'data': venda.get('date', ''),
                'quantidade': qty,
                'preco': float(venda.get('price', 0)),
            })
        
        # Atualiza dados do ativo
        asset['quantidade_atual'] = qtd_acum
        asset['custo_total'] = custo_acum
        asset['custo_medio'] = custo_acum / asset['quantidade_final'] if asset['quantidade_final'] > 0 else 0
        
        # Verifica consistência
        if abs(qtd_acum - asset['quantidade_final']) > 0.01:
            asset['_warning'] = (
                f"Quantidade acumulada ({qtd_acum:.2f}) diferente da "
                f"quantidade no PDF ({asset['quantidade_final']:.2f}). "
                f"Faltam eventos ou dados."
            )
    
    return assets


if __name__ == '__main__':
    # Teste
    pdf_pos = {
        'SOJA3': {'quantidade_final': 200, 'valor_atualizado': 1895.91},
        'AGRO3': {'quantidade_final': 100, 'valor_atualizado': 1994.00},
    }
    
    transactions = [
        {
            'ticker': 'SOJA3',
            'type': 'Compra',
            'date': '26/08/2022',
            'quantity': 200,
            'price': 12.85,
        },
        {
            'ticker': 'SOJA3',
            'type': 'Venda',
            'date': '10/12/2025',
            'quantity': 100,
            'price': 9.08,
        },
    ]
    
    movements = []
    
    result = calculate_cmpa_from_pdf(pdf_pos, transactions, movements)
    
    for ticker, asset in result.items():
        print(f"\n{ticker}:")
        print(f"  Qtd Final: {asset['quantidade_final']:.2f}")
        print(f"  Custo Total: R$ {asset['custo_total']:.2f}")
        print(f"  Custo Médio: R$ {asset['custo_medio']:.2f}")
        if '_warning' in asset:
            print(f"  ⚠️ {asset['_warning']}")
