"""
Extração de informações do texto usando LLM
"""

import json
import re
import logging
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List, Dict, Any

from app.llm import LLMProvider
from app.core.prompts import criar_prompt_extracao, PROMPT_SISTEMA_EXTRACAO
from app.core.validators import (
    validar_uf,
    validar_padrao,
    validar_tipo,
    validar_data_referencia,
    validar_quantidade
)
from app.core.models import (
    DadosExtraidos,
    CampoInfo,
    FonteCampo,
    ResultadoExtracaoInteligente
)

logger = logging.getLogger(__name__)


# Campos obrigatórios (sem valor padrão)
CAMPOS_OBRIGATORIOS_SEM_PADRAO = ["uf", "tipo_construtivo", "padrao_construtivo"]

# Campos com valor padrão
CAMPOS_COM_PADRAO_DEFAULT = {
    "quantidade": 1,
    "mes_referencia": lambda: datetime.now().month,
    "ano_referencia": lambda: datetime.now().year
}


def extrair_por_regras(texto: str) -> Dict[str, Any]:
    """
    Extração rápida baseada em regras (sem LLM).
    Tenta identificar informações usando regex e mapeamentos.

    Args:
        texto: Texto do usuário

    Returns:
        Dict com campos encontrados, incluindo 'tipo_nao_suportado' se detectado
    """
    from app.config import (
        UF_MAPPING, PADRAO_MAPPING, TIPO_MAPPING, MESES_MAPPING,
        TIPOS_NAO_SUPORTADOS, TIPOS_RESIDENCIAIS_DISPONIVEIS
    )

    texto_upper = texto.upper()
    texto_sem_acento = unicodedata.normalize('NFKD', texto_upper).encode('ASCII', 'ignore').decode('ASCII')
    resultado = {}

    # Extrair quantidade (números antes de palavras-chave)
    qtd_patterns = [
        r'(\d+)\s*(?:casas?|unidades?|residencias?|moradias?|habitac|apartamentos?|aptos?|sobrados?|kitnets?|kitinetes?|studios?)',
        r'construir\s*(\d+)',
        r'(\d+)\s*(?:x|X)\s*',
    ]
    for pattern in qtd_patterns:
        match = re.search(pattern, texto, re.IGNORECASE)
        if match:
            resultado['quantidade'] = int(match.group(1))
            break

    # Extrair UF: nomes completos primeiro, depois siglas (evita falsos positivos)
    nomes_completos = {k: v for k, v in UF_MAPPING.items() if len(k) > 2}
    siglas = {k: v for k, v in UF_MAPPING.items() if len(k) == 2}

    for nome, uf in nomes_completos.items():
        if re.search(rf'\b{re.escape(nome)}\b', texto_sem_acento):
            resultado['estado'] = uf
            break

    if 'estado' not in resultado:
        for nome, uf in siglas.items():
            if re.search(rf'\b{re.escape(nome)}\b', texto_sem_acento):
                resultado['estado'] = uf
                break

    # Verificar tipos NÃO SUPORTADOS primeiro
    tipo_nao_suportado_detectado = None
    categoria_nao_suportada = None
    for categoria, palavras in TIPOS_NAO_SUPORTADOS.items():
        for palavra in palavras:
            if palavra.upper() in texto_upper:
                tipo_nao_suportado_detectado = palavra
                categoria_nao_suportada = categoria
                break
        if tipo_nao_suportado_detectado:
            break

    if tipo_nao_suportado_detectado:
        resultado['tipo_nao_suportado'] = {
            'tipo_detectado': tipo_nao_suportado_detectado,
            'categoria': categoria_nao_suportada,
            'tipos_disponiveis': TIPOS_RESIDENCIAIS_DISPONIVEIS
        }
        # Não extrair tipo_construtivo se detectou tipo não suportado
    else:
        # Extrair tipo construtivo (apenas se não detectou tipo não suportado)
        for tipo, sinonimos in TIPO_MAPPING.items():
            for sinonimo in sinonimos:
                if sinonimo.upper() in texto_upper:
                    resultado['tipo_construtivo'] = tipo.lower()
                    break
            if 'tipo_construtivo' in resultado:
                break

    # Extrair padrão construtivo
    for padrao, sinonimos in PADRAO_MAPPING.items():
        for sinonimo in sinonimos:
            if sinonimo.upper() in texto_upper:
                resultado['padrao_construtivo'] = padrao.lower()
                break
        if 'padrao_construtivo' in resultado:
            break

    # Extrair mês
    for nome_mes, num_mes in MESES_MAPPING.items():
        if nome_mes in texto_upper:
            resultado['mes_referencia'] = num_mes
            break

    # Extrair ano (4 dígitos entre 2020-2030)
    ano_match = re.search(r'\b(202[0-9]|2030)\b', texto)
    if ano_match:
        resultado['ano_referencia'] = int(ano_match.group(1))

    return resultado


@dataclass
class ResultadoExtracao:
    """Resultado da extração de informações"""
    sucesso: bool
    dados: Optional[DadosExtraidos] = None
    erros: List[str] = None
    avisos: List[str] = None

    def __post_init__(self):
        if self.erros is None:
            self.erros = []
        if self.avisos is None:
            self.avisos = []


def extrair_json_da_resposta(resposta_texto: str) -> Optional[dict]:
    """
    Extrai JSON da resposta do LLM, mesmo se houver texto extra

    Args:
        resposta_texto: Texto da resposta do LLM

    Returns:
        Dict parseado ou None
    """
    # Tentar extrair JSON entre chaves
    match = re.search(r'\{[^{}]*\}', resposta_texto, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    # Tentar limpar markdown
    texto_limpo = resposta_texto.strip()
    if texto_limpo.startswith('```'):
        linhas = texto_limpo.split('\n')
        # Remover primeira e última linha (```json e ```)
        linhas = [l for l in linhas if not l.strip().startswith('```')]
        texto_limpo = '\n'.join(linhas)

    try:
        return json.loads(texto_limpo)
    except json.JSONDecodeError:
        return None


async def extrair_informacoes(
    texto_usuario: str,
    llm_provider: LLMProvider
) -> ResultadoExtracao:
    """
    Extrai informações estruturadas do texto do usuário usando LLM

    Args:
        texto_usuario: Texto em linguagem natural
        llm_provider: Provider LLM a usar

    Returns:
        ResultadoExtracao com dados ou erros
    """
    resultado = ResultadoExtracao(sucesso=False)

    # 1. Chamar LLM
    prompt = criar_prompt_extracao(texto_usuario)

    try:
        resposta = await llm_provider.complete(
            prompt=prompt,
            system_prompt=PROMPT_SISTEMA_EXTRACAO,
            temperature=0.1,
            max_tokens=300
        )
    except Exception as e:
        resultado.erros.append(f"Erro ao chamar LLM: {str(e)}")
        return resultado

    # 2. Extrair JSON
    dados_extraidos = extrair_json_da_resposta(resposta.content)

    if not dados_extraidos:
        resultado.erros.append("Não foi possível extrair JSON da resposta do LLM")
        return resultado

    # 3. Validar e normalizar cada campo
    erros = []
    avisos = []

    # Quantidade
    quantidade, erro_qtd = validar_quantidade(dados_extraidos.get('quantidade', 1))
    if quantidade is None:
        erros.append(erro_qtd)
    elif erro_qtd:
        avisos.append(erro_qtd)

    # Tipo Construtivo
    tipo_raw = dados_extraidos.get('tipo_construtivo', '')
    tipo_valido, conf_tipo = validar_tipo(tipo_raw)
    if not tipo_valido:
        erros.append(
            f"Tipo construtivo '{tipo_raw}' não reconhecido. "
            "Tipos disponíveis: Casa, Apartamento, Sobrado, Kitnet."
        )

    # Padrão Construtivo
    padrao_raw = dados_extraidos.get('padrao_construtivo', '')
    padrao_valido, conf_padrao = validar_padrao(padrao_raw)
    if not padrao_valido:
        erros.append(
            f"Padrão construtivo '{padrao_raw}' não reconhecido. "
            "Use 'mínimo' ou 'básico'."
        )

    # Estado/UF
    estado_raw = dados_extraidos.get('estado', '')
    uf_valida, conf_uf = validar_uf(estado_raw)
    if not uf_valida:
        erros.append(f"Estado '{estado_raw}' não reconhecido")
    elif conf_uf < 1.0:
        avisos.append(f"Estado '{estado_raw}' interpretado como '{uf_valida}' por aproximação")

    # Data de Referência
    mes_raw = dados_extraidos.get('mes_referencia')
    ano_raw = dados_extraidos.get('ano_referencia')
    mes, ano, usou_corrente = validar_data_referencia(mes_raw, ano_raw)

    if usou_corrente:
        avisos.append(f"Data de referência não especificada. Usando: {mes:02d}/{ano}")

    # Se houver erros críticos, retornar
    if erros:
        resultado.erros = erros
        resultado.avisos = avisos
        return resultado

    # 4. Montar dados validados
    resultado.sucesso = True
    resultado.avisos = avisos
    resultado.dados = DadosExtraidos(
        quantidade=quantidade,
        tipo_construtivo=tipo_valido,
        padrao_construtivo=padrao_valido,
        uf=uf_valida,
        mes_referencia=mes,
        ano_referencia=ano,
        descricao_original=texto_usuario
    )

    return resultado


async def extrair_informacoes_inteligente(
    texto_usuario: str,
    llm_provider: Optional[LLMProvider] = None,
    usar_llm: bool = False
) -> ResultadoExtracaoInteligente:
    """
    Extrai informações de forma inteligente, separando:
    - Campos extraídos com sucesso
    - Campos faltantes (obrigatórios não informados)
    - Campos com valor padrão

    NÃO falha por campos faltantes, apenas reporta.

    Args:
        texto_usuario: Texto em linguagem natural
        llm_provider: Provider LLM a usar (opcional)
        usar_llm: Se True, usa LLM para extração. Se False, usa apenas regras.

    Returns:
        ResultadoExtracaoInteligente com campos separados
    """
    resultado = ResultadoExtracaoInteligente()

    # 1. Sempre tentar extração por regras primeiro (rápido)
    logger.info("[EXTRATOR] Iniciando extração por regras...")
    dados_extraidos = extrair_por_regras(texto_usuario)
    logger.info(f"[EXTRATOR] Regras extraíram: {dados_extraidos}")

    # 2. Se usar_llm=True e há campos faltantes, chamar LLM
    campos_faltantes_regras = []
    for campo in CAMPOS_OBRIGATORIOS_SEM_PADRAO:
        campo_map = "estado" if campo == "uf" else campo
        if campo_map not in dados_extraidos or not dados_extraidos.get(campo_map):
            campos_faltantes_regras.append(campo)

    if usar_llm and llm_provider and campos_faltantes_regras:
        logger.info(f"[EXTRATOR] Campos faltantes após regras: {campos_faltantes_regras}. Chamando LLM...")
        prompt = criar_prompt_extracao(texto_usuario)

        try:
            resposta = await llm_provider.complete(
                prompt=prompt,
                system_prompt=PROMPT_SISTEMA_EXTRACAO,
                temperature=0.1,
                max_tokens=300
            )
            dados_llm = extrair_json_da_resposta(resposta.content)
            if dados_llm:
                # Mesclar: regras têm prioridade, LLM preenche lacunas
                for key, value in dados_llm.items():
                    if key not in dados_extraidos or not dados_extraidos.get(key):
                        dados_extraidos[key] = value
                logger.info(f"[EXTRATOR] Após LLM: {dados_extraidos}")
        except Exception as e:
            logger.warning(f"[EXTRATOR] Erro ao chamar LLM: {e}. Continuando com regras.")
            resultado.avisos.append(f"LLM indisponível, usando extração por regras")

    # 3. Verificar se foi detectado tipo não suportado
    if 'tipo_nao_suportado' in dados_extraidos:
        resultado.campos_faltantes.append("tipo_construtivo")
        resultado.avisos.append(
            f"Tipo '{dados_extraidos['tipo_nao_suportado']['tipo_detectado']}' "
            f"({dados_extraidos['tipo_nao_suportado']['categoria']}) não é suportado. "
            "Apenas tipos residenciais são aceitos."
        )
        # Guardar informação do tipo não suportado para o orquestrador
        resultado.campos_com_padrao["_tipo_nao_suportado"] = dados_extraidos['tipo_nao_suportado']

    # 4. Processar cada campo individualmente

    # --- UF (Obrigatório) ---
    estado_raw = dados_extraidos.get('estado', '')
    if estado_raw:
        uf_valida, conf_uf = validar_uf(estado_raw)
        if uf_valida:
            resultado.campos_extraidos["uf"] = CampoInfo(
                nome="uf",
                valor=uf_valida,
                fonte=FonteCampo.USUARIO,
                confianca=conf_uf,
                confirmado=False,
                obrigatorio=True
            )
            if conf_uf < 1.0:
                resultado.avisos.append(
                    f"Estado '{estado_raw}' interpretado como '{uf_valida}'"
                )
        else:
            resultado.campos_faltantes.append("uf")
            resultado.avisos.append(f"Estado '{estado_raw}' não reconhecido")
    else:
        resultado.campos_faltantes.append("uf")

    # --- Tipo Construtivo (Obrigatório) ---
    # Não processar se já foi marcado como faltante por tipo não suportado
    if "tipo_construtivo" not in resultado.campos_faltantes:
        tipo_raw = dados_extraidos.get('tipo_construtivo', '')
        if tipo_raw:
            tipo_valido, conf_tipo = validar_tipo(tipo_raw)
            if tipo_valido:
                resultado.campos_extraidos["tipo_construtivo"] = CampoInfo(
                    nome="tipo_construtivo",
                    valor=tipo_valido,
                    fonte=FonteCampo.USUARIO,
                    confianca=conf_tipo,
                    confirmado=False,
                    obrigatorio=True
                )
            else:
                resultado.campos_faltantes.append("tipo_construtivo")
                resultado.avisos.append(
                    f"Tipo construtivo '{tipo_raw}' não reconhecido. "
                    "Tipos disponíveis: Casa, Apartamento, Sobrado, Kitnet."
                )
        else:
            resultado.campos_faltantes.append("tipo_construtivo")

    # --- Padrão Construtivo (Obrigatório) ---
    padrao_raw = dados_extraidos.get('padrao_construtivo', '')
    if padrao_raw:
        padrao_valido, conf_padrao = validar_padrao(padrao_raw)
        if padrao_valido:
            resultado.campos_extraidos["padrao_construtivo"] = CampoInfo(
                nome="padrao_construtivo",
                valor=padrao_valido,
                fonte=FonteCampo.USUARIO,
                confianca=conf_padrao,
                confirmado=False,
                obrigatorio=True
            )
        else:
            resultado.campos_faltantes.append("padrao_construtivo")
            resultado.avisos.append(
                f"Padrão construtivo '{padrao_raw}' não reconhecido"
            )
    else:
        resultado.campos_faltantes.append("padrao_construtivo")

    # --- Quantidade (Com padrão = 1) ---
    quantidade_raw = dados_extraidos.get('quantidade')
    if quantidade_raw is not None:
        quantidade, erro_qtd = validar_quantidade(quantidade_raw)
        if quantidade is not None:
            resultado.campos_extraidos["quantidade"] = CampoInfo(
                nome="quantidade",
                valor=quantidade,
                fonte=FonteCampo.USUARIO,
                confianca=1.0,
                confirmado=False,
                obrigatorio=False
            )
        else:
            # Usar padrão
            resultado.campos_com_padrao["quantidade"] = 1
            resultado.avisos.append(erro_qtd)
    else:
        # Usar padrão
        resultado.campos_com_padrao["quantidade"] = 1

    # --- Mês de Referência (Com padrão = mês atual) ---
    mes_raw = dados_extraidos.get('mes_referencia')
    ano_raw = dados_extraidos.get('ano_referencia')
    mes, ano, usou_corrente = validar_data_referencia(mes_raw, ano_raw)

    if mes_raw is not None and not usou_corrente:
        resultado.campos_extraidos["mes_referencia"] = CampoInfo(
            nome="mes_referencia",
            valor=mes,
            fonte=FonteCampo.USUARIO,
            confianca=1.0,
            confirmado=False,
            obrigatorio=False
        )
    else:
        resultado.campos_com_padrao["mes_referencia"] = datetime.now().month

    if ano_raw is not None and not usou_corrente:
        resultado.campos_extraidos["ano_referencia"] = CampoInfo(
            nome="ano_referencia",
            valor=ano,
            fonte=FonteCampo.USUARIO,
            confianca=1.0,
            confirmado=False,
            obrigatorio=False
        )
    else:
        resultado.campos_com_padrao["ano_referencia"] = datetime.now().year

    if usou_corrente and (mes_raw is None and ano_raw is None):
        resultado.avisos.append(
            f"Data de referência não especificada. Usando padrão: {mes:02d}/{ano}"
        )

    return resultado


def construir_dados_extraidos(
    campos: Dict[str, CampoInfo],
    texto_original: str = ""
) -> Optional[DadosExtraidos]:
    """
    Constrói DadosExtraidos a partir de um dict de CampoInfo.

    Args:
        campos: Dict com campos e seus valores
        texto_original: Texto original do usuário

    Returns:
        DadosExtraidos ou None se campos obrigatórios faltantes
    """
    # Verificar campos obrigatórios
    for campo in CAMPOS_OBRIGATORIOS_SEM_PADRAO:
        if campo not in campos or campos[campo].valor is None:
            return None

    return DadosExtraidos(
        quantidade=campos.get("quantidade", CampoInfo(nome="quantidade", valor=1)).valor or 1,
        tipo_construtivo=campos["tipo_construtivo"].valor,
        padrao_construtivo=campos["padrao_construtivo"].valor,
        uf=campos["uf"].valor,
        mes_referencia=campos.get(
            "mes_referencia",
            CampoInfo(nome="mes_referencia", valor=datetime.now().month)
        ).valor or datetime.now().month,
        ano_referencia=campos.get(
            "ano_referencia",
            CampoInfo(nome="ano_referencia", valor=datetime.now().year)
        ).valor or datetime.now().year,
        descricao_original=texto_original
    )
