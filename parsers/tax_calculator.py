"""
Calculadora de imposto de renda sobre ganho de capital
Conforme legislação RFB atual
"""

from datetime import datetime, date
from decimal import Decimal
from typing import List, Dict, Tuple, Any
from dataclasses import dataclass
import calendar


@dataclass
class OperacaoVenda:
    """Representa uma venda para cálculo de imposto"""
    data: date
    ticker: str
    quantidade: Decimal
    preco_compra: Decimal
    preco_venda: Decimal
    custo_medio_aquisicao: Decimal
    custos_operacionais: Decimal
    
    @property
    def valor_total_venda(self) -> Decimal:
        return self.quantidade * self.preco_venda
    
    @property
    def valor_total_compra(self) -> Decimal:
        return self.quantidade * self.custo_medio_aquisicao
    
    @property
    def lucro_bruto(self) -> Decimal:
        return self.valor_total_venda - self.valor_total_compra
    
    @property
    def lucro_liquido(self) -> Decimal:
        """Lucro após descontar custos operacionais"""
        return self.lucro_bruto - self.custos_operacionais
    
    @property
    def eh_lucro(self) -> bool:
        return self.lucro_liquido > 0


@dataclass
class OperacaoMes:
    """Agregação de operações por mês"""
    mes: int
    ano: int
    operacoes: List[OperacaoVenda]
    prejuizo_anterior: Decimal = Decimal('0')
    
    @property
    def total_lucro_bruto(self) -> Decimal:
        return sum(op.lucro_bruto for op in self.operacoes)
    
    @property
    def total_custos(self) -> Decimal:
        return sum(op.custos_operacionais for op in self.operacoes)
    
    @property
    def total_lucro_liquido(self) -> Decimal:
        return sum(op.lucro_liquido for op in self.operacoes)
    
    @property
    def total_prejuizo(self) -> Decimal:
        """Soma de prejuízos (valores negativos)"""
        return sum(op.lucro_liquido for op in self.operacoes if op.lucro_liquido < 0)
    
    @property
    def lucro_compensado(self) -> Decimal:
        """Lucro após compensar prejuízo anterior"""
        lucro_bruto = self.total_lucro_liquido
        compensacao = min(abs(self.prejuizo_anterior), lucro_bruto)
        if self.prejuizo_anterior < 0:
            lucro_bruto = lucro_bruto - compensacao
        return lucro_bruto
    
    @property
    def eh_isento(self) -> bool:
        """Operação isenta se lucro <= R$ 20.000"""
        return self.lucro_compensado <= Decimal('20000')
    
    @property
    def eh_lucro(self) -> bool:
        return self.lucro_compensado > 0
    
    @property
    def mes_ano_str(self) -> str:
        return f"{self.mes:02d}/{self.ano}"


@dataclass
class CalculoIRAnual:
    """Cálculo completo de IR anual"""
    ano: int
    operacoes_mes: Dict[Tuple[int, int], OperacaoMes]
    
    @property
    def total_lucro_anual(self) -> Decimal:
        return sum(om.total_lucro_liquido for om in self.operacoes_mes.values())
    
    @property
    def total_prejuizo_anual(self) -> Decimal:
        total = Decimal('0')
        for om in self.operacoes_mes.values():
            if om.total_lucro_liquido < 0:
                total += om.total_lucro_liquido
        return total


class CalculadoraIR:
    """
    Calculadora de IR sobre ganho de capital (renda variável)
    
    Regras:
    - Alíquota: 15% (operação > 20 dias) ou 20% (day-trade ou < 20 dias)
    - Isenção: operações com lucro <= R$ 20.000 no mês
    - Prejuízo: carregável indefinidamente para meses posteriores
    - Declaração: obrigatória se lucro > R$ 0 no mês (mesmo que isento)
    """
    
    ALIQUOTA_LONGO_PRAZO = Decimal('0.15')  # 15%
    ALIQUOTA_CURTO_PRAZO = Decimal('0.20')  # 20%
    LIMITE_ISENCAO = Decimal('20000')
    
    def __init__(self):
        self.operacoes: List[OperacaoVenda] = []
    
    def adicionar_venda(
        self,
        data: date,
        ticker: str,
        quantidade: Decimal,
        preco_compra: Decimal,
        preco_venda: Decimal,
        custo_medio_aquisicao: Decimal,
        custos_operacionais: Decimal = Decimal('0')
    ) -> None:
        """Adiciona uma operação de venda para cálculo"""
        op = OperacaoVenda(
            data=data,
            ticker=ticker,
            quantidade=quantidade,
            preco_compra=preco_compra,
            preco_venda=preco_venda,
            custo_medio_aquisicao=custo_medio_aquisicao,
            custos_operacionais=custos_operacionais
        )
        self.operacoes.append(op)
    
    def _eh_longo_prazo(self, data_compra: date, data_venda: date) -> bool:
        """Verifica se operação é de longo prazo (> 20 dias)"""
        dias = (data_venda - data_compra).days
        return dias > 20
    
    def _calcular_aliquota(self, op: OperacaoVenda, dias_posicao: int) -> Decimal:
        """Determina alíquota baseado em dias de posição"""
        if dias_posicao > 20:
            return self.ALIQUOTA_LONGO_PRAZO
        return self.ALIQUOTA_CURTO_PRAZO
    
    def agregar_por_mes(self, ano: int) -> Dict[Tuple[int, int], OperacaoMes]:
        """Agrupa operações por mês/ano"""
        meses = {}
        
        for op in self.operacoes:
            if op.data.year != ano:
                continue
            
            mes = op.data.month
            chave = (mes, ano)
            
            if chave not in meses:
                meses[chave] = OperacaoMes(mes=mes, ano=ano, operacoes=[])
            
            meses[chave].operacoes.append(op)
        
        # Compensa prejuízos entre meses
        meses_ordenados = sorted(meses.keys())
        prejuizo_acumulado = Decimal('0')
        
        for mes, ano_chave in meses_ordenados:
            mes_obj = meses[(mes, ano_chave)]
            mes_obj.prejuizo_anterior = prejuizo_acumulado
            
            # Atualiza prejuízo acumulado para próximo mês
            if mes_obj.lucro_compensado < 0:
                prejuizo_acumulado += abs(mes_obj.lucro_compensado)
            elif prejuizo_acumulado > 0:
                prejuizo_acumulado -= min(prejudizo_acumulado, mes_obj.lucro_compensado)
        
        return meses
    
    def calcular_darf_mensal(
        self,
        ano: int,
        mes: int,
        operacoes_mes: OperacaoMes
    ) -> Dict[str, Any]:
        """
        Calcula DARF para um mês específico
        
        Retorna:
            {
                'deve_gerar_darf': bool,
                'valor_imposto': Decimal,
                'aliquota': Decimal,
                'motivo_isencao': str or None,
                'data_vencimento': date,
                'codigo_receita': str
            }
        """
        
        if not operacoes_mes.eh_lucro:
            # Prejuízo no mês - não gera DARF, mas declara
            return {
                'deve_gerar_darf': False,
                'valor_imposto': Decimal('0'),
                'aliquota': Decimal('0'),
                'motivo_isencao': 'Prejuízo no mês',
                'declara_prejuizo': True,
                'valor_prejuizo': abs(operacoes_mes.total_prejuizo)
            }
        
        # Tem lucro - verifica isenção
        if operacoes_mes.eh_isento:
            return {
                'deve_gerar_darf': False,
                'valor_imposto': Decimal('0'),
                'aliquota': Decimal('0'),
                'motivo_isencao': 'Lucro <= R$ 20.000',
                'declara_lucro': True,
                'valor_lucro': operacoes_mes.lucro_compensado
            }
        
        # Lucro > R$ 20.000 - deve pagar imposto
        lucro_tributavel = operacoes_mes.lucro_compensado
        
        # Alíquota padrão 15% (pode variar com day-trade)
        aliquota = self.ALIQUOTA_LONGO_PRAZO
        valor_imposto = lucro_tributavel * aliquota
        
        # Vencimento: até o 3º dia útil do mês seguinte (aqui simplificamos para dia 3)
        if mes == 12:
            data_vencimento = date(ano + 1, 1, 15)
        else:
            _, ultimo_dia = calendar.monthrange(ano, mes + 1)
            data_vencimento = date(ano, mes + 1, min(15, ultimo_dia))
        
        return {
            'deve_gerar_darf': True,
            'valor_imposto': valor_imposto.quantize(Decimal('0.01')),
            'aliquota': aliquota,
            'motivo_isencao': None,
            'mes_ano': f"{mes:02d}/{ano}",
            'data_vencimento': data_vencimento,
            'codigo_receita': '6015',  # IR - Pessoa Física
            'valor_lucro': lucro_tributavel.quantize(Decimal('0.01'))
        }
    
    def gerar_darf_completo(self, ano: int) -> List[Dict[str, Any]]:
        """Gera relatório DARF completo para o ano"""
        operacoes_por_mes = self.agregar_por_mes(ano)
        darfs = []
        
        for (mes, ano_chave), mes_obj in sorted(operacoes_por_mes.items()):
            darf = self.calcular_darf_mensal(ano_chave, mes, mes_obj)
            if darf['deve_gerar_darf']:
                darfs.append(darf)
        
        return darfs
    
    def gerar_resumo_anual(self, ano: int) -> Dict[str, Any]:
        """Gera resumo fiscal anual"""
        operacoes_por_mes = self.agregar_por_mes(ano)
        total_lucro = Decimal('0')
        total_imposto = Decimal('0')
        darfs_emitidos = []
        
        for (mes, ano_chave), mes_obj in sorted(operacoes_por_mes.items()):
            darf = self.calcular_darf_mensal(ano_chave, mes, mes_obj)
            if darf['deve_gerar_darf']:
                total_imposto += darf['valor_imposto']
                darfs_emitidos.append(darf)
            total_lucro += mes_obj.total_lucro_liquido
        
        return {
            'ano': ano,
            'total_vendas': len(self.operacoes),
            'total_lucro_bruto': sum(op.lucro_bruto for op in self.operacoes).quantize(Decimal('0.01')),
            'total_custos': sum(op.custos_operacionais for op in self.operacoes).quantize(Decimal('0.01')),
            'total_lucro_liquido': total_lucro.quantize(Decimal('0.01')),
            'total_imposto': total_imposto.quantize(Decimal('0.01')),
            'darfs_emitidos': len(darfs_emitidos),
            'lista_darfs': darfs_emitidos
        }
