"""
Cliente HTTP assíncrono para API Spring Boot
"""

from dataclasses import dataclass
from typing import Optional, List, Dict, Any

import httpx

from app.config import get_settings


@dataclass
class PrecoComposicao:
    """Preço de uma composição SINAPI"""
    codigo_composicao: str
    custo_sem_desoneracao: float
    custo_com_desoneracao: float


@dataclass
class ItemOrcamento:
    """Item de um orçamento"""
    codigo: int
    nome: str
    descricao: str
    quantidade: float
    unidade: str
    custo_unitario: float = 0.0


@dataclass
class EtapaOrcamento:
    """Etapa de um orçamento"""
    codigo: int
    nome: str
    descricao: str
    itens: List[ItemOrcamento]


class SpringAPIClient:
    """Cliente para API Spring Boot do Obradoria"""

    def __init__(self):
        self.settings = get_settings()
        self.base_url = self.settings.spring_api_url
        self.timeout = self.settings.spring_api_timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(self.timeout)
            )
        return self._client

    async def close(self) -> None:
        """Fecha conexão"""
        if self._client:
            await self._client.aclose()
            self._client = None

    # =========================================================================
    # ORÇAMENTO BASE
    # =========================================================================

    async def buscar_orcamento_base(self, padrao: str) -> Optional[Dict[str, Any]]:
        """
        Busca orçamento base pelo padrão construtivo

        Args:
            padrao: MINIMO ou BASICO

        Returns:
            Dict com dados do orçamento ou None
        """
        client = await self._get_client()

        try:
            response = await client.get(f"/orcamentos/base/{padrao}")
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError:
            return None

    async def buscar_etapas_por_orcamento(
        self,
        codigo_orcamento: int
    ) -> List[EtapaOrcamento]:
        """
        Busca etapas e itens de um orçamento

        Args:
            codigo_orcamento: Código do orçamento

        Returns:
            Lista de etapas com seus itens
        """
        client = await self._get_client()

        response = await client.get(
            "/etapas-orcamento",
            params={"codigoOrcamento": codigo_orcamento}
        )
        response.raise_for_status()

        etapas_data = response.json()
        etapas = []

        for etapa_data in etapas_data:
            itens = []
            for item_data in etapa_data.get('itens', []):
                itens.append(ItemOrcamento(
                    codigo=item_data.get('codigo', 0),
                    nome=item_data.get('nome', ''),
                    descricao=item_data.get('descricao', ''),
                    quantidade=float(item_data.get('quantidade', 0)),
                    unidade=item_data.get('unidade', ''),
                    custo_unitario=float(item_data.get('custoUnitario', 0))
                ))

            etapas.append(EtapaOrcamento(
                codigo=etapa_data.get('codigo', 0),
                nome=etapa_data.get('nome', ''),
                descricao=etapa_data.get('descricao', ''),
                itens=itens
            ))

        return etapas

    # =========================================================================
    # PREÇOS SINAPI
    # =========================================================================

    async def buscar_preco_composicao(
        self,
        codigo_composicao: str,
        uf: str,
        mes: int,
        ano: int
    ) -> Optional[PrecoComposicao]:
        """
        Busca preço de uma composição SINAPI

        Args:
            codigo_composicao: Código SINAPI
            uf: Sigla do estado
            mes: Mês de referência
            ano: Ano de referência

        Returns:
            PrecoComposicao ou None se não encontrado
        """
        client = await self._get_client()

        try:
            response = await client.get(
                "/preco-composicoes/buscar",
                params={
                    "codigoComposicao": codigo_composicao,
                    "uf": uf,
                    "mes": mes,
                    "ano": ano
                }
            )
            response.raise_for_status()
            data = response.json()

            return PrecoComposicao(
                codigo_composicao=str(data.get('codigoComposicao', '')),
                custo_sem_desoneracao=float(data.get('custoSemDesoneracao', 0)),
                custo_com_desoneracao=float(data.get('custoComDesoneracao', 0))
            )
        except httpx.HTTPStatusError:
            return None

    # =========================================================================
    # CRIAÇÃO DE ORÇAMENTO
    # =========================================================================

    async def criar_obra(self, nome: str, descricao: str) -> Optional[Dict[str, Any]]:
        """Cria uma nova obra"""
        client = await self._get_client()

        try:
            response = await client.post(
                "/obras",
                json={"nome": nome, "descricao": descricao}
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError:
            return None

    async def criar_orcamento(
        self,
        nome: str,
        descricao: str,
        codigo_obra: Optional[int] = None,
        percentual_bdi: float = 0,
        percentual_desconto: float = 0
    ) -> Optional[Dict[str, Any]]:
        """Cria um novo orçamento"""
        client = await self._get_client()

        payload = {
            "nome": nome,
            "descricao": descricao,
            "percentualBdi": percentual_bdi,
            "percentualDesconto": percentual_desconto
        }

        if codigo_obra:
            payload["codigoObra"] = codigo_obra

        try:
            response = await client.post("/orcamentos", json=payload)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError:
            return None

    async def criar_etapa_orcamento(
        self,
        codigo_orcamento: int,
        nome: str,
        descricao: str
    ) -> Optional[Dict[str, Any]]:
        """Cria uma nova etapa no orçamento"""
        client = await self._get_client()

        payload = {
            "codigoOrcamento": codigo_orcamento,
            "nome": nome,
            "descricao": descricao
        }

        try:
            response = await client.post("/etapas-orcamento", json=payload)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError:
            return None

    async def adicionar_itens_etapa(
        self,
        codigo_etapa: int,
        itens: List[Dict[str, Any]]
    ) -> bool:
        """
        Adiciona itens a uma etapa

        Args:
            codigo_etapa: Código da etapa
            itens: Lista de itens no formato da API

        Returns:
            True se sucesso, False se falhou
        """
        client = await self._get_client()

        try:
            response = await client.post(
                f"/etapas-orcamento/{codigo_etapa}/itens",
                json=itens
            )
            response.raise_for_status()
            return True
        except httpx.HTTPStatusError:
            return False


# Singleton
_spring_client: Optional[SpringAPIClient] = None


def get_spring_client() -> SpringAPIClient:
    """Retorna instância singleton do cliente Spring"""
    global _spring_client
    if _spring_client is None:
        _spring_client = SpringAPIClient()
    return _spring_client


async def close_spring_client() -> None:
    """Fecha o cliente Spring"""
    global _spring_client
    if _spring_client:
        await _spring_client.close()
        _spring_client = None
