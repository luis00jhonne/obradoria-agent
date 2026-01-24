"""
Orquestrador do fluxo de geração de orçamentos
"""

import asyncio
import time
from typing import AsyncGenerator, Optional, List, Dict, Any

from app.llm import LLMProvider, get_llm_provider
from app.services.vector_search import get_vector_search_service
from app.services.spring_client import get_spring_client
from app.core.extractor import extrair_informacoes
from app.core.models import (
    EventoStream,
    DadosExtraidos,
    ItemBase,
    ItemProcessado,
    EtapaProcessada,
    ResultadoOrcamento,
    Estatisticas,
    NivelConfianca
)


class BudgetOrchestrator:
    """
    Orquestrador simples para geração de orçamentos.
    Emite eventos SSE para feedback em tempo real.
    """

    def __init__(self, provider_name: Optional[str] = None):
        """
        Inicializa o orquestrador

        Args:
            provider_name: Nome do provider LLM (ollama, openai, anthropic)
        """
        self.llm = get_llm_provider(provider_name)
        self.provider_name = self.llm.name

    async def process_stream(
        self,
        texto_usuario: str,
        nome_obra: Optional[str] = None
    ) -> AsyncGenerator[EventoStream, None]:
        """
        Processa pedido e emite eventos SSE por etapa

        Args:
            texto_usuario: Texto do usuário em linguagem natural
            nome_obra: Nome da obra (opcional)

        Yields:
            EventoStream para cada etapa do processamento
        """
        inicio = time.time()
        resultado = ResultadoOrcamento(sucesso=False)

        # =====================================================================
        # ETAPA 1: Extração
        # =====================================================================
        yield EventoStream(
            etapa="extraction",
            mensagem="Extraindo informações do pedido...",
            progresso=0.1
        )

        extracao = await extrair_informacoes(texto_usuario, self.llm)

        if not extracao.sucesso:
            yield EventoStream(
                etapa="error",
                mensagem=f"Erro na extração: {', '.join(extracao.erros)}",
                dados={"erros": extracao.erros}
            )
            return

        dados = extracao.dados
        resultado.dados_extraidos = dados
        resultado.avisos = extracao.avisos

        yield EventoStream(
            etapa="extraction_done",
            mensagem=f"Extraído: {dados.quantidade}x {dados.tipo_construtivo} {dados.padrao_construtivo} em {dados.uf}",
            progresso=0.2,
            dados={
                "quantidade": dados.quantidade,
                "tipo": dados.tipo_construtivo,
                "padrao": dados.padrao_construtivo,
                "uf": dados.uf,
                "mes": dados.mes_referencia,
                "ano": dados.ano_referencia
            }
        )

        # =====================================================================
        # ETAPA 2: Carregar orçamento base
        # =====================================================================
        yield EventoStream(
            etapa="load_base",
            mensagem=f"Carregando orçamento base '{dados.padrao_construtivo}'...",
            progresso=0.25
        )

        spring_client = get_spring_client()

        orcamento_base = await spring_client.buscar_orcamento_base(dados.padrao_construtivo)

        if not orcamento_base:
            yield EventoStream(
                etapa="error",
                mensagem=f"Orçamento base '{dados.padrao_construtivo}' não encontrado"
            )
            return

        etapas_base = await spring_client.buscar_etapas_por_orcamento(
            orcamento_base['codigo']
        )

        # Preparar lista de itens para processar
        itens_para_processar = []
        for etapa in etapas_base:
            for item in etapa.itens:
                itens_para_processar.append({
                    "etapa_nome": etapa.nome,
                    "etapa_codigo": etapa.codigo,
                    "item": item
                })

        total_itens = len(itens_para_processar)

        yield EventoStream(
            etapa="load_base_done",
            mensagem=f"Carregado: {len(etapas_base)} etapas, {total_itens} itens",
            progresso=0.3,
            dados={
                "orcamento_base": orcamento_base['nome'],
                "total_etapas": len(etapas_base),
                "total_itens": total_itens
            }
        )

        # =====================================================================
        # ETAPA 3: Busca SINAPI (paralelo)
        # =====================================================================
        yield EventoStream(
            etapa="search",
            mensagem=f"Buscando composições SINAPI para {total_itens} itens...",
            progresso=0.4
        )

        vector_service = await get_vector_search_service()

        # Buscar em paralelo
        async def buscar_item(item_info: dict):
            item = item_info["item"]
            texto_busca = item.descricao or item.nome
            busca = await vector_service.buscar_com_confianca(texto_busca)
            return {
                "item_info": item_info,
                "busca": busca
            }

        resultados_busca = await asyncio.gather(
            *[buscar_item(item_info) for item_info in itens_para_processar]
        )

        yield EventoStream(
            etapa="search_done",
            mensagem=f"Busca SINAPI concluída",
            progresso=0.6
        )

        # =====================================================================
        # ETAPA 4: Buscar preços (paralelo)
        # =====================================================================
        yield EventoStream(
            etapa="pricing",
            mensagem="Calculando preços...",
            progresso=0.65
        )

        # Coletar códigos únicos para buscar preços
        codigos_para_buscar = set()
        for r in resultados_busca:
            if r["busca"].melhor_match:
                codigos_para_buscar.add(r["busca"].melhor_match.codigo)

        # Buscar preços em paralelo
        async def buscar_preco(codigo: str):
            preco = await spring_client.buscar_preco_composicao(
                codigo,
                dados.uf,
                dados.mes_referencia,
                dados.ano_referencia
            )
            return codigo, preco

        precos_resultado = await asyncio.gather(
            *[buscar_preco(codigo) for codigo in codigos_para_buscar]
        )

        # Mapear preços
        precos_map = {codigo: preco for codigo, preco in precos_resultado}

        yield EventoStream(
            etapa="pricing_done",
            mensagem=f"Preços encontrados: {len([p for p in precos_map.values() if p])}/{len(codigos_para_buscar)}",
            progresso=0.8
        )

        # =====================================================================
        # ETAPA 5: Montar resultado
        # =====================================================================
        yield EventoStream(
            etapa="synthesize",
            mensagem="Montando orçamento...",
            progresso=0.85
        )

        # Processar e agrupar por etapa
        etapas_dict: Dict[str, EtapaProcessada] = {}
        estatisticas = Estatisticas()

        for r in resultados_busca:
            item_info = r["item_info"]
            busca = r["busca"]
            item = item_info["item"]
            etapa_nome = item_info["etapa_nome"]

            estatisticas.total_itens += 1

            # Contabilizar confiança
            if busca.nivel_confianca == NivelConfianca.ALTA:
                estatisticas.alta_confianca += 1
            elif busca.nivel_confianca == NivelConfianca.MEDIA:
                estatisticas.media_confianca += 1
            else:
                estatisticas.baixa_confianca += 1

            # Calcular preço
            preco_unitario = 0.0
            preco_total = 0.0
            problema = None

            if busca.melhor_match:
                codigo_sinapi = busca.melhor_match.codigo
                preco_info = precos_map.get(codigo_sinapi)

                if preco_info:
                    preco_unitario = preco_info.custo_sem_desoneracao or preco_info.custo_com_desoneracao
                    estatisticas.itens_com_preco += 1
                else:
                    estatisticas.itens_sem_preco += 1
                    problema = "Preço não encontrado para UF/data"
            else:
                estatisticas.itens_sem_composicao += 1
                problema = "Composição SINAPI não encontrada"

            # Calcular quantidade ajustada
            quantidade_ajustada = item.quantidade * dados.quantidade
            preco_total = preco_unitario * quantidade_ajustada

            # Criar item processado
            item_processado = ItemProcessado(
                item_base=ItemBase(
                    codigo=item.codigo,
                    nome=item.nome,
                    descricao=item.descricao,
                    quantidade=item.quantidade,
                    unidade=item.unidade
                ),
                etapa_nome=etapa_nome,
                busca_sinapi=busca,
                quantidade_ajustada=quantidade_ajustada,
                preco_unitario=preco_unitario,
                preco_total=preco_total,
                problema=problema
            )

            # Agrupar por etapa
            if etapa_nome not in etapas_dict:
                etapas_dict[etapa_nome] = EtapaProcessada(
                    codigo=item_info["etapa_codigo"],
                    nome=etapa_nome,
                    descricao="",
                    itens=[],
                    valor_total=0.0
                )

            etapas_dict[etapa_nome].itens.append(item_processado)
            etapas_dict[etapa_nome].valor_total += preco_total

        # Calcular valor total
        valor_total = sum(e.valor_total for e in etapas_dict.values())

        resultado.sucesso = True
        resultado.etapas = list(etapas_dict.values())
        resultado.estatisticas = estatisticas
        resultado.valor_total = valor_total
        resultado.tempo_processamento = time.time() - inicio

        yield EventoStream(
            etapa="synthesize_done",
            mensagem=f"Orçamento calculado: R$ {valor_total:,.2f}",
            progresso=0.9,
            dados={
                "valor_total": valor_total,
                "total_etapas": len(etapas_dict),
                "taxa_sucesso": estatisticas.taxa_sucesso
            }
        )

        # =====================================================================
        # ETAPA 6: Persistir (opcional)
        # =====================================================================
        if nome_obra:
            yield EventoStream(
                etapa="persist",
                mensagem="Salvando orçamento...",
                progresso=0.92
            )

            try:
                orcamento_criado = await self._persistir_orcamento(
                    resultado, nome_obra, dados
                )
                if orcamento_criado:
                    resultado.codigo_orcamento_criado = orcamento_criado.get('codigo')
                    resultado.codigo_obra_criada = orcamento_criado.get('codigo_obra')

                yield EventoStream(
                    etapa="persist_done",
                    mensagem="Orçamento salvo com sucesso",
                    progresso=0.98
                )
            except Exception as e:
                yield EventoStream(
                    etapa="persist_error",
                    mensagem=f"Erro ao salvar: {str(e)}",
                    progresso=0.98
                )

        # =====================================================================
        # COMPLETO
        # =====================================================================
        yield EventoStream(
            etapa="complete",
            mensagem=f"Processamento concluído em {resultado.tempo_processamento:.1f}s",
            progresso=1.0,
            dados=self._resultado_to_dict(resultado)
        )

    async def _persistir_orcamento(
        self,
        resultado: ResultadoOrcamento,
        nome_obra: str,
        dados: DadosExtraidos
    ) -> Optional[Dict[str, Any]]:
        """Persiste o orçamento na API Spring"""
        spring_client = get_spring_client()

        # 1. Criar obra
        descricao_obra = (
            f"Obra gerada automaticamente - "
            f"{dados.tipo_construtivo} {dados.padrao_construtivo}"
        )
        obra = await spring_client.criar_obra(nome_obra, descricao_obra)

        codigo_obra = obra['codigo'] if obra else None

        # 2. Criar orçamento
        nome_orcamento = (
            f"Orçamento {dados.tipo_construtivo} - {dados.padrao_construtivo} - "
            f"{dados.uf} - {dados.mes_referencia:02d}/{dados.ano_referencia}"
        )
        descricao_orcamento = (
            f"Orçamento gerado automaticamente via IA\n"
            f"Quantidade: {dados.quantidade} unidades\n"
            f"Taxa de sucesso: {resultado.estatisticas.taxa_sucesso:.1f}%"
        )

        orcamento = await spring_client.criar_orcamento(
            nome=nome_orcamento,
            descricao=descricao_orcamento,
            codigo_obra=codigo_obra
        )

        if not orcamento:
            return None

        codigo_orcamento = orcamento['codigo']

        # 3. Criar etapas e itens
        for etapa in resultado.etapas:
            etapa_criada = await spring_client.criar_etapa_orcamento(
                codigo_orcamento=codigo_orcamento,
                nome=etapa.nome,
                descricao=f"Etapa gerada - {len(etapa.itens)} itens"
            )

            if etapa_criada:
                # Preparar itens
                itens_payload = []
                for item in etapa.itens:
                    item_api = {
                        "nome": item.item_base.nome,
                        "descricao": item.item_base.descricao,
                        "quantidade": item.quantidade_ajustada,
                        "custoUnitario": item.preco_unitario
                    }
                    if item.busca_sinapi.melhor_match:
                        item_api["codigoComposicao"] = int(
                            item.busca_sinapi.melhor_match.codigo
                        )
                    itens_payload.append(item_api)

                await spring_client.adicionar_itens_etapa(
                    etapa_criada['codigo'],
                    itens_payload
                )

        return {
            "codigo": codigo_orcamento,
            "codigo_obra": codigo_obra
        }

    def _resultado_to_dict(self, resultado: ResultadoOrcamento) -> dict:
        """Converte resultado para dicionário serializável"""
        etapas_dict = []
        for etapa in resultado.etapas:
            itens_dict = []
            for item in etapa.itens:
                item_dict = {
                    "nome": item.item_base.nome,
                    "descricao": item.item_base.descricao,
                    "quantidade": item.quantidade_ajustada,
                    "unidade": item.item_base.unidade,
                    "preco_unitario": item.preco_unitario,
                    "preco_total": item.preco_total,
                    "nivel_confianca": item.busca_sinapi.nivel_confianca.value,
                    "problema": item.problema
                }
                if item.busca_sinapi.melhor_match:
                    item_dict["codigo_sinapi"] = item.busca_sinapi.melhor_match.codigo
                    item_dict["descricao_sinapi"] = item.busca_sinapi.melhor_match.nome
                    item_dict["similaridade"] = item.busca_sinapi.melhor_match.similaridade
                itens_dict.append(item_dict)

            etapas_dict.append({
                "nome": etapa.nome,
                "itens": itens_dict,
                "valor_total": etapa.valor_total
            })

        dados_extraidos = None
        if resultado.dados_extraidos:
            dados_extraidos = {
                "quantidade": resultado.dados_extraidos.quantidade,
                "tipo_construtivo": resultado.dados_extraidos.tipo_construtivo,
                "padrao_construtivo": resultado.dados_extraidos.padrao_construtivo,
                "uf": resultado.dados_extraidos.uf,
                "mes_referencia": resultado.dados_extraidos.mes_referencia,
                "ano_referencia": resultado.dados_extraidos.ano_referencia
            }

        return {
            "sucesso": resultado.sucesso,
            "dados_extraidos": dados_extraidos,
            "etapas": etapas_dict,
            "valor_total": resultado.valor_total,
            "estatisticas": {
                "total_itens": resultado.estatisticas.total_itens,
                "itens_com_preco": resultado.estatisticas.itens_com_preco,
                "itens_sem_composicao": resultado.estatisticas.itens_sem_composicao,
                "itens_sem_preco": resultado.estatisticas.itens_sem_preco,
                "alta_confianca": resultado.estatisticas.alta_confianca,
                "media_confianca": resultado.estatisticas.media_confianca,
                "baixa_confianca": resultado.estatisticas.baixa_confianca,
                "taxa_sucesso": resultado.estatisticas.taxa_sucesso
            },
            "avisos": resultado.avisos,
            "codigo_orcamento_criado": resultado.codigo_orcamento_criado,
            "codigo_obra_criada": resultado.codigo_obra_criada,
            "tempo_processamento": resultado.tempo_processamento
        }
