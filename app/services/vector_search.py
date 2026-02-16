"""
Serviço de busca vetorial com pgvector
"""

import asyncio
from typing import Optional, List
import asyncpg
from sentence_transformers import SentenceTransformer

from app.config import get_settings
from app.core.models import (
    ComposicaoSinapi,
    ResultadoBusca,
    NivelConfianca
)


class VectorSearchService:
    """Serviço de busca semântica usando pgvector"""

    def __init__(self):
        self.settings = get_settings()
        self._pool: Optional[asyncpg.Pool] = None
        self._model: Optional[SentenceTransformer] = None

    async def initialize(self) -> None:
        """Inicializa pool de conexões e modelo de embeddings"""
        if self._pool is None:
            self._pool = await asyncpg.create_pool(
                host=self.settings.db_host,
                port=self.settings.db_port,
                database=self.settings.db_name,
                user=self.settings.db_user,
                password=self.settings.db_password,
                min_size=2,
                max_size=10
            )

        if self._model is None:
            self._model = SentenceTransformer(self.settings.embedding_model)
            # Tentar usar GPU se disponível
            import torch
            if torch.cuda.is_available():
                self._model = self._model.to('cuda')

    async def close(self) -> None:
        """Fecha conexões"""
        if self._pool:
            await self._pool.close()
            self._pool = None

    async def health_check(self) -> bool:
        """Verifica se o banco de dados está acessível"""
        if self._pool is None:
            return False
        try:
            async with self._pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            return True
        except Exception:
            return False

    def _gerar_embedding(self, texto: str) -> List[float]:
        """Gera embedding para um texto"""
        if self._model is None:
            raise RuntimeError("Modelo não inicializado. Chame initialize() primeiro.")
        embedding = self._model.encode(texto, convert_to_numpy=True)
        return embedding.tolist()

    def _classificar_confianca(self, similaridade: float) -> NivelConfianca:
        """Classifica nível de confiança baseado na similaridade"""
        if similaridade >= self.settings.limite_alta_confianca:
            return NivelConfianca.ALTA
        elif similaridade >= self.settings.limite_media_confianca:
            return NivelConfianca.MEDIA
        else:
            return NivelConfianca.BAIXA

    async def buscar_composicoes(
        self,
        texto_busca: str,
        top_k: int = 5,
        limite_similaridade: Optional[float] = None
    ) -> List[ComposicaoSinapi]:
        """
        Busca composições SINAPI por similaridade semântica

        Args:
            texto_busca: Texto para buscar
            top_k: Quantidade de resultados
            limite_similaridade: Similaridade mínima

        Returns:
            Lista de composições ordenadas por similaridade
        """
        if self._pool is None:
            await self.initialize()

        if limite_similaridade is None:
            limite_similaridade = self.settings.limite_minimo_busca

        # Gerar embedding em thread para nao bloquear o event loop
        embedding = await asyncio.to_thread(self._gerar_embedding, texto_busca)
        embedding_str = '[' + ','.join(map(str, embedding)) + ']'

        query = """
            SELECT
                c.codigo,
                c.nome,
                c.descricao,
                c.unidade_medida,
                1 - (ce.embedding <=> $1::vector) AS similaridade
            FROM composicao_embeddings ce
            JOIN composicao c ON ce.codigo_composicao = c.codigo
            WHERE 1 - (ce.embedding <=> $1::vector) >= $2
            ORDER BY ce.embedding <=> $1::vector
            LIMIT $3
        """

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, embedding_str, limite_similaridade, top_k)

        resultados = []
        for row in rows:
            similaridade = float(row['similaridade'] or 0)
            resultados.append(ComposicaoSinapi(
                codigo=str(row['codigo']),
                nome=row['nome'],
                descricao=row['descricao'] or '',
                unidade_medida=row['unidade_medida'] or '',
                similaridade=similaridade,
                nivel_confianca=self._classificar_confianca(similaridade)
            ))

        return resultados

    async def buscar_com_confianca(self, texto_busca: str) -> ResultadoBusca:
        """
        Busca composição e retorna resultado classificado por confiança

        Sistema de três níveis:
        - ALTA (>= 75%): Aceita automaticamente
        - MÉDIA (60-75%): Retorna top 3 para análise
        - BAIXA (< 60%): Indica que não encontrou match confiável

        Args:
            texto_busca: Texto para buscar

        Returns:
            ResultadoBusca com classificação de confiança
        """
        resultados = await self.buscar_composicoes(
            texto_busca,
            top_k=3,
            limite_similaridade=self.settings.limite_minimo_busca
        )

        if not resultados:
            return ResultadoBusca(
                nivel_confianca=NivelConfianca.BAIXA,
                melhor_match=None,
                alternativas=[],
                requer_validacao=True,
                mensagem='Nenhuma composição similar encontrada'
            )

        melhor = resultados[0]
        alternativas = resultados[1:] if len(resultados) > 1 else []

        if melhor.nivel_confianca == NivelConfianca.ALTA:
            return ResultadoBusca(
                nivel_confianca=NivelConfianca.ALTA,
                melhor_match=melhor,
                alternativas=alternativas,
                requer_validacao=False,
                mensagem=f'Match encontrado com {melhor.similaridade:.1%} de confiança'
            )

        elif melhor.nivel_confianca == NivelConfianca.MEDIA:
            return ResultadoBusca(
                nivel_confianca=NivelConfianca.MEDIA,
                melhor_match=melhor,
                alternativas=alternativas,
                requer_validacao=True,
                mensagem=f'Match com {melhor.similaridade:.1%} - Validação recomendada'
            )

        else:
            return ResultadoBusca(
                nivel_confianca=NivelConfianca.BAIXA,
                melhor_match=melhor,
                alternativas=alternativas,
                requer_validacao=True,
                mensagem=f'Similaridade baixa ({melhor.similaridade:.1%}) - Validação necessária'
            )


# Singleton
_vector_search_service: Optional[VectorSearchService] = None


async def get_vector_search_service() -> VectorSearchService:
    """Retorna instância singleton do serviço de busca vetorial"""
    global _vector_search_service
    if _vector_search_service is None:
        _vector_search_service = VectorSearchService()
        await _vector_search_service.initialize()
    return _vector_search_service


async def close_vector_search_service() -> None:
    """Fecha o serviço de busca vetorial"""
    global _vector_search_service
    if _vector_search_service:
        await _vector_search_service.close()
        _vector_search_service = None


async def check_database_connection() -> bool:
    """
    Verifica conectividade com o banco de dados sem inicializar o serviço completo.
    Se o serviço já estiver inicializado, usa o pool existente.
    Caso contrário, faz uma conexão direta rápida.
    """
    if _vector_search_service and _vector_search_service._pool:
        return await _vector_search_service.health_check()

    settings = get_settings()
    try:
        conn = await asyncpg.connect(
            host=settings.db_host,
            port=settings.db_port,
            database=settings.db_name,
            user=settings.db_user,
            password=settings.db_password,
            timeout=5
        )
        await conn.fetchval("SELECT 1")
        await conn.close()
        return True
    except Exception:
        return False
