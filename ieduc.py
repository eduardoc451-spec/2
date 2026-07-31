from datetime import date, datetime
from io import BytesIO
import html
import json
import logging
import os
import re
import sys
import warnings
import pandas as pd

import plotly.express as px
import plotly.graph_objects as go
import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.shapes import Drawing, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
import streamlit as st

# =============================================================================
# CONSTANTES E REGEX GLOBAIS
# =============================================================================
REGEX_PURE_URL = r"(https?://[^\s]+)"

# =============================================================================
# IMPORTAÇÃO DAS FUNÇÕES UTILITÁRIAS COMPARTILHADAS (UTILS)
# =============================================================================
try:
    from utils import (
        bloco_comentarios,
        get_connection,
        load_respostas_ieduc,
        modal_aviso_link,
        render_sidebar_ieduc,
        save_resp_ieduc,
    )
except ImportError:
    logging.warning("Módulo utils.py não encontrado. Carregando funções fallback de segurança.")

    def get_connection():
        """Conexão fallback com banco Neon usando URL das Secrets do Streamlit."""
        db_url = st.secrets.get("postgres", {}).get("url") or os.getenv("DATABASE_URL")
        return psycopg2.connect(db_url)

    def load_respostas_ieduc(ano: int = None, forcar_recarga: bool = False) -> dict:
        """Fallback local para carregar respostas do iEduc."""
        ano_sel = ano or st.session_state.get("ano_referencia_ieduc", 2026)
        key_ano = f"respostas_ieduc_{ano_sel}"
        return st.session_state.get(key_ano, {})

    def save_resp_ieduc(qid, valor, pontos, link="", comentarios=None, comentario=""):
        """Fallback para manter na memória caso utils falhe."""
        ano_sel = st.session_state.get("ano_referencia_ieduc", 2026)
        key_ano = f"respostas_ieduc_{ano_sel}"
        if key_ano not in st.session_state:
            st.session_state[key_ano] = {}

        st.session_state[key_ano][str(qid)] = {
            "valor": str(valor),
            "pontos": float(pontos),
            "link": str(link),
            "comentario": str(comentario),
            "detalhes": {"link": str(link), "comentario": str(comentario)}
        }
        return True

    def bloco_comentarios(qid: str, res_data: dict, ano_sel: int):
        d_item = res_data.get(str(qid), {})
        coment_salvo = d_item.get("comentario", "")
        return st.text_area(
            "💬 Observações / Comentários:",
            value=coment_salvo,
            key=f"coment_ieduc_{qid}_{ano_sel}",
            placeholder="Escreva aqui observações ou justificativas...",
            height=80,
        )

    def modal_aviso_link(*args, **kwargs):
        pass

    def render_sidebar_ieduc(*args, **kwargs):
        return 0, {}, datetime.now().year

# =============================================================================
# CONFIGURAÇÃO COMPLETA DE ESTILOS DE RELATÓRIO (PDF) - iEduc
# =============================================================================
styles = getSampleStyleSheet()

# --- ESTILOS DE TABELA ---
style_tabela_padrao = ParagraphStyle(
    "TabelaPadrao",
    parent=styles["Normal"],
    fontName="Helvetica",
    fontSize=9,
    leading=11,
    alignment=TA_LEFT,
)

style_tabela_centro = ParagraphStyle(
    "TabelaCentro",
    parent=styles["Normal"],
    fontName="Helvetica",
    fontSize=9,
    leading=11,
    alignment=TA_CENTER,
)

style_tabela_esquerda = ParagraphStyle(
    "TabelaEsquerda",
    parent=styles["Normal"],
    fontName="Helvetica",
    fontSize=9,
    leading=11,
    alignment=TA_LEFT,
)

style_tabela_direita = ParagraphStyle(
    "TabelaDireita",
    parent=styles["Normal"],
    fontName="Helvetica",
    fontSize=9,
    leading=11,
    alignment=TA_RIGHT,
)

style_tabela_cabecalho = ParagraphStyle(
    "TabelaCabecalho",
    parent=styles["Normal"],
    fontName="Helvetica-Bold",
    fontSize=9,
    leading=11,
    alignment=TA_CENTER,
    textColor=colors.whitesmoke,
)

# --- ESTILOS DE CAPA E TÍTULOS DO RELATÓRIO ---
style_titulo_capa = ParagraphStyle(
    "TituloCapaIEduc",
    parent=styles["Normal"],
    fontName="Helvetica-Bold",
    fontSize=24,
    leading=28,
    alignment=TA_CENTER,
    textColor=colors.HexColor("#1E3A8A"),
    spaceAfter=15,
)

style_subtitulo_capa = ParagraphStyle(
    "SubtituloCapaIEduc",
    parent=styles["Normal"],
    fontName="Helvetica",
    fontSize=14,
    leading=18,
    alignment=TA_CENTER,
    textColor=colors.HexColor("#4B5563"),
    spaceAfter=20,
)

# -----------------------------------------------------------------------------
# CONFIGURAÇÕES INICIAIS E SUPRESSÃO DE WARNINGS
# -----------------------------------------------------------------------------
warnings.filterwarnings("ignore")
logging.getLogger("streamlit").setLevel(logging.ERROR)

# =============================================================================
# CONSTANTES GLOBAIS i-EDUC
# =============================================================================

PONTUACOES_MAX_IEDUC = {
    # 1.0 Creche
    "1.1.1": 2, "1.1.2": 3, "1.2.1.1": 5, "1.2.2": 5, "1.3": 10, "1.4": 18, "1.7.1": 7, "1.8": 3, 
    "1.9": 2, "1.10": 2, "1.11": 18, "1.11.1": 18, "1.12": 18, "1.12.1": 18, "1.13": 50, "1.15": 10,
    
    # 2.0 Pré-escola
    "2.1.1": 2, "2.1.2": 3, "2.2.1.1": 5, "2.2.2": 5, "2.3": 10, "2.4": 18, "2.7.1": 7, "2.8": 3, 
    "2.9": 2, "2.10": 2, "2.11": 18, "2.11.1": 18, "2.12": 18, "2.12.1": 18, "2.13": 50, "2.15": 10,
    
    # 3.0 Ensino Fundamental
    "3.1": 10, "3.2": 19, "3.5.1": 7, "3.6": 3, "3.7": 2, "3.8": 2, "3.10": 12, "3.11": 2, 
    "3.12": 20, "3.12.1": 20, "3.13.1": 20, "3.14.1": 20, "3.15.3.1": 18, "3.15.4.1": 18, "3.16": 20, 
    "3.19": 10, "3.20": 2.5, "3.23": 25,
    
    # 5.0 a 12.0 Infraestrutura, Gestão e Merenda
    "5.0": 75, "7.0": 5, "8.1": 12, "9.0": 2, "11.1": 2, "12.1": 6,
    
    # 14.0 a 19.0 Planos, Conselhos e Operação
    "14.3": 20, "14.3.1": 30, "16.1": 3, "16.2": 3, "16.3": 6, "16.5": 3, "17.3.1": 2, 
    "17.4": 3, "17.5": 6, "17.7": 3, "18.1": 3, "18.2": 6, "18.3.1": 6, "19.3": 2,
    
    # Bloco Especial E1 e E2
    "E1.1": 2, "E1.2": 4, "E1.5": 6, "E1.6": 2, "E1.8": 12.5, "E1.9": 12.5,
    "E2.1": 2, "E2.2": 4, "E2.5": 6, "E2.6": 2, "E2.8": 12.5, "E2.9": 12.5,
    
    # Bloco Especial E3, E5, E6, E7 e E13
    "E3.3": 6, "E3.4": 12, "E3.5": 2, "E3.9": 12.5, "E3.10": 12.5,
    "E13.1": 18, "E.13.2": 18, "E13.3": 38, "E5": 75, "E6": 5, "E7": 5
}

CATEGORIAS_MAP_IEDUC = {
    "creche": {
        "label": "1.0 Creche",
        "qids": ["1.1.1", "1.1.2", "1.2.1.1", "1.2.2", "1.3", "1.4", "1.7.1", "1.8", "1.9", "1.10", "1.11", "1.11.1", "1.12", "1.12.1", "1.13", "1.15"]
    },
    "pre_escola": {
        "label": "2.0 Pré-escola",
        "qids": ["2.1.1", "2.1.2", "2.2.1.1", "2.2.2", "2.3", "2.4", "2.7.1", "2.8", "2.9", "2.10", "2.11", "2.11.1", "2.12", "2.12.1", "2.13", "2.15"]
    },
    "anos_iniciais_finais": {
        "label": "3.0 Ensino Fundamental",
        "qids": ["3.1", "3.2", "3.5.1", "3.6", "3.7", "3.8", "3.10", "3.11", "3.12", "3.12.1", "3.13.1", "3.14.1", "3.15.3.1", "3.15.4.1", "3.16", "3.19", "3.20", "3.23"]
    },
    "infra_gestao_merenda": {
        "label": "5.0 a 12.0 Infraestrutura, Gestão e Merenda",
        "qids": ["5.0", "7.0", "8.1", "9.0", "11.1", "12.1"]
    },
    "planos_conselhos_outros": {
        "label": "14.0 a 19.0 Planos, Conselhos e Operação",
        "qids": ["14.3", "14.3.1", "16.1", "16.2", "16.3", "16.5", "17.3.1", "17.4", "17.5", "17.7", "18.1", "18.2", "18.3.1", "19.3"]
    },
    "extras_e1_e2": {
        "label": "Blocos Especiais E1 e E2",
        "qids": ["E1.1", "E1.2", "E1.5", "E1.6", "E1.8", "E1.9", "E2.1", "E2.2", "E2.5", "E2.6", "E2.8", "E2.9"]
    },
    "extras_e3_e13_e5_e7": {
        "label": "Blocos Especiais E3, E5, E6, E7 e E13",
        "qids": ["E3.3", "E3.4", "E3.5", "E3.9", "E3.10", "E13.1", "E.13.2", "E13.3", "E5", "E6", "E7"]
    }
}

# Alias de compatibilidade para usar tanto PONTUACOES_MAX quanto PONTUACOES_MAX_IEDUC
PONTUACOES_MAX = PONTUACOES_MAX_IEDUC
CATEGORIAS_MAP = CATEGORIAS_MAP_IEDUC

# =============================================================================
# MODAL DE AVISO AUTOMÁTICO
# =============================================================================
@st.dialog("⚠️ Atenção! Evidência em Link Externo")
def modal_aviso_link(qid, links_encontrados, ano_sel):
    st.warning(f"Detectamos a inclusão de link(s) no campo de evidências da questão **{qid}**.")
    
    for lk in links_encontrados:
        st.markdown(f"🔗 **Endereço:** [{lk}]({lk})")
        
    st.markdown("""
    **Por favor, verifique se este link está configurado para acesso público/compartilhado.**
    
    Se as credenciais estiverem privadas ou exigirem login e senha do seu município, as equipes avaliadoras externas **não conseguirão acessar as provas**, invalidando os pontos desse quesito.
    """)
    
    # Gera a chave exata limpa
    qid_key = str(qid).replace('.', '_')
    chave_gatilho = f"gatilho_modal_{qid_key}_{ano_sel}"
    
    if st.button("Confirmo que o link está liberado para o público", key=f"btn_conf_{qid_key}_{ano_sel}", type="primary"):
        # Desliga o gatilho no session_state para fechar o modal e não reabrir em outros salvamentos
        st.session_state[chave_gatilho] = False
        st.rerun()

style_ano_capa = ParagraphStyle(
    "AnoCapaIEduc",
    parent=styles["Normal"],
    fontName="Helvetica-Bold",
    fontSize=16,
    leading=20,
    alignment=TA_CENTER,
    textColor=colors.HexColor("#1F2937"),
    spaceAfter=25,
)

import json
import logging
import re
import streamlit as st
from datetime import datetime
from psycopg2.extras import RealDictCursor

# =============================================================================
# 1. GESTÃO DE ESTADO E PERSISTÊNCIA NEON POSTGRES - iEduc
# =============================================================================

def get_ano_atual_ieduc() -> int:
    """Recupera o ano de referência ativo para o iEduc."""
    return int(
        st.session_state.get("ano_referencia_ieduc")
        or st.session_state.get("ano_referencia_global")
        or 2026
    )


def load_respostas_ieduc(ano: int = None, forcar_recarga: bool = False) -> dict:
    """Carrega respostas do Neon PostgreSQL diretamente para o st.session_state."""
    if ano is None:
        ano = get_ano_atual_ieduc()

    key_ano = f"respostas_ieduc_{ano}"

    if forcar_recarga or key_ano not in st.session_state:
        st.session_state[key_ano] = {}
        try:
            with get_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    cursor.execute(
                        "SELECT quesito, resposta, pontos, detalhes FROM respostas_ieduc WHERE ano = %s",
                        (int(ano),)
                    )
                    rows = cursor.fetchall()
                    for r in rows:
                        detalhes = r.get('detalhes') or {}
                        if isinstance(detalhes, str):
                            try:
                                detalhes = json.loads(detalhes)
                            except Exception:
                                detalhes = {}

                        st.session_state[key_ano][str(r['quesito'])] = {
                            "valor": r['resposta'] or "",
                            "pontos": float(r['pontos'] or 0.0),
                            "link": detalhes.get("link", ""),
                            "comentarios": detalhes.get("comentarios", []),
                            "comentario": detalhes.get("comentario", ""),
                            "detalhes": detalhes
                        }
        except Exception as e:
            logging.error(f"Erro ao carregar respostas do banco iEduc: {e}")

    return st.session_state[key_ano]


def save_resp_ieduc(qid, valor, pontos, link="", comentarios=None, comentario=""):
    """Salva a resposta no Neon PostgreSQL e sincroniza o estado local reativamente."""
    ano_int = get_ano_atual_ieduc()
    key_ano = f"respostas_ieduc_{ano_int}"

    if key_ano not in st.session_state:
        st.session_state[key_ano] = {}

    dados_atuais = st.session_state[key_ano].get(str(qid), {})

    if comentarios is None:
        comentarios = dados_atuais.get("comentarios", [])

    if not comentario:
        comentario = dados_atuais.get("comentario", "")

    dados_detalhes = {
        "link": str(link or ""),
        "comentarios": comentarios,
        "comentario": str(comentario or "")
    }

    # 1. ATUALIZAÇÃO IMEDIATA DO SESSION STATE
    st.session_state[key_ano][str(qid)] = {
        "valor": str(valor or ""),
        "pontos": float(pontos or 0.0),
        "link": str(link or ""),
        "comentarios": comentarios,
        "comentario": str(comentario or ""),
        "detalhes": dados_detalhes,
        "atualizado_em": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    # 2. PERSISTÊNCIA NO BANCO DE DADOS NEON
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO respostas_ieduc (ano, quesito, resposta, pontos, detalhes, atualizado_em)
                    VALUES (%s, %s, %s, %s, %s::jsonb, CURRENT_TIMESTAMP)
                    ON CONFLICT (ano, quesito)
                    DO UPDATE SET
                        resposta = EXCLUDED.resposta,
                        pontos = EXCLUDED.pontos,
                        detalhes = EXCLUDED.detalhes,
                        atualizado_em = CURRENT_TIMESTAMP;
                """, (
                    int(ano_int),
                    str(qid),
                    str(valor or ""),
                    float(pontos or 0.0),
                    json.dumps(dados_detalhes, ensure_ascii=False)
                ))
            conn.commit()

            # Força sincronização do cache local
            load_respostas_ieduc(ano=ano_int, forcar_recarga=True)
            return True

    except Exception as e:
        logging.error(f"Erro ao salvar no Neon (iEduc): {e}")
        st.error(f"Erro ao salvar no banco Neon: {e}")
        return False


# =============================================================================
# 2. COMPONENTE DE DIÁLOGO INTERNO E COMENTÁRIOS (SISTEMA AVANÇADO)
# =============================================================================

def bloco_comentarios_ieduc(questao_id: str, res_data: dict, sufixo: str = None):
    """Gera o diálogo interno avançado com histórico, status e salvamento direto no Neon."""
    ano_sel = get_ano_atual_ieduc()
    usuario_atual = st.session_state.get("username", st.session_state.get("usuario", "Usuário Anônimo"))

    id_chave = f"{questao_id}_{sufixo}" if sufixo else questao_id
    key_texto = f"v_txt_com_ieduc_{id_chave}_{ano_sel}"
    key_estado_limpar = f"limpar_input_ieduc_{id_chave}_{ano_sel}"
    key_radio = f"rad_status_ieduc_{id_chave}_{ano_sel}"

    if key_estado_limpar not in st.session_state:
        st.session_state[key_estado_limpar] = False

    dados_questao = res_data.get(str(questao_id), {})
    historico = list(dados_questao.get("comentarios", []))

    status_global = "Resolvido"
    for com in historico:
        if isinstance(com, dict) and "status_definido" in com:
            status_global = com["status_definido"]

    badge_status = "🔴 PENDENTE" if status_global == "Pendente" else "🟢 RESOLVIDO"

    with st.expander(f"💬 Diálogo Interno {id_chave} | Status: {badge_status}", expanded=(status_global == "Pendente")):
        opcoes_status = ["Resolvido", "Pendente"]
        idx_status_atual = opcoes_status.index(status_global) if status_global in opcoes_status else 0

        novo_status_clicado = st.radio(
            f"Definir status para {id_chave}:",
            options=opcoes_status,
            index=idx_status_atual,
            horizontal=True,
            key=key_radio
        )

        # 1. Alteração de Status Automática
        if key_radio in st.session_state and st.session_state[key_radio] != status_global:
            log_mudanca = {
                "autor": "Sistema / " + usuario_atual,
                "data": datetime.now().strftime("%d/%m/%Y %H:%M"),
                "texto": f"ℹ️ Alterou o status do quesito para: **{novo_status_clicado.upper()}**.",
                "status_definido": novo_status_clicado
            }
            historico.append(log_mudanca)
            save_resp_ieduc(
                qid=questao_id,
                valor=dados_questao.get("valor", ""),
                pontos=dados_questao.get("pontos", 0.0),
                link=dados_questao.get("link", ""),
                comentarios=historico,
                comentario=dados_questao.get("comentario", "")
            )
            st.rerun()

        # 2. Renderização do Histórico de Balões de Comentários
        if historico:
            for idx, com in enumerate(historico):
                if not isinstance(com, dict):
                    continue
                col_balao, col_lixeira = st.columns([11, 1])

                with col_balao:
                    autor = com.get('autor', 'Anônimo')
                    data_com = com.get('data', '')
                    texto_com = com.get('texto', '')

                    if "Sistema /" in autor:
                        st.markdown(
                            f"""<div style="background-color: #f1f3f5; padding: 6px 12px; border-radius: 6px; margin-bottom: 4px; border-left: 3px solid #ced4da;">
                                <span style="font-size: 11px; color: #6c757d; font-style: italic;">{autor} - {data_com}</span>
                                <p style="margin: 2px 0 0 0; font-size: 12px; color: #495057;">{texto_com}</p>
                            </div>""", unsafe_allow_html=True
                        )
                    else:
                        st.markdown(
                            f"""<div style="background-color: #f8f9fa; padding: 10px 15px; border-radius: 8px; margin-bottom: 6px; border-left: 3px solid #1e3a8a;">
                                <span style="font-size: 11px; color: #1e3a8a; font-weight: bold;">{autor}</span> 
                                <span style="font-size: 10px; color: #999; margin-left: 10px;">{data_com}</span>
                                <p style="margin: 4px 0 0 0; font-size: 13px; color: #333;">{texto_com}</p>
                            </div>""", unsafe_allow_html=True
                        )

                with col_lixeira:
                    if st.button("🗑️", key=f"btn_del_com_ieduc_{id_chave}_{idx}_{ano_sel}"):
                        historico.pop(idx)
                        save_resp_ieduc(
                            qid=questao_id,
                            valor=dados_questao.get("valor", ""),
                            pontos=dados_questao.get("pontos", 0.0),
                            link=dados_questao.get("link", ""),
                            comentarios=historico,
                            comentario=dados_questao.get("comentario", "")
                        )
                        st.rerun()

        # Limpeza reativa da caixa de texto
        if st.session_state[key_estado_limpar]:
            st.session_state[key_texto] = ""
            st.session_state[key_estado_limpar] = False

        novo_texto = st.text_area("Novo comentário:", key=key_texto, height=70, label_visibility="collapsed")

        # 3. Botão para Postar Novo Comentário
        if st.button("Postar Comentário", key=f"btn_com_ieduc_{id_chave}_{ano_sel}", type="primary"):
            if novo_texto.strip():
                nova_mensagem = {
                    "autor": usuario_atual,
                    "data": datetime.now().strftime("%d/%m/%Y %H:%M"),
                    "texto": novo_texto.strip(),
                    "status_definido": status_global
                }
                historico.append(nova_mensagem)
                save_resp_ieduc(
                    qid=questao_id,
                    valor=dados_questao.get("valor", ""),
                    pontos=dados_questao.get("pontos", 0.0),
                    link=dados_questao.get("link", ""),
                    comentarios=historico,
                    comentario=dados_questao.get("comentario", "")
                )
                st.session_state[key_estado_limpar] = True
                st.rerun()

# =============================================================================
# 3. PAINEL DE RESUMO E PONTUAÇÃO (DESEMPENHO DO I-EDUC)
# =============================================================================

def render_dashboard_ieduc(questoes: list):
    """Exibe os cartões de status e progresso do i-Educ."""
    ano = get_ano_atual_ieduc()
    respostas = load_respostas_ieduc(ano)

    total_quesitos = len(questoes)
    preenchidos = 0
    pontuacao_obtida = 0.0
    pontuacao_maxima = 0.0

    for q in questoes:
        qid = str(q["id"])
        peso_max = float(q.get("peso", 1.0))
        pontuacao_maxima += peso_max

        if qid in respostas and respostas[qid].get("valor"):
            preenchidos += 1
            pontuacao_obtida += float(respostas[qid].get("pontos", 0.0))

    progresso_pct = (preenchidos / total_quesitos * 100) if total_quesitos > 0 else 0
    nota_final = (pontuacao_obtida / pontuacao_maxima * 10) if pontuacao_maxima > 0 else 0.0

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Ano de Referência", f"{ano}")
    with col2:
        st.metric("Quesitos Preenchidos", f"{preenchidos} / {total_quesitos}", f"{progresso_pct:.1f}%")
    with col3:
        st.metric("Pontuação Total", f"{pontuacao_obtida:.2f} / {pontuacao_maxima:.2f}")
    with col4:
        st.metric("Nota i-Educ", f"{nota_final:.2f} / 10.0")

    st.progress(min(progresso_pct / 100.0, 1.0))
    st.markdown("---")


# =============================================================================
# 4. RENDERIZADOR DE QUESITOS E FORMULÁRIO (PADRÃO IAMB INTEGRADO COM COMENTÁRIOS)
# =============================================================================

def render_modulo_ieduc(questoes_ieduc: list):
    """Interface principal do módulo i-Educ."""
    st.title("🎓 i-Educ - Índice de Educação")
    
    # 1. Renderiza o resumo dinâmico
    render_dashboard_ieduc(questoes_ieduc)

    ano = get_ano_atual_ieduc()
    respostas = load_respostas_ieduc(ano)

    st.subheader("Formulário de Avaliação")

    for questao in questoes_ieduc:
        qid = str(questao["id"])
        titulo = questao.get("titulo", f"Quesito {qid}")
        opcoes = questao.get("opcoes", ["Sim", "Não"])
        pontos_map = questao.get("pontos_map", {})
        
        # Recupera dados salvos previamente
        resp_salva = respostas.get(qid, {})
        val_atual = resp_salva.get("valor", "")
        link_atual = resp_salva.get("link", "")
        obs_atual = resp_salva.get("comentario", "")

        # Índice padrão para o Selectbox
        idx_padrao = 0
        if val_atual in opcoes:
            idx_padrao = opcoes.index(val_atual) + 1

        opcoes_com_vazio = ["-- Selecione --"] + opcoes

        with st.expander(f"**{qid} - {titulo}**", expanded=False):
            # Campo de Resposta
            opcao_sel = st.selectbox(
                f"Resposta para {qid}",
                options=opcoes_com_vazio,
                index=idx_padrao,
                key=f"select_ieduc_{ano}_{qid}"
            )

            # Evidência / Link
            link_input = st.text_input(
                "Link da Evidência / Comprovação:",
                value=link_atual,
                key=f"link_ieduc_{ano}_{qid}"
            )

            # Observações adicionais
            obs_input = st.text_area(
                "Observações / Justificativa:",
                value=obs_atual,
                key=f"obs_ieduc_{ano}_{qid}"
            )

            # Ação de Salvar por Quesito
            if st.button(f"Salvar Quesito {qid}", key=f"btn_save_ieduc_{ano}_{qid}", type="primary"):
                if opcao_sel != "-- Selecione --":
                    pts = float(pontos_map.get(opcao_sel, 0.0))
                    
                    sucesso = save_resp_ieduc(
                        qid=qid,
                        valor=opcao_sel,
                        pontos=pts,
                        link=link_input,
                        comentario=obs_input
                    )
                    
                    if sucesso:
                        st.toast(f"Quesito {qid} salvo com sucesso!", icon="✅")
                        
                        # Modal de link
                        links = re.findall(r'https?://[^\s]+', link_input)
                        if links and "modal_aviso_link" in globals():
                            modal_aviso_link(qid, links, ano)
                            
                        st.rerun()
                else:
                    st.warning("Selecione uma opção válida antes de salvar.")

            # INTEGRAÇÃO DO DIÁLOGO INTERNO / HISTÓRICO DE COMENTÁRIOS
            bloco_comentarios_ieduc(qid, respostas)

# =============================================================================
# CONFIGURAÇÃO DE ESTILOS PADRÃO PARA RELATÓRIOS PDF (i-Educ)
# =============================================================================
styles = getSampleStyleSheet()

# --- ESTILOS DE CAPA ---
style_titulo_capa = ParagraphStyle(
    "TituloCapaIEduc",
    parent=styles["Normal"],
    fontName="Helvetica-Bold",
    fontSize=24,
    leading=28,
    alignment=TA_CENTER,
    textColor=colors.HexColor("#1E3A8A"),  # Azul escuro institucional (i-Educ)
    spaceAfter=15,
)

style_subtitulo_capa = ParagraphStyle(
    "SubtituloCapaIEduc",
    parent=styles["Normal"],
    fontName="Helvetica",
    fontSize=14,
    leading=18,
    alignment=TA_CENTER,
    textColor=colors.HexColor("#4B5563"),
    spaceAfter=30,
)

