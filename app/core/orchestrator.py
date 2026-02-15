"""
Orquestrador do fluxo de geração de orçamentos
"""

import asyncio
import time
import logging
from typing import AsyncGenerator, Optional, List, Dict, Any

logger = logging.getLogger(__name__)

from app.llm import LLMProvider, get_llm_provider
from app.services.vector_search import get_vector_search_service
from app.services.spring_client import get_spring_client
from app.core.extractor import (
    extrair_informacoes,
    extrair_informacoes_inteligente,
    construir_dados_extraidos
)
from app.core.budget_generator import gerar_estrutura_orcamento
from app.core.conversation import (
    get_conversation_manager,
    ConversationManager,
    PERGUNTAS_CAMPOS
)
from app.core.models import (
    EventoStream,
    DadosExtraidos,
    ItemBase,
    ItemProcessado,
    EtapaProcessada,
    ResultadoOrcamento,
    Estatisticas,
    NivelConfianca,
    TipoEventoConversacao,
    FaseConversacao,
    FonteCampo,
    CampoInfo
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
        # ETAPA 2: Carregar estrutura do orçamento (API ou LLM)
        # =====================================================================
        yield EventoStream(
            etapa="load_base",
            mensagem=f"Buscando estrutura de orçamento para '{dados.padrao_construtivo}'...",
            progresso=0.25
        )

        spring_client = get_spring_client()
        fonte_estrutura = "api"  # Rastrear origem da estrutura
        itens_para_processar = []

        # Tentar buscar da API Spring primeiro
        orcamento_base = await spring_client.buscar_orcamento_base(dados.padrao_construtivo)

        if orcamento_base:
            # Usar estrutura da API
            etapas_base = await spring_client.buscar_etapas_por_orcamento(
                orcamento_base['codigo']
            )

            for etapa in etapas_base:
                for item in etapa.itens:
                    itens_para_processar.append({
                        "etapa_nome": etapa.nome,
                        "etapa_codigo": etapa.codigo,
                        "item": item
                    })

            nome_base = orcamento_base['nome']
            total_etapas = len(etapas_base)

        else:
            # Fallback: Gerar estrutura via LLM com Chain-of-Thought
            yield EventoStream(
                etapa="generate_structure",
                mensagem="Orçamento base não encontrado. Gerando estrutura via IA...",
                progresso=0.27
            )

            estrutura = await gerar_estrutura_orcamento(
                dados=dados,
                llm_provider=self.llm,
                usar_cot=True
            )

            if not estrutura.sucesso:
                yield EventoStream(
                    etapa="error",
                    mensagem=f"Erro ao gerar estrutura: {estrutura.erro}"
                )
                return

            # Log do raciocínio CoT (para debug)
            if estrutura.raciocinio:
                resultado.avisos.append(
                    f"Estrutura gerada via IA (Chain-of-Thought)"
                )

            # Converter estrutura gerada para formato processável
            fonte_estrutura = "llm"
            codigo_etapa = 1

            for etapa in estrutura.etapas:
                for item in etapa.itens:
                    # Criar ItemOrcamento compatível
                    item_obj = type('ItemOrcamento', (), {
                        'codigo': 0,
                        'nome': item.nome,
                        'descricao': item.descricao,
                        'quantidade': item.quantidade,
                        'unidade': item.unidade,
                        'custo_unitario': 0.0
                    })()

                    itens_para_processar.append({
                        "etapa_nome": etapa.nome,
                        "etapa_codigo": codigo_etapa,
                        "item": item_obj
                    })

                codigo_etapa += 1

            nome_base = f"Gerado por IA - {dados.padrao_construtivo}"
            total_etapas = len(estrutura.etapas)

        total_itens = len(itens_para_processar)

        if total_itens == 0:
            yield EventoStream(
                etapa="error",
                mensagem="Nenhum item encontrado na estrutura do orçamento"
            )
            return

        yield EventoStream(
            etapa="load_base_done",
            mensagem=f"Estrutura carregada ({fonte_estrutura.upper()}): {total_etapas} etapas, {total_itens} itens",
            progresso=0.3,
            dados={
                "orcamento_base": nome_base,
                "fonte": fonte_estrutura,
                "total_etapas": total_etapas,
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
        resultado.fonte_estrutura = fonte_estrutura

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
            "erros": resultado.erros,
            "avisos": resultado.avisos,
            "codigo_orcamento_criado": resultado.codigo_orcamento_criado,
            "codigo_obra_criada": resultado.codigo_obra_criada,
            "tempo_processamento": resultado.tempo_processamento,
            "fonte_estrutura": resultado.fonte_estrutura
        }


class ConversationalOrchestrator:
    """
    Orquestrador conversacional para geração de orçamentos.

    Implementa fluxo em fases:
    - COLETA: Extrai e coleta informações faltantes
    - CONFIRMACAO: Confirma valores padrão e resumo
    - PROCESSAMENTO: Processa orçamento SINAPI
    """

    def __init__(self, provider_name: Optional[str] = None):
        """
        Inicializa o orquestrador conversacional.

        Args:
            provider_name: Nome do provider LLM (ollama, openai, anthropic)
        """
        self.llm = get_llm_provider(provider_name)
        self.provider_name = self.llm.name
        self.conversation = get_conversation_manager()
        # Orquestrador base para processamento SINAPI
        self._base_orchestrator = BudgetOrchestrator(provider_name)

    async def process_stream(
        self,
        texto_usuario: Optional[str] = None,
        session_id: Optional[str] = None,
        resposta_campo: Optional[Dict[str, Any]] = None,
        confirmacao: Optional[str] = None,
        nome_obra: Optional[str] = None
    ) -> AsyncGenerator[EventoStream, None]:
        """
        Processa pedido de forma conversacional.

        Args:
            texto_usuario: Texto do usuário (mensagem inicial ou vazia)
            session_id: ID da sessão existente (para continuação)
            resposta_campo: Resposta a uma pergunta {"campo": str, "valor": Any}
            confirmacao: Ação de confirmação ("confirmar", "corrigir")
            nome_obra: Nome da obra para persistir

        Yields:
            EventoStream para cada etapa do processamento
        """
        # =====================================================================
        # 1. Criar ou recuperar sessão
        # =====================================================================
        if not session_id:
            session_id = self.conversation.criar_sessao(
                texto_original=texto_usuario or "",
                nome_obra=nome_obra
            )
            yield EventoStream(
                etapa=TipoEventoConversacao.SESSION_CREATED.value,
                mensagem="Sessão criada",
                dados={"session_id": session_id}
            )
        else:
            # Verificar se sessão existe
            sessao = self.conversation.obter_sessao(session_id)
            if sessao is None:
                yield EventoStream(
                    etapa=TipoEventoConversacao.SESSION_EXPIRED.value,
                    mensagem="Sessão expirada ou não encontrada. Por favor, inicie uma nova conversa.",
                    dados={"session_id": session_id}
                )
                return

            yield EventoStream(
                etapa=TipoEventoConversacao.SESSION_RESUMED.value,
                mensagem="Sessão retomada",
                dados={"session_id": session_id, "fase": sessao.fase.value}
            )

        sessao = self.conversation.obter_sessao(session_id)

        # Atualizar nome da obra se fornecido
        if nome_obra and sessao:
            sessao.nome_obra = nome_obra

        # =====================================================================
        # 2. Processar resposta a pergunta (se houver)
        # =====================================================================
        if resposta_campo:
            campo = resposta_campo.get("campo")
            valor = resposta_campo.get("valor")

            if campo and valor is not None:
                # Validar e normalizar valor
                valor_normalizado = self._normalizar_valor_campo(campo, valor)

                if valor_normalizado is not None:
                    self.conversation.atualizar_campo(
                        session_id,
                        campo,
                        valor_normalizado,
                        FonteCampo.USUARIO
                    )
                    yield EventoStream(
                        etapa=TipoEventoConversacao.FIELD_UPDATED.value,
                        mensagem=f"Campo '{campo}' atualizado",
                        dados={
                            "session_id": session_id,
                            "campo": campo,
                            "valor": valor_normalizado
                        }
                    )
                else:
                    yield EventoStream(
                        etapa=TipoEventoConversacao.ERROR.value,
                        mensagem=f"Valor inválido para campo '{campo}'",
                        dados={"campo": campo, "valor_recebido": valor}
                    )
                    # Perguntar novamente
                    async for evento in self._emitir_pergunta(session_id, campo):
                        yield evento
                    return

        # =====================================================================
        # 3. Processar confirmação (se houver)
        # =====================================================================
        if confirmacao:
            if confirmacao == "confirmar":
                # Verificar em qual fase estamos para saber o que confirmar
                if sessao.fase == FaseConversacao.COLETA:
                    # Confirmar defaults e ir para confirmação do resumo
                    self.conversation.confirmar_todos_defaults(session_id)
                    # NÃO muda para PROCESSAMENTO ainda, vai mostrar resumo primeiro

                    yield EventoStream(
                        etapa=TipoEventoConversacao.USER_CONFIRMED.value,
                        mensagem="Valores padrão confirmados.",
                        dados={"session_id": session_id}
                    )
                    # Continua para mostrar confirm_summary abaixo

                elif sessao.fase == FaseConversacao.CONFIRMACAO:
                    # Confirmar resumo final e ir para processamento
                    self.conversation.atualizar_fase(session_id, FaseConversacao.PROCESSAMENTO)

                    yield EventoStream(
                        etapa=TipoEventoConversacao.USER_CONFIRMED.value,
                        mensagem="Dados confirmados. Iniciando processamento...",
                        dados={"session_id": session_id}
                    )

            elif confirmacao == "corrigir":
                # Voltar para fase de coleta
                self.conversation.atualizar_fase(session_id, FaseConversacao.COLETA)

                yield EventoStream(
                    etapa=TipoEventoConversacao.CORRECTION_NEEDED.value,
                    mensagem="Qual campo deseja corrigir?",
                    dados={
                        "session_id": session_id,
                        "campos_disponiveis": list(sessao.campos.keys())
                    }
                )
                return

        # Recarregar sessão após atualizações
        sessao = self.conversation.obter_sessao(session_id)

        # =====================================================================
        # 4. Extração inicial (se é primeira mensagem com texto)
        # =====================================================================
        if sessao.fase == FaseConversacao.COLETA and texto_usuario and not resposta_campo:
            yield EventoStream(
                etapa=TipoEventoConversacao.EXTRACTION_START.value,
                mensagem="Analisando seu pedido...",
                progresso=0.1
            )

            # Adicionar mensagem ao histórico
            self.conversation.adicionar_mensagem(session_id, texto_usuario)

            # Extração inteligente (por regras - rápido, sem LLM)
            t_start = time.time()
            logger.info(f"[TIMING] Iniciando extração por regras...")
            resultado_extracao = await extrair_informacoes_inteligente(
                texto_usuario,
                llm_provider=self.llm,
                usar_llm=False  # Extração rápida por regras, sem LLM
            )
            t_elapsed = time.time() - t_start
            logger.info(f"[TIMING] Extração concluída em {t_elapsed:.2f}s")

            if not resultado_extracao.sucesso:
                yield EventoStream(
                    etapa=TipoEventoConversacao.ERROR.value,
                    mensagem=resultado_extracao.erro or "Erro na extração",
                    dados={"session_id": session_id}
                )
                return

            # Atualizar sessão com campos extraídos
            for campo, info in resultado_extracao.campos_extraidos.items():
                self.conversation.atualizar_campo(
                    session_id,
                    campo,
                    info.valor,
                    info.fonte,
                    info.confianca
                )

            # Atualizar campos com padrão
            for campo, valor in resultado_extracao.campos_com_padrao.items():
                # Só adiciona se ainda não existe na sessão
                if campo not in sessao.campos or sessao.campos[campo].valor is None:
                    self.conversation.atualizar_campo(
                        session_id,
                        campo,
                        valor,
                        FonteCampo.PADRAO,
                        1.0
                    )

            # Atualizar lista de pendentes
            sessao = self.conversation.obter_sessao(session_id)
            sessao.campos_pendentes = resultado_extracao.campos_faltantes.copy()

            # Verificar se foi detectado tipo não suportado
            tipo_nao_suportado = resultado_extracao.campos_com_padrao.get("_tipo_nao_suportado")
            if tipo_nao_suportado:
                # Emitir evento de tipo não suportado
                yield EventoStream(
                    etapa=TipoEventoConversacao.UNSUPPORTED_TYPE.value,
                    mensagem=f"Tipo '{tipo_nao_suportado['tipo_detectado']}' não é suportado. "
                             "Selecione um tipo residencial:",
                    dados={
                        "session_id": session_id,
                        "tipo_detectado": tipo_nao_suportado['tipo_detectado'],
                        "categoria": tipo_nao_suportado['categoria'],
                        "tipos_disponiveis": tipo_nao_suportado['tipos_disponiveis']
                    }
                )
                # Remover a chave interna
                del resultado_extracao.campos_com_padrao["_tipo_nao_suportado"]

            # Emitir evento de extração parcial
            campos_extraidos_dict = {
                campo: info.to_dict()
                for campo, info in resultado_extracao.campos_extraidos.items()
            }

            yield EventoStream(
                etapa=TipoEventoConversacao.EXTRACTION_PARTIAL.value,
                mensagem="Informações identificadas",
                progresso=0.2,
                dados={
                    "session_id": session_id,
                    "extraidos": campos_extraidos_dict,
                    "faltantes": resultado_extracao.campos_faltantes,
                    "com_padrao": resultado_extracao.campos_com_padrao,
                    "avisos": resultado_extracao.avisos
                }
            )

        # =====================================================================
        # 5. Verificar campos faltantes e perguntar
        # =====================================================================
        sessao = self.conversation.obter_sessao(session_id)

        if sessao.campos_pendentes:
            campo_faltante = sessao.campos_pendentes[0]
            async for evento in self._emitir_pergunta(session_id, campo_faltante):
                yield evento
            return  # Aguardar resposta

        # =====================================================================
        # 6. Verificar defaults não confirmados
        # =====================================================================
        campos_com_padrao = self.conversation.obter_campos_com_padrao_nao_confirmados(
            session_id
        )

        if campos_com_padrao and sessao.fase == FaseConversacao.COLETA:
            yield EventoStream(
                etapa=TipoEventoConversacao.CONFIRM_DEFAULTS.value,
                mensagem="Confirme os valores padrão que serão utilizados:",
                dados={
                    "session_id": session_id,
                    "defaults": campos_com_padrao
                }
            )
            return  # Aguardar confirmação

        # =====================================================================
        # 7. Mostrar resumo para confirmação final
        # =====================================================================
        if sessao.fase == FaseConversacao.COLETA:
            self.conversation.atualizar_fase(session_id, FaseConversacao.CONFIRMACAO)
            resumo = self.conversation.obter_resumo(session_id)

            yield EventoStream(
                etapa=TipoEventoConversacao.CONFIRM_SUMMARY.value,
                mensagem="Confirme os dados do orçamento:",
                dados={
                    "session_id": session_id,
                    "resumo": resumo
                }
            )
            return  # Aguardar confirmação

        # =====================================================================
        # 8. Processar orçamento (se confirmado)
        # =====================================================================
        if sessao.fase == FaseConversacao.PROCESSAMENTO:
            # Construir DadosExtraidos a partir dos campos da sessão
            dados = construir_dados_extraidos(
                sessao.campos,
                sessao.texto_original
            )

            if dados is None:
                yield EventoStream(
                    etapa=TipoEventoConversacao.ERROR.value,
                    mensagem="Dados incompletos para processamento",
                    dados={"session_id": session_id}
                )
                return

            # Processar usando orquestrador base
            async for evento in self._processar_orcamento(sessao, dados):
                yield evento

            # Marcar como completo
            self.conversation.atualizar_fase(session_id, FaseConversacao.COMPLETO)

    async def _emitir_pergunta(
        self,
        session_id: str,
        campo: str
    ) -> AsyncGenerator[EventoStream, None]:
        """Emite evento de pergunta para um campo."""
        pergunta_config = self.conversation.obter_pergunta_para_campo(campo)

        if pergunta_config:
            yield EventoStream(
                etapa=TipoEventoConversacao.QUESTION.value,
                mensagem=pergunta_config.pergunta,
                dados={
                    "session_id": session_id,
                    "campo": campo,
                    "tipo": pergunta_config.tipo.value,
                    "opcoes": pergunta_config.opcoes
                }
            )
        else:
            yield EventoStream(
                etapa=TipoEventoConversacao.QUESTION.value,
                mensagem=f"Por favor, informe o valor para '{campo}':",
                dados={
                    "session_id": session_id,
                    "campo": campo,
                    "tipo": "text"
                }
            )

    def _normalizar_valor_campo(self, campo: str, valor: Any) -> Any:
        """Normaliza e valida valor de um campo."""
        from app.core.validators import (
            validar_uf,
            validar_padrao,
            validar_tipo,
            validar_quantidade,
            validar_mes,
            validar_ano
        )

        if campo == "uf":
            uf_valida, _ = validar_uf(str(valor))
            return uf_valida

        elif campo == "tipo_construtivo":
            tipo_valido, _ = validar_tipo(str(valor))
            return tipo_valido

        elif campo == "padrao_construtivo":
            padrao_valido, _ = validar_padrao(str(valor))
            return padrao_valido

        elif campo == "quantidade":
            qtd, _ = validar_quantidade(valor)
            return qtd

        elif campo == "mes_referencia":
            return validar_mes(valor)

        elif campo == "ano_referencia":
            return validar_ano(valor)

        return valor

    async def _processar_orcamento(
        self,
        sessao,
        dados: DadosExtraidos
    ) -> AsyncGenerator[EventoStream, None]:
        """
        Processa o orçamento usando o fluxo existente.

        Reutiliza a lógica do BudgetOrchestrator base.
        """
        inicio = time.time()
        resultado = ResultadoOrcamento(sucesso=False)

        # =====================================================================
        # ETAPA 1: Carregar estrutura (mesma lógica do BudgetOrchestrator)
        # =====================================================================
        yield EventoStream(
            etapa="load_base",
            mensagem=f"Buscando estrutura de orçamento para '{dados.padrao_construtivo}'...",
            progresso=0.25
        )

        spring_client = get_spring_client()
        fonte_estrutura = "api"
        itens_para_processar = []

        # Tentar buscar da API Spring primeiro
        orcamento_base = await spring_client.buscar_orcamento_base(dados.padrao_construtivo)

        if orcamento_base:
            etapas_base = await spring_client.buscar_etapas_por_orcamento(
                orcamento_base['codigo']
            )

            for etapa in etapas_base:
                for item in etapa.itens:
                    itens_para_processar.append({
                        "etapa_nome": etapa.nome,
                        "etapa_codigo": etapa.codigo,
                        "item": item
                    })

            nome_base = orcamento_base['nome']
            total_etapas = len(etapas_base)

        else:
            # Fallback: Gerar estrutura via LLM
            yield EventoStream(
                etapa="generate_structure",
                mensagem="Orçamento base não encontrado. Gerando estrutura via IA...",
                progresso=0.27
            )

            estrutura = await gerar_estrutura_orcamento(
                dados=dados,
                llm_provider=self.llm,
                usar_cot=True
            )

            if not estrutura.sucesso:
                yield EventoStream(
                    etapa="error",
                    mensagem=f"Erro ao gerar estrutura: {estrutura.erro}"
                )
                return

            fonte_estrutura = "llm"
            codigo_etapa = 1

            for etapa in estrutura.etapas:
                for item in etapa.itens:
                    item_obj = type('ItemOrcamento', (), {
                        'codigo': 0,
                        'nome': item.nome,
                        'descricao': item.descricao,
                        'quantidade': item.quantidade,
                        'unidade': item.unidade,
                        'custo_unitario': 0.0
                    })()

                    itens_para_processar.append({
                        "etapa_nome": etapa.nome,
                        "etapa_codigo": codigo_etapa,
                        "item": item_obj
                    })

                codigo_etapa += 1

            nome_base = f"Gerado por IA - {dados.padrao_construtivo}"
            total_etapas = len(estrutura.etapas)

        total_itens = len(itens_para_processar)

        if total_itens == 0:
            yield EventoStream(
                etapa="error",
                mensagem="Nenhum item encontrado na estrutura do orçamento"
            )
            return

        yield EventoStream(
            etapa="load_base_done",
            mensagem=f"Estrutura carregada ({fonte_estrutura.upper()}): {total_etapas} etapas, {total_itens} itens",
            progresso=0.3,
            dados={
                "orcamento_base": nome_base,
                "fonte": fonte_estrutura,
                "total_etapas": total_etapas,
                "total_itens": total_itens
            }
        )

        # =====================================================================
        # ETAPA 2: Busca SINAPI
        # =====================================================================
        yield EventoStream(
            etapa="search",
            mensagem=f"Buscando composições SINAPI para {total_itens} itens...",
            progresso=0.4
        )

        vector_service = await get_vector_search_service()

        async def buscar_item(item_info: dict):
            item = item_info["item"]
            texto_busca = item.descricao or item.nome
            busca = await vector_service.buscar_com_confianca(texto_busca)
            return {"item_info": item_info, "busca": busca}

        resultados_busca = await asyncio.gather(
            *[buscar_item(item_info) for item_info in itens_para_processar]
        )

        yield EventoStream(
            etapa="search_done",
            mensagem="Busca SINAPI concluída",
            progresso=0.6
        )

        # =====================================================================
        # ETAPA 3: Buscar preços
        # =====================================================================
        yield EventoStream(
            etapa="pricing",
            mensagem="Calculando preços...",
            progresso=0.65
        )

        codigos_para_buscar = set()
        for r in resultados_busca:
            if r["busca"].melhor_match:
                codigos_para_buscar.add(r["busca"].melhor_match.codigo)

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

        precos_map = {codigo: preco for codigo, preco in precos_resultado}

        yield EventoStream(
            etapa="pricing_done",
            mensagem=f"Preços encontrados: {len([p for p in precos_map.values() if p])}/{len(codigos_para_buscar)}",
            progresso=0.8
        )

        # =====================================================================
        # ETAPA 4: Montar resultado
        # =====================================================================
        yield EventoStream(
            etapa="synthesize",
            mensagem="Montando orçamento...",
            progresso=0.85
        )

        etapas_dict: Dict[str, EtapaProcessada] = {}
        estatisticas = Estatisticas()

        for r in resultados_busca:
            item_info = r["item_info"]
            busca = r["busca"]
            item = item_info["item"]
            etapa_nome = item_info["etapa_nome"]

            estatisticas.total_itens += 1

            if busca.nivel_confianca == NivelConfianca.ALTA:
                estatisticas.alta_confianca += 1
            elif busca.nivel_confianca == NivelConfianca.MEDIA:
                estatisticas.media_confianca += 1
            else:
                estatisticas.baixa_confianca += 1

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

            quantidade_ajustada = item.quantidade * dados.quantidade
            preco_total = preco_unitario * quantidade_ajustada

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

        valor_total = sum(e.valor_total for e in etapas_dict.values())

        resultado.sucesso = True
        resultado.dados_extraidos = dados
        resultado.etapas = list(etapas_dict.values())
        resultado.estatisticas = estatisticas
        resultado.valor_total = valor_total
        resultado.tempo_processamento = time.time() - inicio
        resultado.fonte_estrutura = fonte_estrutura

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
        # ETAPA 5: Persistir (opcional)
        # =====================================================================
        if sessao.nome_obra:
            yield EventoStream(
                etapa="persist",
                mensagem="Salvando orçamento...",
                progresso=0.92
            )

            try:
                orcamento_criado = await self._base_orchestrator._persistir_orcamento(
                    resultado, sessao.nome_obra, dados
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
            dados=self._base_orchestrator._resultado_to_dict(resultado)
        )
