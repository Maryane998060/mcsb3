"""
Calculadora de CMPA (Custo Médio Ponderado de Aquisição)
Com suporte a eventos corporativos (bonificação, desdobramento, agrupamento, etc)
"""

from datetime import date
from decimal import Decimal
from typing import List, Dict, Tuple, Any
from dataclasses import dataclass


@dataclass
class MovimentoAtivo:
    """Base para qualquer movimento de ativo"""
    data: date
    tipo: str  # 'compra', 'venda', 'bonificacao', 'desdobramento', 'agrupamento', etc
    

@dataclass
class Compra(MovimentoAtivo):
    """Compra de ativo"""
    quantidade: Decimal
    preco_unitario: Decimal
    custos_operacionais: Decimal = Decimal('0')
    
    @property
    def valor_total(self) -> Decimal:
        return (self.quantidade * self.preco_unitario) + self.custos_operacionais


@dataclass
class Venda(MovimentoAtivo):
    """Venda de ativo"""
    quantidade: Decimal
    preco_unitario: Decimal
    custos_operacionais: Decimal = Decimal('0')
    cmpa_na_operacao: Decimal = Decimal('0')  # Preenchido durante cálculo
    
    @property
    def valor_total(self) -> Decimal:
        return self.quantidade * self.preco_unitario


@dataclass
class Bonificacao(MovimentoAtivo):
    """Evento corporativo: Bonificação"""
    quantidade_adicionada: Decimal
    preco_unitario_bonificacao: Decimal = Decimal('0')
    
    @property
    def valor_bonificacao(self) -> Decimal:
        """Valor da bonificação para adicionar ao custo"""
        return self.quantidade_adicionada * self.preco_unitario_bonificacao


@dataclass
class Desdobramento(MovimentoAtivo):
    """Evento corporativo: Desdobramento (split)"""
    taxa: Decimal  # Ex: 2 para 2:1, 3 para 3:1


@dataclass
class Agrupamento(MovimentoAtivo):
    """Evento corporativo: Agrupamento (reverse split)"""
    taxa: Decimal  # Ex: 2 para 2:1 (divide quantidade)


@dataclass
class OperacaoCMPA:
    """Estado CMPA de uma operação"""
    data: date
    quantidade: Decimal
    preco_medio: Decimal
    custo_total: Decimal  # quantidade * preco_medio
    descricao: str
    
    def __repr__(self):
        return f"<CMPA({self.data}, qtd={self.quantidade}, cmpa={self.preco_medio:.4f}, total={self.custo_total:.2f})>"


class CalculadoraCMPA:
    """
    Calcula CMPA com suporte a eventos corporativos.
    
    Princípio: O custo de aquisição é distribuído entre as quantidades
    atualizadas pelos eventos corporativos.
    
    CMPA = Custo Total de Aquisição / Quantidade Total Atualizada
    """
    
    def __init__(self):
        self.historico: List[OperacaoCMPA] = []
        self.custo_total_acumulado = Decimal('0')  # Custo de aquisição
        self.quantidade_atual = Decimal('0')  # Quantidade atual
    
    def adicionar_compra(
        self,
        data: date,
        quantidade: Decimal,
        preco_unitario: Decimal,
        custos_operacionais: Decimal = Decimal('0'),
        descricao: str = ""
    ) -> None:
        """Adiciona uma compra ao CMPA"""
        compra = Compra(
            data=data,
            tipo='compra',
            quantidade=quantidade,
            preco_unitario=preco_unitario,
            custos_operacionais=custos_operacionais
        )
        
        valor_total = compra.valor_total
        self.custo_total_acumulado += valor_total
        self.quantidade_atual += quantidade
        
        # Recalcula CMPA
        nova_cmpa = self._calcular_cmpa()
        
        desc = descricao or f"Compra de {quantidade} unidades @ R$ {preco_unitario}"
        self.historico.append(OperacaoCMPA(
            data=data,
            quantidade=self.quantidade_atual,
            preco_medio=nova_cmpa,
            custo_total=self.custo_total_acumulado,
            descricao=desc
        ))
    
    def adicionar_bonificacao(
        self,
        data: date,
        quantidade_bonus: Decimal,
        preco_unitario_bonus: Decimal = Decimal('0'),
        descricao: str = ""
    ) -> None:
        """
        Adiciona uma bonificação.
        
        A bonificação aumenta a quantidade e adiciona ao custo de aquisição.
        O CMPA é recalculado.
        """
        valor_bonus = quantidade_bonus * preco_unitario_bonus
        
        # Aumenta quantidade
        quantidade_anterior = self.quantidade_atual
        self.quantidade_atual += quantidade_bonus
        
        # Adiciona ao custo total
        self.custo_total_acumulado += valor_bonus
        
        # Recalcula CMPA
        cmpa_novo = self._calcular_cmpa()
        cmpa_anterior = self._calcular_cmpa_anterior(quantidade_anterior)
        
        desc = (
            descricao or 
            f"Bonificação: +{quantidade_bonus} unidades. "
            f"Quantidade anterior: {quantidade_anterior}, nova: {self.quantidade_atual}. "
            f"CMPA antes: R$ {cmpa_anterior:.4f}, depois: R$ {cmpa_novo:.4f}. "
            f"Custo aquisição mantido: R$ {self.custo_total_acumulado:.2f}"
        )
        
        self.historico.append(OperacaoCMPA(
            data=data,
            quantidade=self.quantidade_atual,
            preco_medio=cmpa_novo,
            custo_total=self.custo_total_acumulado,
            descricao=desc
        ))
    
    def adicionar_desdobramento(
        self,
        data: date,
        taxa: Decimal,
        descricao: str = ""
    ) -> None:
        """
        Desdobramento (split): multiplica quantidade, divide preço.
        Ex: Split 2:1 → taxa = 2, quantidade multiplica por 2
        
        O custo de aquisição NÃO muda.
        """
        quantidade_anterior = self.quantidade_atual
        self.quantidade_atual = self.quantidade_atual * taxa
        
        cmpa_novo = self._calcular_cmpa()
        cmpa_anterior = self._calcular_cmpa_anterior(quantidade_anterior)
        
        desc = (
            descricao or
            f"Desdobramento {taxa}:1. "
            f"Quantidade: {quantidade_anterior} → {self.quantidade_atual}. "
            f"CMPA: R$ {cmpa_anterior:.4f} → R$ {cmpa_novo:.4f}. "
            f"Custo aquisição: R$ {self.custo_total_acumulado:.2f}"
        )
        
        self.historico.append(OperacaoCMPA(
            data=data,
            quantidade=self.quantidade_atual,
            preco_medio=cmpa_novo,
            custo_total=self.custo_total_acumulado,
            descricao=desc
        ))
    
    def adicionar_agrupamento(
        self,
        data: date,
        taxa: Decimal,
        descricao: str = ""
    ) -> None:
        """
        Agrupamento (reverse split): divide quantidade, multiplica preço.
        Ex: Agrupamento 2:1 → taxa = 2, quantidade divide por 2
        
        O custo de aquisição NÃO muda.
        """
        quantidade_anterior = self.quantidade_atual
        self.quantidade_atual = self.quantidade_atual / taxa
        
        cmpa_novo = self._calcular_cmpa()
        cmpa_anterior = self._calcular_cmpa_anterior(quantidade_anterior)
        
        desc = (
            descricao or
            f"Agrupamento 1:{taxa}. "
            f"Quantidade: {quantidade_anterior} → {self.quantidade_atual}. "
            f"CMPA: R$ {cmpa_anterior:.4f} → R$ {cmpa_novo:.4f}. "
            f"Custo aquisição: R$ {self.custo_total_acumulado:.2f}"
        )
        
        self.historico.append(OperacaoCMPA(
            data=data,
            quantidade=self.quantidade_atual,
            preco_medio=cmpa_novo,
            custo_total=self.custo_total_acumulado,
            descricao=desc
        ))
    
    def _calcular_cmpa(self) -> Decimal:
        """Calcula CMPA atual"""
        if self.quantidade_atual == 0:
            return Decimal('0')
        return self.custo_total_acumulado / self.quantidade_atual
    
    def _calcular_cmpa_anterior(self, quantidade_anterior: Decimal) -> Decimal:
        """Calcula CMPA baseado em quantidade anterior"""
        if quantidade_anterior == 0:
            return Decimal('0')
        return self.custo_total_acumulado / quantidade_anterior
    
    def calcular_venda(
        self,
        data: date,
        quantidade_vendida: Decimal,
        preco_venda_unitario: Decimal,
        custos_operacionais: Decimal = Decimal('0')
    ) -> Dict[str, Any]:
        """
        Calcula resultado de uma venda.
        
        Retorna:
            {
                'quantidade_vendida': Decimal,
                'preco_venda': Decimal,
                'valor_venda_bruto': Decimal,
                'custos_operacionais': Decimal,
                'valor_venda_liquido': Decimal,
                'cmpa_na_venda': Decimal,
                'custo_adquisicao_vendido': Decimal,
                'lucro_bruto': Decimal,
                'lucro_liquido': Decimal,
                'percentual_ganho': Decimal,
            }
        """
        
        cmpa_na_venda = self._calcular_cmpa()
        valor_venda_bruto = quantidade_vendida * preco_venda_unitario
        custo_aquisicao_vendido = quantidade_vendida * cmpa_na_venda
        
        lucro_bruto = valor_venda_bruto - custo_aquisicao_vendido
        lucro_liquido = lucro_bruto - custos_operacionais
        
        percentual = (lucro_liquido / custo_aquisicao_vendido * 100) if custo_aquisicao_vendido != 0 else Decimal('0')
        
        # Reduz quantidade e custo total
        self.quantidade_atual -= quantidade_vendida
        self.custo_total_acumulado -= custo_aquisicao_vendido
        
        return {
            'quantidade_vendida': quantidade_vendida,
            'preco_venda': preco_venda_unitario,
            'valor_venda_bruto': valor_venda_bruto.quantize(Decimal('0.01')),
            'custos_operacionais': custos_operacionais.quantize(Decimal('0.01')),
            'valor_venda_liquido': (valor_venda_bruto - custos_operacionais).quantize(Decimal('0.01')),
            'cmpa_na_venda': cmpa_na_venda.quantize(Decimal('0.0001')),
            'custo_aquisicao_vendido': custo_aquisicao_vendido.quantize(Decimal('0.01')),
            'lucro_bruto': lucro_bruto.quantize(Decimal('0.01')),
            'lucro_liquido': lucro_liquido.quantize(Decimal('0.01')),
            'percentual_ganho': percentual.quantize(Decimal('0.01')),
            'quantidade_restante': self.quantidade_atual,
            'custo_total_restante': self.custo_total_acumulado.quantize(Decimal('0.01')),
            'cmpa_restante': self._calcular_cmpa().quantize(Decimal('0.0001')),
        }
    
    def obter_estado_atual(self) -> Dict[str, Any]:
        """Retorna estado atual do ativo"""
        return {
            'quantidade': self.quantidade_atual,
            'cmpa': self._calcular_cmpa().quantize(Decimal('0.0001')),
            'custo_total': self.custo_total_acumulado.quantize(Decimal('0.01')),
            'historico_movimentos': [
                {
                    'data': h.data.isoformat(),
                    'quantidade': h.quantidade,
                    'cmpa': h.preco_medio.quantize(Decimal('0.0001')),
                    'custo_total': h.custo_total.quantize(Decimal('0.01')),
                    'descricao': h.descricao
                }
                for h in self.historico
            ]
        }
