import html
import json
import logging
import os
import re
import sys
import warnings
from datetime import date, datetime
from io import BytesIO

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
    
    qid_key = str(qid).replace('.', '_')
    chave_gatilho = f"gatilho_modal_{qid_key}_{ano_sel}"
    
    if st.button("Confirmo que o link está liberado para o público", key=f"btn_conf_{qid_key}_{ano_sel}", type="primary"):
        st.session_state[chave_gatilho] = False
        st.rerun()


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

    st.session_state[key_ano][str(qid)] = {
        "valor": str(valor or ""),
        "pontos": float(pontos or 0.0),
        "link": str(link or ""),
        "comentarios": comentarios,
        "comentario": str(comentario or ""),
        "detalhes": dados_detalhes,
        "atualizado_em": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

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

        if st.session_state[key_estado_limpar]:
            st.session_state[key_texto] = ""
            st.session_state[key_estado_limpar] = False

        novo_texto = st.text_area("Novo comentário:", key=key_texto, height=70, label_visibility="collapsed")

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
# 4. RENDERIZADOR DE QUESITOS E FORMULÁRIO
# =============================================================================

def render_modulo_ieduc(questoes_ieduc: list):
    """Interface principal do módulo i-Educ."""
    st.title("🎓 i-Educ - Índice de Educação")
    
    render_dashboard_ieduc(questoes_ieduc)

    ano = get_ano_atual_ieduc()
    respostas = load_respostas_ieduc(ano)

    st.subheader("Formulário de Avaliação")

    for questao in questoes_ieduc:
        qid = str(questao["id"])
        titulo = questao.get("titulo", f"Quesito {qid}")
        opcoes = questao.get("opcoes", ["Sim", "Não"])
        pontos_map = questao.get("pontos_map", {})
        
        resp_salva = respostas.get(qid, {})
        val_atual = resp_salva.get("valor", "")
        link_atual = resp_salva.get("link", "")
        obs_atual = resp_salva.get("comentario", "")

        idx_padrao = 0
        if val_atual in opcoes:
            idx_padrao = opcoes.index(val_atual) + 1

        opcoes_com_vazio = ["-- Selecione --"] + opcoes

        with st.expander(f"**{qid} - {titulo}**", expanded=False):
            opcao_sel = st.selectbox(
                f"Resposta para {qid}",
                options=opcoes_com_vazio,
                index=idx_padrao,
                key=f"select_ieduc_{ano}_{qid}"
            )

            link_input = st.text_input(
                "Link da Evidência / Comprovação:",
                value=link_atual,
                key=f"link_ieduc_{ano}_{qid}"
            )

            obs_input = st.text_area(
                "Observações / Justificativa:",
                value=obs_atual,
                key=f"obs_ieduc_{ano}_{qid}"
            )

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
                        
                        links = re.findall(r'https?://[^\s]+', link_input)
                        if links and "modal_aviso_link" in globals():
                            modal_aviso_link(qid, links, ano)
                            
                        st.rerun()
                else:
                    st.warning("Selecione uma opção válida antes de salvar.")

            bloco_comentarios_ieduc(qid, respostas)

# =============================================================================
# ESTRUTURA DE DADOS PADRÃO (FALLBACK PARA QUESITOS DO I-EDUC)
# =============================================================================
QUESTOES_IEDUC_PADRAO = [
    {
        "id": "EDUC-01",
        "titulo": "Plano Municipal de Educação (PME) vigente e atualizado",
        "opcoes": ["Sim", "Não"],
        "pontos_map": {"Sim": 100.0, "Não": 0.0},
    },
    {
        "id": "EDUC-02",
        "titulo": "Cumprimento das metas de cobertura em creches e pré-escola",
        "opcoes": ["Totalmente", "Parcialmente", "Não atende"],
        "pontos_map": {"Totalmente": 100.0, "Parcialmente": 50.0, "Não atende": 0.0},
    },
    {
        "id": "EDUC-03",
        "titulo": "Disponibilização de transporte escolar com frota regularizada",
        "opcoes": ["Sim", "Não"],
        "pontos_map": {"Sim": 100.0, "Não": 0.0},
    },
]

# =============================================================================
# HELPER DE ANO ATUAL
# =============================================================================
def get_ano_atual_ieduc() -> int:
    """Retorna o ano selecionado no session_state ou o padrão atual."""
    return st.session_state.get("ano_referencia_ieduc", 2024)

# =============================================================================
# 4. SIDEBAR - i-Educ
# =============================================================================

def zerar_questionario_ieduc(ano: int):
    """Deleta todas as respostas do ano selecionado na tabela respostas_ieduc."""
    try:
        if "get_connection" in globals():
            with get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "DELETE FROM respostas_ieduc WHERE ano = %s",
                        (int(ano),),
                    )
                conn.commit()
        st.cache_data.clear()  # Limpa o cache após deletar
    except Exception as e:
        logging.error(f"Erro ao zerar questionário i-Educ: {e}")
        st.error(f"Erro ao zerar questionário i-Educ: {e}")


@st.dialog("⚠️ Zerar Respostas do i-Educ")
def confirmar_zerar_dialog_ieduc(ano):
    st.warning(
        f"Tem certeza que deseja apagar TODAS as respostas do i-Educ para o ano {ano}?"
    )
    st.write(
        "Esta ação é irreversível e excluirá os dados salvos no banco Neon."
    )

    # Campo para inserção da senha de confirmação
    senha_digitada = st.text_input(
        "Digite a senha de confirmação para prosseguir:",
        type="password",
        placeholder="Digite a senha...",
    )

    col1, col2 = st.columns(2)
    with col1:
        if st.button(
            "🔴 Sim, Zerar Tudo", type="primary", use_container_width=True
        ):
            if senha_digitada.strip() == "fidelios":
                try:
                    zerar_questionario_ieduc(ano)

                    # Limpa a sessão
                    key_ano = f"respostas_ieduc_{ano}"
                    st.session_state[key_ano] = {}

                    st.toast(
                        "Respostas do i-Educ zeradas com sucesso!", icon="🗑️"
                    )
                    st.rerun()
                except Exception as e:
                    st.error(f"Erro ao zerar banco: {e}")
            else:
                st.error("🔒 Senha incorreta! Ação cancelada.")

    with col2:
        if st.button("Cancelar", use_container_width=True):
            st.rerun()


def render_sidebar_ieduc():
    st.sidebar.title("🎓 Painel de Controle - i-Educ")
    anos = [2024, 2025, 2026, 2027, 2028, 2029, 2030]

    # Seleção do ano no session_state
    ano_sel = st.sidebar.selectbox(
        "Ano de Referência:", anos, key="ano_referencia_ieduc"
    )

    if "load_respostas_ieduc" in globals():
        res_data = load_respostas_ieduc(ano_sel)
    elif "load_respostas" in globals():
        res_data = load_respostas(ano_sel)
    else:
        res_data = st.session_state.get(f"respostas_ieduc_{ano_sel}", {})

    total_pts = sum(
        float(item.get("pontos", 0.0))
        for item in res_data.values()
        if isinstance(item, dict)
    )

    # Régua de Classificação IEGM / i-Educ
    if total_pts <= 500:
        faixa, cor = "C", "red"
    elif total_pts <= 599:
        faixa, cor = "C+", "orange"
    elif total_pts <= 749:
        faixa, cor = "B", "#d4d400"
    elif total_pts <= 899:
        faixa, cor = "B+", "lightgreen"
    else:
        faixa, cor = "A", "green"

    st.sidebar.metric("Pontuação Total i-Educ", f"{total_pts:.1f} pts")
    st.sidebar.markdown(
        f"**Faixa:** <span style='color:{cor}; font-size:18px; font-weight:bold;'>{faixa}</span>",
        unsafe_allow_html=True,
    )

    st.sidebar.divider()

    col1, col2 = st.sidebar.columns(2)

    # Botão de Download direto
    with col1:
        pdf_bytes = b""
        if "gerar_relatorio_pdf_ieduc" in globals():
            res_pdf = gerar_relatorio_pdf_ieduc(
                res_data, ano_sel, total_pts, faixa
            )
            pdf_bytes = (
                res_pdf.getvalue()
                if hasattr(res_pdf, "getvalue")
                else res_pdf
            )
        elif "gerar_relatorio_pdf" in globals():
            res_pdf = gerar_relatorio_pdf(res_data, ano_sel, total_pts, faixa)
            pdf_bytes = (
                res_pdf.getvalue()
                if hasattr(res_pdf, "getvalue")
                else res_pdf
            )

        st.download_button(
            label="📄 Baixar PDF",
            data=pdf_bytes,
            file_name=f"Relatorio_iEduc_{ano_sel}.pdf",
            mime="application/pdf",
            use_container_width=True,
            disabled=(pdf_bytes == b""),
        )

    # Botão para abrir o Modal de confirmação
    with col2:
        if st.button(
            "🔄 Zerar",
            help="Limpar todas as respostas do ano selecionado",
            use_container_width=True,
        ):
            confirmar_zerar_dialog_ieduc(ano_sel)

    return total_pts, res_data, ano_sel


# =============================================================================
# 5. GRÁFICOS E HISTÓRICO - i-Educ
# =============================================================================

def get_all_years_data_ieduc() -> dict:
    """Busca o histórico de dados de todos os anos salvos na tabela respostas_ieduc e session_state."""
    all_data = {}

    # 1. Carrega via Banco
    try:
        if "get_connection" in globals():
            with get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "SELECT DISTINCT ano FROM respostas_ieduc ORDER BY ano"
                    )
                    anos_banco = [row[0] for row in cursor.fetchall()]
                    for a in anos_banco:
                        all_data[a] = (
                            load_respostas_ieduc(a)
                            if "load_respostas_ieduc" in globals()
                            else load_respostas(a)
                        )
    except Exception as e:
        logging.error(
            f"Erro ao buscar histórico de anos i-Educ no banco: {e}"
        )

    # 2. Carrega via Session State (para capturar anos ainda não persistidos)
    prefixo = "respostas_ieduc_"
    for key in list(st.session_state.keys()):
        if key.startswith(prefixo):
            try:
                ano = int(key.replace(prefixo, ""))
                if ano not in all_data or not all_data[ano]:
                    all_data[ano] = st.session_state[key]
            except ValueError:
                continue

    return all_data


def get_faixa_ieduc(total: float) -> str:
    if total <= 500:
        return "C - Inefetivo"
    if total <= 599:
        return "C+ - Em Adequação"
    if total <= 749:
        return "B - Efetivo"
    if total <= 899:
        return "B+ - Muito Efetivo"
    return "A - Altamente Efetivo"


def grafico_pontos_por_ano_ieduc(all_data):
    """Gráfico de barras vertical com pontos totais por ano para o i-Educ."""
    anos = sorted(all_data.keys())
    totais = []
    cores = []

    for ano in anos:
        res = all_data[ano]
        total = sum(
            float(v.get("pontos", 0.0))
            for k, v in res.items()
            if isinstance(v, dict) and not str(k).startswith("COM_")
        )
        totais.append(total)

        if total <= 500:
            cores.append("#ef4444")  # Vermelho
        elif total <= 599:
            cores.append("#f97316")  # Laranja
        elif total <= 749:
            cores.append("#eab308")  # Amarelo
        elif total <= 899:
            cores.append("#84cc16")  # Verde Claro
        else:
            cores.append("#16a34a")  # Verde Escuro

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=[str(a) for a in anos],
            y=totais,
            marker_color=cores,
            text=[f"{t:.1f} pts" for t in totais],
            textposition="outside",
            hovertemplate="<b>Ano: %{x}</b><br>i-Educ Total: %{y:.1f} pts<extra></extra>",
        )
    )

    fig.update_layout(
        title="Índice Histórico i-Educ (Gestão Educacional) por Exercício",
        xaxis_title="Ano",
        yaxis_title="Pontuação i-Educ",
        plot_bgcolor="white",
        paper_bgcolor="white",
        showlegend=False,
        height=400,
    )

    return fig


def render_graficos_ieduc(res_data_atual=None, ano_sel=None):
    st.header("📊 Painel de Análise do i-Educ")

    all_data = get_all_years_data_ieduc()

    if not all_data:
        st.info(
            "Nenhum dado do i-Educ registrado ainda. Preencha os itens para visualizar os gráficos."
        )
        return

    st.plotly_chart(
        grafico_pontos_por_ano_ieduc(all_data), use_container_width=True
    )


# =============================================================================
# 6. RENDERIZADOR DE FORMULÁRIO E QUESITOS
# =============================================================================

def render_modulo_ieduc(questoes_ieduc: list):
    """Interface principal dos quesitos do módulo i-Educ."""
    # Recupera a função de ano de forma segura
    get_ano_func = globals().get("get_ano_atual_ieduc", lambda: "2024")
    ano = get_ano_func()
    
    # Carregamento das respostas
    if "load_respostas_ieduc" in globals():
        respostas = load_respostas_ieduc(ano)
    else:
        respostas = st.session_state.get(f"respostas_ieduc_{ano}", {})

    st.subheader("Formulário de Avaliação")

    # -------------------------------------------------------------------------
    # 📌 CALL/RENDER DO QUESITO 1.0 CUSTOMIZADO (Destaque/Layout Padrão iGov)
    # -------------------------------------------------------------------------
    render_questao_1_0_ieduc(respostas, ano)

    # -------------------------------------------------------------------------
    # 📋 RENDERIZADOR GENÉRICO PARA OS DEMAIS QUESITOS (2.0, 3.0, ETC.)
    # -------------------------------------------------------------------------
    for questao in questoes_ieduc:
        qid = str(questao.get("id", ""))
        
        # Ignora o ID "1.0" ou "1" no loop genérico para não duplicar o Quesito 1.0 na tela
        if qid in ["1.0", "1"]:
            continue

        titulo = questao.get("titulo", f"Quesito {qid}")
        opcoes = questao.get("opcoes", ["Sim", "Não"])
        pontos_map = questao.get("pontos_map", {})

        resp_salva = respostas.get(qid, {})
        val_atual = resp_salva.get("valor", "")
        link_atual = resp_salva.get("link", "")
        obs_atual = resp_salva.get("comentario", "")

        idx_padrao = 0
        if val_atual in opcoes:
            idx_padrao = opcoes.index(val_atual) + 1

        opcoes_com_vazio = ["-- Selecione --"] + opcoes

        with st.expander(f"**{qid} - {titulo}**", expanded=False):
            opcao_sel = st.selectbox(
                f"Resposta para {qid}",
                options=opcoes_com_vazio,
                index=idx_padrao,
                key=f"select_ieduc_{ano}_{qid}",
            )

            link_input = st.text_input(
                "Link da Evidência / Comprovação:",
                value=link_atual,
                key=f"link_ieduc_{ano}_{qid}",
            )

            obs_input = st.text_area(
                "Observações / Justificativa:",
                value=obs_atual,
                key=f"obs_ieduc_{ano}_{qid}",
            )

            if st.button(
                f"Salvar Quesito {qid}",
                key=f"btn_save_ieduc_{ano}_{qid}",
                type="primary",
            ):
                if opcao_sel != "-- Selecione --":
                    pts = float(pontos_map.get(opcao_sel, 0.0))

                    if "save_resp_ieduc" in globals():
                        sucesso = save_resp_ieduc(
                            qid=qid,
                            valor=opcao_sel,
                            pontos=pts,
                            link=link_input,
                            comentario=obs_input,
                        )
                    else:
                        key_ano = f"respostas_ieduc_{ano}"
                        if key_ano not in st.session_state:
                            st.session_state[key_ano] = {}
                        st.session_state[key_ano][qid] = {
                            "valor": opcao_sel,
                            "pontos": pts,
                            "link": link_input,
                            "comentario": obs_input,
                        }
                        sucesso = True

                    if sucesso:
                        st.toast(f"Quesito {qid} salvo com sucesso!", icon="✅")

                        links = re.findall(r"https?://[^\s]+", link_input)
                        if links and "modal_aviso_link" in globals():
                            modal_aviso_link(qid, links, ano)

                        st.rerun()
                else:
                    st.warning("Selecione uma opção válida antes de salvar.")


import re
import streamlit as st
# =============================================================================
# 6. FORMULÁRIO PRINCIPAL - iEduc
# =============================================================================

def mostrar_formulario_educ(questoes: list = None):
    """Renderiza a interface principal do módulo i-Educ (Gestão Educacional).

    Gerencia a barra lateral, abas de navegação, carregamento de dados
    e renderização sequencial dos quesitos exatamente na ordem do arquivo.
    """
    # Carregamento do estado e da barra lateral
    total_pts, res_data, ano_sel = render_sidebar_ieduc()

    # Título principal da página
    st.title(f"🎓 Educação (i-Educ) - Exercício {ano_sel}")

    # Estrutura de abas principal
    aba_quest, aba_dados_ext, aba_graf = st.tabs(
        ["📋 Questionário i-Educ", "🌐 Dados Externos", "📊 Gráficos"]
    )

    with aba_quest:
        # Pega as funções exatamente na ordem de declaração no arquivo (sem sort)
        funcoes_questoes = [
            nome for nome in globals()
            if nome.startswith("render_questao_") and callable(globals()[nome])
        ]

        if funcoes_questoes:
            for nome_func in funcoes_questoes:
                globals()[nome_func](res_data, ano_sel)
        else:
            st.info("Nenhum quesito cadastrado até o momento.")
            
# =============================================================================
# QUESITO 1.0 • OFERTA DE CRECHE (INFORMATIVO)
# =============================================================================

def render_questao_1_0_ieduc(res_data: dict, ano_sel: str):
    """Renderiza a Questão 1.0 (Oferta de Creche) - Quesito Informativo."""
    
    regex_url = globals().get("REGEX_PURE_URL", r'https?://[^\s]+')

    with st.container(key=f"container_bloco_ieduc_1_0_{ano_sel}", border=True):
        with st.expander(f"📌 Questão 1.0 • Oferta de Creche ({ano_sel})", expanded=True):
            st.subheader("1.0 • Infraestrutura da Educação Infantil")
            st.write("**A Prefeitura municipal oferece Creche?**")
            st.caption("ℹ️ *Preencha os campos abaixo e clique no botão 'Salvar Questão 1.0' para registrar.*")

            opcoes_10 = {
                "Selecione...": 0.0,
                "Sim": 0.0,
                "Não": 0.0
            }

            d10 = res_data.get("1.0") or {
                "valor": "Selecione...",
                "pontos": 0.0,
                "link": "",
                "comentarios": [],
                "comentario": ""
            }
            v_salvo_10 = d10.get("valor", "Selecione...")

            if v_salvo_10 not in opcoes_10:
                v_salvo_10 = "Selecione..."

            evidencia_10_salva = d10.get("link", "")

            chave_radio_10 = f"r_10_{ano_sel}"
            chave_link_10 = f"l_10_txt_{ano_sel}"

            c10_1, c10_2 = st.columns([1, 1])
            
            with c10_1:
                lista_opcoes_10 = list(opcoes_10.keys())
                idx_10 = lista_opcoes_10.index(v_salvo_10) if v_salvo_10 in lista_opcoes_10 else 0

                val_radio_10 = st.radio(
                    "Selecione a situação da Oferta de Creche:",
                    options=lista_opcoes_10,
                    index=idx_10,
                    key=chave_radio_10,
                )

            with c10_2:
                link_10 = st.text_area(
                    "Link de Evidência (Lei, Decreto, Fotos, Matrículas, etc.):",
                    value=evidencia_10_salva,
                    key=chave_link_10,
                    placeholder="Insira o link oficial das evidências referente ao quesito 1.0...",
                    height=100,
                )
                
                placeholder_links_10 = st.empty()
                links_10_visuais = re.findall(regex_url, link_10 or "")
                
                if links_10_visuais:
                    links_formatados = [
                        f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                        for u in links_10_visuais
                    ]
                    placeholder_links_10.markdown("**🔗 Link ativo:** " + " | ".join(links_formatados))

            bloco_comentarios_func = globals().get("bloco_comentarios_ieduc", globals().get("bloco_comentarios"))
            if bloco_comentarios_func:
                bloco_comentarios_func("1.0", res_data, ano_sel)

            if st.button("💾 Salvar Questão 1.0", key=f"btn_salvar_1_0_{ano_sel}", type="primary"):
                val_salvar = st.session_state.get(chave_radio_10, v_salvo_10)
                pts_10 = 0.0
                lnk_val = link_10.strip()

                comentarios_historico = d10.get("comentarios", [])
                comentario_simples = d10.get("comentario", "")

                save_resp_func = globals().get("save_resp_ieduc", globals().get("save_resp"))
                if save_resp_func:
                    save_resp_func(
                        qid="1.0",
                        valor=val_salvar,
                        pontos=pts_10,
                        link=lnk_val,
                        comentario=comentario_simples,
                        comentarios=comentarios_historico
                    )

                links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(regex_url, lnk_val or "")]
                links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(regex_url, evidencia_10_salva or "")]

                if lnk_val != evidencia_10_salva and links_atuais and links_atuais != links_antigos:
                    st.session_state[f"links_pendentes_1_0_{ano_sel}"] = links_atuais
                    st.session_state[f"gatilho_modal_1_0_{ano_sel}"] = True

                st.cache_data.clear()
                st.toast("Resposta e histórico do Quesito 1.0 salvos com sucesso!", icon="✅")
                st.rerun()

            st.markdown(
                "<span style='color:#6c757d; font-weight:bold;'>"
                "ℹ️ Status: Questão Informativa (Sem impacto na pontuação global)</span>",
                unsafe_allow_html=True,
            )

    if st.session_state.get(f"gatilho_modal_1_0_{ano_sel}", False):
        modal_aviso_func = globals().get("modal_aviso_link")
        if modal_aviso_func:
            modal_aviso_func("1.0", st.session_state.get(f"links_pendentes_1_0_{ano_sel}", []), ano_sel)


# =============================================================================
# QUESITO 1.1 • BRINQUEDOS NO PÁTIO INFANTIL (INFORMATIVO)
# =============================================================================

def render_questao_1_1_ieduc(res_data: dict, ano_sel: str):
    """Renderiza a Questão 1.1 (Brinquedos no Pátio) - Quesito Informativo."""
    
    regex_url = globals().get("REGEX_PURE_URL", r'https?://[^\s]+')

    with st.container(key=f"container_bloco_ieduc_1_1_{ano_sel}", border=True):
        with st.expander(f"📌 Questão 1.1 • Brinquedos no Pátio Infantil ({ano_sel})", expanded=True):
            st.subheader("1.1 • Infraestrutura da Educação Infantil")
            st.write("**Algum estabelecimento que oferece Creche possui brinquedos no Pátio Infantil?**")
            st.caption("ℹ️ *Preencha os campos abaixo e clique no botão 'Salvar Questão 1.1' para registrar.*")

            opcoes_11 = {
                "Selecione...": 0.0,
                "Sim": 0.0,
                "Não": 0.0
            }

            d11 = res_data.get("1.1") or {
                "valor": "Selecione...",
                "pontos": 0.0,
                "link": "",
                "comentarios": [],
                "comentario": ""
            }
            v_salvo_11 = d11.get("valor", "Selecione...")

            if v_salvo_11 not in opcoes_11:
                v_salvo_11 = "Selecione..."

            evidencia_11_salva = d11.get("link", "")

            chave_radio_11 = f"r_11_{ano_sel}"
            chave_link_11 = f"l_11_txt_{ano_sel}"

            c11_1, c11_2 = st.columns([1, 1])
            
            with c11_1:
                lista_opcoes_11 = list(opcoes_11.keys())
                idx_11 = lista_opcoes_11.index(v_salvo_11) if v_salvo_11 in lista_opcoes_11 else 0

                val_radio_11 = st.radio(
                    "Selecione a situação dos Brinquedos no Pátio:",
                    options=lista_opcoes_11,
                    index=idx_11,
                    key=chave_radio_11,
                )

            with c11_2:
                link_11 = st.text_area(
                    "Link de Evidência (Fotos, Relatórios, Termos de Vistoria, etc.):",
                    value=evidencia_11_salva,
                    key=chave_link_11,
                    placeholder="Insira o link oficial das evidências referente ao quesito 1.1...",
                    height=100,
                )
                
                placeholder_links_11 = st.empty()
                links_11_visuais = re.findall(regex_url, link_11 or "")
                
                if links_11_visuais:
                    links_formatados = [
                        f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                        for u in links_11_visuais
                    ]
                    placeholder_links_11.markdown("**🔗 Link ativo:** " + " | ".join(links_formatados))

            bloco_comentarios_func = globals().get("bloco_comentarios_ieduc", globals().get("bloco_comentarios"))
            if bloco_comentarios_func:
                bloco_comentarios_func("1.1", res_data, ano_sel)

            if st.button("💾 Salvar Questão 1.1", key=f"btn_salvar_1_1_{ano_sel}", type="primary"):
                val_salvar = st.session_state.get(chave_radio_11, v_salvo_11)
                pts_11 = 0.0
                lnk_val = link_11.strip()

                comentarios_historico = d11.get("comentarios", [])
                comentario_simples = d11.get("comentario", "")

                save_resp_func = globals().get("save_resp_ieduc", globals().get("save_resp"))
                if save_resp_func:
                    save_resp_func(
                        qid="1.1",
                        valor=val_salvar,
                        pontos=pts_11,
                        link=lnk_val,
                        comentario=comentario_simples,
                        comentarios=comentarios_historico
                    )

                links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(regex_url, lnk_val or "")]
                links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(regex_url, evidencia_11_salva or "")]

                if lnk_val != evidencia_11_salva and links_atuais and links_atuais != links_antigos:
                    st.session_state[f"links_pendentes_1_1_{ano_sel}"] = links_atuais
                    st.session_state[f"gatilho_modal_1_1_{ano_sel}"] = True

                st.cache_data.clear()
                st.toast("Resposta e histórico do Quesito 1.1 salvos com sucesso!", icon="✅")
                st.rerun()

            st.markdown(
                "<span style='color:#6c757d; font-weight:bold;'>"
                "ℹ️ Status: Questão Informativa (Sem impacto na pontuação global)</span>",
                unsafe_allow_html=True,
            )

    if st.session_state.get(f"gatilho_modal_1_1_{ano_sel}", False):
        modal_aviso_func = globals().get("modal_aviso_link")
        if modal_aviso_func:
            modal_aviso_func("1.1", st.session_state.get(f"links_pendentes_1_1_{ano_sel}", []), ano_sel)

# =============================================================================
# QUESITO 1.1.1 • BRINQUEDOS NO PÁTIO INFANTIL - CÁLCULO BPI (IEDUC)
# =============================================================================

def render_questao_1_1_1_ieduc(res_data: dict, ano_sel: str):
    """Renderiza a Questão 1.1.1 (Cálculo de Brinquedos no Pátio Infantil - BPI)."""
    
    regex_url = globals().get("REGEX_PURE_URL", r'https?://[^\s]+')

    with st.container(key=f"container_bloco_ieduc_1_1_1_{ano_sel}", border=True):
        with st.expander(f"📌 Questão 1.1.1 • Dados de Brinquedos no Pátio Infantil (BPI) ({ano_sel})", expanded=True):
            st.subheader("1.1.1 • Infraestrutura da Educação Infantil")
            st.write("**Informe os dados para o cálculo de brinquedos no Pátio Infantil (BPI):**")
            st.caption("ℹ️ *Preencha os campos abaixo e clique no botão 'Salvar Questão 1.1.1' para registrar.*")

            # Recupera os dados salvos ou define o padrão
            d111 = res_data.get("1.1.1") or {
                "valor": "BPI:0,TOTAL:0",
                "pontos": 0.0,
                "link": "",
                "comentarios": [],
                "comentario": ""
            }

            # Faz o split seguro para carregar os dois campos
            try:
                parts_111 = str(d111.get("valor", "")).split(",")
                v_bpi_input = int(parts_111[0].split(":")[1])
                v_total_input = int(parts_111[1].split(":")[1])
            except Exception:
                v_bpi_input, v_total_input = 0, 0

            evidencia_111_salva = d111.get("link", "")

            chave_bpi_111 = f"q111_bpi_val_{ano_sel}"
            chave_total_111 = f"q111_total_val_{ano_sel}"
            chave_link_111 = f"l_111_txt_{ano_sel}"

            c111_1, c111_2 = st.columns([1, 1])

            with c111_1:
                bpi_input = st.number_input(
                    "Nº de creches com brinquedos no pátio infantil:",
                    min_value=0,
                    step=1,
                    value=v_bpi_input,
                    key=chave_bpi_111,
                )

                total_input = st.number_input(
                    "Nº TOTAL de creches no município:",
                    min_value=0,
                    step=1,
                    value=v_total_input,
                    key=chave_total_111,
                )

                # Cálculo proporcional da Pontuação (Máximo: 2.0 pts)
                pts_111 = 0.0
                if total_input > 0:
                    proporcao_p = bpi_input / total_input
                    pts_111 = float(min(2.0, proporcao_p * 2.0))

            with c111_2:
                link_111 = st.text_area(
                    "Link de Evidência (Fotos, Vistorias, Inventário, etc.):",
                    value=evidencia_111_salva,
                    key=chave_link_111,
                    placeholder="Insira o link oficial das evidências referente ao quesito 1.1.1...",
                    height=140,
                )

                placeholder_links_111 = st.empty()
                links_111_visuais = re.findall(regex_url, link_111 or "")

                if links_111_visuais:
                    links_formatados = [
                        f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})"
                        for u in links_111_visuais
                    ]
                    placeholder_links_111.markdown("**🔗 Link ativo:** " + " | ".join(links_formatados))

            # Exibição do resultado do cálculo
            st.markdown(
                f"📊 **Pontuação Calculada na Questão 1.1.1:** `{pts_111:.2f} pontos` *(Máximo: 2.0 pontos)*"
            )

            # Bloco de Comentários
            bloco_comentarios_func = globals().get("bloco_comentarios_ieduc", globals().get("bloco_comentarios"))
            if bloco_comentarios_func:
                bloco_comentarios_func("1.1.1", res_data, ano_sel)

            # Botão de Salvamento
            if st.button("💾 Salvar Questão 1.1.1", key=f"btn_salvar_1_1_1_{ano_sel}", type="primary"):
                str_valor_111 = f"BPI:{bpi_input},TOTAL:{total_input}"
                lnk_val = link_111.strip()

                comentarios_historico = d111.get("comentarios", [])
                comentario_simples = d111.get("comentario", "")

                save_resp_func = globals().get("save_resp_ieduc", globals().get("save_resp"))
                if save_resp_func:
                    save_resp_func(
                        qid="1.1.1",
                        valor=str_valor_111,
                        pontos=pts_111,
                        link=lnk_val,
                        comentario=comentario_simples,
                        comentarios=comentarios_historico
                    )

                links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(regex_url, lnk_val or "")]
                links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(regex_url, evidencia_111_salva or "")]

                if lnk_val != evidencia_111_salva and links_atuais and links_atuais != links_antigos:
                    st.session_state[f"links_pendentes_1_1_1_{ano_sel}"] = links_atuais
                    st.session_state[f"gatilho_modal_1_1_1_{ano_sel}"] = True

                st.cache_data.clear()
                st.toast("Resposta e histórico do Quesito 1.1.1 salvos com sucesso!", icon="✅")
                st.rerun()

    if st.session_state.get(f"gatilho_modal_1_1_1_{ano_sel}", False):
        modal_aviso_func = globals().get("modal_aviso_link")
        if modal_aviso_func:
            modal_aviso_func("1.1.1", st.session_state.get(f"links_pendentes_1_1_1_{ano_sel}", []), ano_sel)

# =============================================================================
# QUESITO 1.1.2 • MANUTENÇÃO DAS CRECHES (IEDUC)
# =============================================================================

def render_questao_1_1_2_ieduc(res_data: dict, ano_sel: str):
    """Renderiza a Questão 1.1.2 (Manutenção das Creches)."""
    
    regex_url = globals().get("REGEX_PURE_URL", r'https?://[^\s]+')

    with st.container(key=f"container_bloco_ieduc_1_1_2_{ano_sel}", border=True):
        with st.expander(f"📌 Questão 1.1.2 • Manutenção das Creches ({ano_sel})", expanded=True):
            st.subheader("1.1.2 • Manutenção das Creches")
            st.write("**Informe os dados para o cálculo de manutenção das creches:**")
            st.markdown("""
            *Fórmulas de cálculo:*
            * $P1 = (NMANU / TOTAL) \times Pmáx1$ *(Pmáx1 = -2 pontos)*
            * $P2 = (NCRON / TOTAL) \times Pmáx2$ *(Pmáx2 = 1 ponto)*
            * $P3 = (CRON / TOTAL) \times Pmáx3$ *(Pmáx3 = 3 pontos)*
            * $P = P1 + P2 + P3$
            """)
            st.caption("ℹ️ *Preencha os dados abaixo e clique no botão 'Salvar Questão 1.1.2' para registrar.*")

            d112 = res_data.get("1.1.2") or {
                "valor": "CRON:0,NCRON:0,SOLIC:0,NMANU:0,TOTAL:0",
                "pontos": 0.0,
                "link": "",
                "comentarios": [],
                "comentario": ""
            }
            v_banco_112 = d112.get("valor", "CRON:0,NCRON:0,SOLIC:0,NMANU:0,TOTAL:0")
            evidencia_112_salva = d112.get("link", "")

            # Parse seguro dos campos numéricos do banco de dados
            try:
                parts_m = v_banco_112.split(",")
                v_cron = int(parts_m[0].split(":")[1])
                v_ncron = int(parts_m[1].split(":")[1])
                v_solic = int(parts_m[2].split(":")[1])
                v_nmanu = int(parts_m[3].split(":")[1])
            except Exception:
                v_cron, v_ncron, v_solic, v_nmanu = 0, 0, 0, 0

            # Chaves únicas para os inputs
            k_cron = f"q112_cron_{ano_sel}"
            k_ncron = f"q112_ncron_{ano_sel}"
            k_solic = f"q112_solic_{ano_sel}"
            k_nmanu = f"q112_nmanu_{ano_sel}"
            chave_link_112 = f"l_112_txt_{ano_sel}"

            c112_1, c112_2 = st.columns([1, 1])

            with c112_1:
                cron_val = st.number_input(
                    "Quantas creches possuem e CUMPRIRAM o cronograma de manutenção preventiva (CRON):",
                    min_value=0, step=1, value=v_cron, key=k_cron
                )
                ncron_val = st.number_input(
                    "Quantas creches possuem e NÃO CUMPRIRAM o cronograma de manutenção preventiva (NCRON):",
                    min_value=0, step=1, value=v_ncron, key=k_ncron
                )
                solic_val = st.number_input(
                    "Quantas creches realizam manutenção/troca SOMENTE por solicitação (SOLIC):",
                    min_value=0, step=1, value=v_solic, key=k_solic
                )
                nmanu_val = st.number_input(
                    "Quantas creches NÃO realizam manutenção/troca dos brinquedos (NMANU):",
                    min_value=0, step=1, value=v_nmanu, key=k_nmanu
                )

                total_calculado = cron_val + ncron_val + solic_val + nmanu_val
                st.markdown('<label style="font-size: 13px; font-weight: 600; color: #1E3A8A;">Total de Creches (Somatório Automático):</label>', unsafe_allow_html=True)
                st.number_input("", value=int(total_calculado), disabled=True, key=f"disabled_total_112_{ano_sel}", label_visibility="collapsed")

            with c112_2:
                link_112 = st.text_area(
                    "Link de Evidência (Relatórios, Contratos, Ordens de Serviço, etc.):",
                    value=evidencia_112_salva,
                    key=chave_link_112,
                    placeholder="Insira o link oficial das evidências referente ao quesito 1.1.2...",
                    height=280,
                )

                placeholder_links_112 = st.empty()
                links_112_visuais = re.findall(regex_url, link_112 or "")

                if links_112_visuais:
                    links_formatados = [
                        f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                        for u in links_112_visuais
                    ]
                    placeholder_links_112.markdown("**🔗 Link ativo:** " + " | ".join(links_formatados))

            # Cálculo de pontuação prévia na tela
            pts_112 = 0.0
            if total_calculado > 0:
                p1 = (nmanu_val / total_calculado) * (-2.0)
                p2 = (ncron_val / total_calculado) * 1.0
                p3 = (cron_val / total_calculado) * 3.0
                pts_112 = float(max(0.0, p1 + p2 + p3))
                st.code(f"📊 Pontuação Calculada no Quesito 1.1.2: {pts_112:.2f} pontos / 3.0 pontos máximos.", language="text")
            else:
                st.code("💡 Insira os quantitativos para realizar o cálculo dinâmico ponderado da nota.", language="text")

            bloco_comentarios_func = globals().get("bloco_comentarios_ieduc", globals().get("bloco_comentarios"))
            if bloco_comentarios_func:
                bloco_comentarios_func("1.1.2", res_data, ano_sel)

            if st.button("💾 Salvar Questão 1.1.2", key=f"btn_salvar_1_1_2_{ano_sel}", type="primary"):
                str_valor_salvar = f"CRON:{cron_val},NCRON:{ncron_val},SOLIC:{solic_val},NMANU:{nmanu_val},TOTAL:{total_calculado}"
                lnk_val = link_112.strip()

                comentarios_historico = d112.get("comentarios", [])
                comentario_simples = d112.get("comentario", "")

                save_resp_func = globals().get("save_resp_ieduc", globals().get("save_resp"))
                if save_resp_func:
                    save_resp_func(
                        qid="1.1.2",
                        valor=str_valor_salvar,
                        pontos=pts_112,
                        link=lnk_val,
                        comentario=comentario_simples,
                        comentarios=comentarios_historico
                    )

                links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(regex_url, lnk_val or "")]
                links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(regex_url, evidencia_112_salva or "")]

                if lnk_val != evidencia_112_salva and links_atuais and links_atuais != links_antigos:
                    st.session_state[f"links_pendentes_1_1_2_{ano_sel}"] = links_atuais
                    st.session_state[f"gatilho_modal_1_1_2_{ano_sel}"] = True

                st.cache_data.clear()
                st.toast("Resposta e histórico do Quesito 1.1.2 salvos com sucesso!", icon="✅")
                st.rerun()

    if st.session_state.get(f"gatilho_modal_1_1_2_{ano_sel}", False):
        modal_aviso_func = globals().get("modal_aviso_link")
        if modal_aviso_func:
            modal_aviso_func("1.1.2", st.session_state.get(f"links_pendentes_1_1_2_{ano_sel}", []), ano_sel)


# =============================================================================
# QUESITO 1.2 • DISPONIBILIZAÇÃO DE BRINQUEDOS E MATERIAIS (IEDUC)
# =============================================================================

def render_questao_1_2_ieduc(res_data: dict, ano_sel: str):
    """Renderiza a Questão 1.2 (Disponibilização de Brinquedos/Materiais Pedagógicos)."""
    
    regex_url = globals().get("REGEX_PURE_URL", r'https?://[^\s]+')

    with st.container(key=f"container_bloco_ieduc_1_2_{ano_sel}", border=True):
        with st.expander(f"📌 Questão 1.2 • Disponibilização de Brinquedos/Materiais Pedagógicos ({ano_sel})", expanded=True):
            st.subheader("1.2 • Materiais Pedagógicos e Brinquedos")
            st.write("**A Prefeitura disponibiliza brinquedos/materiais pedagógicos para as crianças em todos os estabelecimentos de Creche do município?**")
            st.caption("ℹ️ *Preencha os campos abaixo e clique no botão 'Salvar Questão 1.2' para registrar.*")

            opcoes_12 = {
                "Selecione...": 0.0,
                "Sim": 0.0,
                "Não": 0.0
            }

            d12 = res_data.get("1.2") or {
                "valor": "Selecione...",
                "pontos": 0.0,
                "link": "",
                "comentarios": [],
                "comentario": ""
            }
            v_salvo_12 = d12.get("valor", "Selecione...")

            if v_salvo_12 not in opcoes_12:
                v_salvo_12 = "Selecione..."

            evidencia_12_salva = d12.get("link", "")

            chave_radio_12 = f"r_12_{ano_sel}"
            chave_link_12 = f"l_12_txt_{ano_sel}"

            c12_1, c12_2 = st.columns([1, 1])
            
            with c12_1:
                lista_opcoes_12 = list(opcoes_12.keys())
                idx_12 = lista_opcoes_12.index(v_salvo_12) if v_salvo_12 in lista_opcoes_12 else 0

                val_radio_12 = st.radio(
                    "Selecione a situação da disponibilização:",
                    options=lista_opcoes_12,
                    index=idx_12,
                    key=chave_radio_12,
                )

            with c12_2:
                link_12 = st.text_area(
                    "Link de Evidência (Notas Fiscais, Fotos, Inventário, etc.):",
                    value=evidencia_12_salva,
                    key=chave_link_12,
                    placeholder="Insira o link oficial das evidências referente ao quesito 1.2...",
                    height=100,
                )
                
                placeholder_links_12 = st.empty()
                links_12_visuais = re.findall(regex_url, link_12 or "")
                
                if links_12_visuais:
                    links_formatados = [
                        f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                        for u in links_12_visuais
                    ]
                    placeholder_links_12.markdown("**🔗 Link ativo:** " + " | ".join(links_formatados))

            bloco_comentarios_func = globals().get("bloco_comentarios_ieduc", globals().get("bloco_comentarios"))
            if bloco_comentarios_func:
                bloco_comentarios_func("1.2", res_data, ano_sel)

            if st.button("💾 Salvar Questão 1.2", key=f"btn_salvar_1_2_{ano_sel}", type="primary"):
                val_salvar = st.session_state.get(chave_radio_12, v_salvo_12)
                pts_12 = 0.0
                lnk_val = link_12.strip()

                comentarios_historico = d12.get("comentarios", [])
                comentario_simples = d12.get("comentario", "")

                save_resp_func = globals().get("save_resp_ieduc", globals().get("save_resp"))
                if save_resp_func:
                    save_resp_func(
                        qid="1.2",
                        valor=val_salvar,
                        pontos=pts_12,
                        link=lnk_val,
                        comentario=comentario_simples,
                        comentarios=comentarios_historico
                    )

                links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(regex_url, lnk_val or "")]
                links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(regex_url, evidencia_12_salva or "")]

                if lnk_val != evidencia_12_salva and links_atuais and links_atuais != links_antigos:
                    st.session_state[f"links_pendentes_1_2_{ano_sel}"] = links_atuais
                    st.session_state[f"gatilho_modal_1_2_{ano_sel}"] = True

                st.cache_data.clear()
                st.toast("Resposta e histórico do Quesito 1.2 salvos com sucesso!", icon="✅")
                st.rerun()

            st.markdown(
                "<span style='color:#6c757d; font-weight:bold;'>"
                "ℹ️ Status: Questão Informativa (Sem impacto na pontuação global)</span>",
                unsafe_allow_html=True,
            )

    if st.session_state.get(f"gatilho_modal_1_2_{ano_sel}", False):
        modal_aviso_func = globals().get("modal_aviso_link")
        if modal_aviso_func:
            modal_aviso_func("1.2", st.session_state.get(f"links_pendentes_1_2_{ano_sel}", []), ano_sel)

# =============================================================================
# QUESITO 1.2.1 • HIGIENIZAÇÃO DOS BRINQUEDOS/MATERIAIS PEDAGÓGICOS (IEDUC)
# =============================================================================

def render_questao_1_2_1_ieduc(res_data: dict, ano_sel: str):
    """Renderiza a Questão 1.2.1 (Higienização dos Brinquedos/Materiais Pedagógicos)."""
    
    regex_url = globals().get("REGEX_PURE_URL", r'https?://[^\s]+')

    with st.container(key=f"container_bloco_ieduc_1_2_1_{ano_sel}", border=True):
        with st.expander(f"📌 Questão 1.2.1 • Higienização dos Brinquedos/Materiais ({ano_sel})", expanded=True):
            st.subheader("1.2.1 • Higienização dos Brinquedos/Materiais")
            st.write("**Realiza higienização dos brinquedos/materiais pedagógicos?**")
            st.caption("ℹ️ *Preencha os campos abaixo e clique no botão 'Salvar Questão 1.2.1' para registrar.*")

            opcoes_121 = {
                "Selecione...": 0.0,
                "Sim": 0.0,
                "Não": 0.0
            }

            d121 = res_data.get("1.2.1") or {
                "valor": "Selecione...",
                "pontos": 0.0,
                "link": "",
                "comentarios": [],
                "comentario": ""
            }
            v_salvo_121 = d121.get("valor", "Selecione...")

            if v_salvo_121 not in opcoes_121:
                v_salvo_121 = "Selecione..."

            evidencia_121_salva = d121.get("link", "")

            chave_radio_121 = f"r_121_{ano_sel}"
            chave_link_121 = f"l_121_txt_{ano_sel}"

            c121_1, c121_2 = st.columns([1, 1])
            
            with c121_1:
                lista_opcoes_121 = list(opcoes_121.keys())
                idx_121 = lista_opcoes_121.index(v_salvo_121) if v_salvo_121 in lista_opcoes_121 else 0

                val_radio_121 = st.radio(
                    "Selecione a situação da higienização:",
                    options=lista_opcoes_121,
                    index=idx_121,
                    key=chave_radio_121,
                )

            with c121_2:
                link_121 = st.text_area(
                    "Link de Evidência (Protocolos, Relatórios, Checklists, etc.):",
                    value=evidencia_121_salva,
                    key=chave_link_121,
                    placeholder="Insira o link oficial das evidências referente ao quesito 1.2.1...",
                    height=100,
                )
                
                placeholder_links_121 = st.empty()
                links_121_visuais = re.findall(regex_url, link_121 or "")
                
                if links_121_visuais:
                    links_formatados = [
                        f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                        for u in links_121_visuais
                    ]
                    placeholder_links_121.markdown("**🔗 Link ativo:** " + " | ".join(links_formatados))

            bloco_comentarios_func = globals().get("bloco_comentarios_ieduc", globals().get("bloco_comentarios"))
            if bloco_comentarios_func:
                bloco_comentarios_func("1.2.1", res_data, ano_sel)

            if st.button("💾 Salvar Questão 1.2.1", key=f"btn_salvar_1_2_1_{ano_sel}", type="primary"):
                val_salvar = st.session_state.get(chave_radio_121, v_salvo_121)
                pts_121 = 0.0
                lnk_val = link_121.strip()

                comentarios_historico = d121.get("comentarios", [])
                comentario_simples = d121.get("comentario", "")

                save_resp_func = globals().get("save_resp_ieduc", globals().get("save_resp"))
                if save_resp_func:
                    save_resp_func(
                        qid="1.2.1",
                        valor=val_salvar,
                        pontos=pts_121,
                        link=lnk_val,
                        comentario=comentario_simples,
                        comentarios=comentarios_historico
                    )

                links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(regex_url, lnk_val or "")]
                links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(regex_url, evidencia_121_salva or "")]

                if lnk_val != evidencia_121_salva and links_atuais and links_atuais != links_antigos:
                    st.session_state[f"links_pendentes_1_2_1_{ano_sel}"] = links_atuais
                    st.session_state[f"gatilho_modal_1_2_1_{ano_sel}"] = True

                st.cache_data.clear()
                st.toast("Resposta e histórico do Quesito 1.2.1 salvos com sucesso!", icon="✅")
                st.rerun()

            st.markdown(
                "<span style='color:#6c757d; font-weight:bold;'>"
                "ℹ️ Status: Questão Informativa (Sem impacto na pontuação global)</span>",
                unsafe_allow_html=True,
            )

    if st.session_state.get(f"gatilho_modal_1_2_1_{ano_sel}", False):
        modal_aviso_func = globals().get("modal_aviso_link")
        if modal_aviso_func:
            modal_aviso_func("1.2.1", st.session_state.get(f"links_pendentes_1_2_1_{ano_sel}", []), ano_sel)


# =============================================================================
# QUESITO 1.2.1.1 • FREQUÊNCIA DE HIGIENIZAÇÃO (IEDUC)
# =============================================================================

def render_questao_1_2_1_1_ieduc(res_data: dict, ano_sel: str):
    """Renderiza a Questão 1.2.1.1 (Frequência de Higienização)."""
    
    regex_url = globals().get("REGEX_PURE_URL", r'https?://[^\s]+')

    with st.container(key=f"container_bloco_ieduc_1_2_1_1_{ano_sel}", border=True):
        with st.expander(f"📌 Questão 1.2.1.1 • Frequência de Higienização ({ano_sel})", expanded=True):
            st.subheader("1.2.1.1 • Frequência de Higienização")
            st.write("**Qual a frequência de higienização aplicada na maior parte dos estabelecimentos que oferecem creche?**")
            st.caption("ℹ️ *Preencha os campos abaixo e clique no botão 'Salvar Questão 1.2.1.1' para registrar.*")

            opcoes_1211 = {
                "Selecione...": 0.0,
                "Diária – 05": 5.0,
                "A cada 2 dias – 04": 4.0,
                "A cada 3 dias – 03": 3.0,
                "Semanal – 02": 2.0,
                "Mensal – 01": 1.0,
                "> 30 dias – 00": 0.0
            }

            d1211 = res_data.get("1.2.1.1") or {
                "valor": "Selecione...",
                "pontos": 0.0,
                "link": "",
                "comentarios": [],
                "comentario": ""
            }
            v_salvo_1211 = d1211.get("valor", "Selecione...")

            if v_salvo_1211 not in opcoes_1211:
                v_salvo_1211 = "Selecione..."

            evidencia_1211_salva = d1211.get("link", "")

            chave_radio_1211 = f"r_1211_{ano_sel}"
            chave_link_1211 = f"l_1211_txt_{ano_sel}"

            c1211_1, c1211_2 = st.columns([1, 1])
            
            with c1211_1:
                lista_opcoes_1211 = list(opcoes_1211.keys())
                idx_1211 = lista_opcoes_1211.index(v_salvo_1211) if v_salvo_1211 in lista_opcoes_1211 else 0

                val_radio_1211 = st.radio(
                    "Selecione a frequência de higienização:",
                    options=lista_opcoes_1211,
                    index=idx_1211,
                    key=chave_radio_1211,
                )

            with c1211_2:
                link_1211 = st.text_area(
                    "Link de Evidência (Escala de Limpeza, Rotinas, Regulamento Interno, etc.):",
                    value=evidencia_1211_salva,
                    key=chave_link_1211,
                    placeholder="Insira o link oficial das evidências referente ao quesito 1.2.1.1...",
                    height=200,
                )
                
                placeholder_links_1211 = st.empty()
                links_1211_visuais = re.findall(regex_url, link_1211 or "")
                
                if links_1211_visuais:
                    links_formatados = [
                        f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                        for u in links_1211_visuais
                    ]
                    placeholder_links_1211.markdown("**🔗 Link ativo:** " + " | ".join(links_formatados))

            # Exibição dinâmica de pontos calculados
            pts_previstos_1211 = opcoes_1211.get(val_radio_1211, 0.0)
            if val_radio_1211 != "Selecione...":
                st.code(f"📊 Pontuação Selecionada na Questão 1.2.1.1: {pts_previstos_1211:.1f} pontos / 5.0 pontos máximos.", language="text")
            else:
                st.code("💡 Selecione uma opção para visualizar a pontuação da questão.", language="text")

            bloco_comentarios_func = globals().get("bloco_comentarios_ieduc", globals().get("bloco_comentarios"))
            if bloco_comentarios_func:
                bloco_comentarios_func("1.2.1.1", res_data, ano_sel)

            if st.button("💾 Salvar Questão 1.2.1.1", key=f"btn_salvar_1_2_1_1_{ano_sel}", type="primary"):
                val_salvar = st.session_state.get(chave_radio_1211, v_salvo_1211)
                pts_1211 = float(opcoes_1211.get(val_salvar, 0.0))
                lnk_val = link_1211.strip()

                comentarios_historico = d1211.get("comentarios", [])
                comentario_simples = d1211.get("comentario", "")

                save_resp_func = globals().get("save_resp_ieduc", globals().get("save_resp"))
                if save_resp_func:
                    save_resp_func(
                        qid="1.2.1.1",
                        valor=val_salvar,
                        pontos=pts_1211,
                        link=lnk_val,
                        comentario=comentario_simples,
                        comentarios=comentarios_historico
                    )

                links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(regex_url, lnk_val or "")]
                links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(regex_url, evidencia_1211_salva or "")]

                if lnk_val != evidencia_1211_salva and links_atuais and links_atuais != links_antigos:
                    st.session_state[f"links_pendentes_1_2_1_1_{ano_sel}"] = links_atuais
                    st.session_state[f"gatilho_modal_1_2_1_1_{ano_sel}"] = True

                st.cache_data.clear()
                st.toast("Resposta e histórico do Quesito 1.2.1.1 salvos com sucesso!", icon="✅")
                st.rerun()

    if st.session_state.get(f"gatilho_modal_1_2_1_1_{ano_sel}", False):
        modal_aviso_func = globals().get("modal_aviso_link")
        if modal_aviso_func:
            modal_aviso_func("1.2.1.1", st.session_state.get(f"links_pendentes_1_2_1_1_{ano_sel}", []), ano_sel)

# =============================================================================
# QUESITO 1.2.2 • CRONOGRAMA PARA COMPRA DE BRINQUEDOS (IEDUC)
# =============================================================================

def render_questao_1_2_2_ieduc(res_data: dict, ano_sel: str):
    """Renderiza a Questão 1.2.2 (Cronograma para Compra de Brinquedos)."""
    
    regex_url = globals().get("REGEX_PURE_URL", r'https?://[^\s]+')

    with st.container(key=f"container_bloco_ieduc_1_2_2_{ano_sel}", border=True):
        with st.expander(f"📌 Questão 1.2.2 • Cronograma para Compra de Brinquedos ({ano_sel})", expanded=True):
            st.subheader("1.2.2 • Cronograma para Compra de Brinquedos/Materiais")
            st.write("**Possui cronograma para compra de brinquedos/materiais pedagógicos?**")
            st.caption("Planejamento de compra de brinquedos/materiais pedagógicos para cada estabelecimento de ensino.")
            st.caption("ℹ️ *Preencha os campos abaixo e clique no botão 'Salvar Questão 1.2.2' para registrar.*")

            opcoes_122 = {
                "Selecione...": 0.0,
                "Sim – 05": 5.0,
                "Não – 00": 0.0
            }

            d122 = res_data.get("1.2.2") or {
                "valor": "Selecione...",
                "pontos": 0.0,
                "link": "",
                "comentarios": [],
                "comentario": ""
            }
            v_salvo_122 = d122.get("valor", "Selecione...")

            if v_salvo_122 not in opcoes_122:
                v_salvo_122 = "Selecione..."

            evidencia_122_salva = d122.get("link", "")

            chave_radio_122 = f"r_122_{ano_sel}"
            chave_link_122 = f"l_122_txt_{ano_sel}"

            c122_1, c122_2 = st.columns([1, 1])
            
            with c122_1:
                lista_opcoes_122 = list(opcoes_122.keys())
                idx_122 = lista_opcoes_122.index(v_salvo_122) if v_salvo_122 in lista_opcoes_122 else 0

                val_radio_122 = st.radio(
                    "Selecione a situação do cronograma:",
                    options=lista_opcoes_122,
                    index=idx_122,
                    key=chave_radio_122,
                )

            with c122_2:
                link_122 = st.text_area(
                    "Link de Evidência (Plano de Compras, Cronograma Anual, Editais, etc.):",
                    value=evidencia_122_salva,
                    key=chave_link_122,
                    placeholder="Insira o link oficial das evidências referente ao quesito 1.2.2...",
                    height=120,
                )
                
                placeholder_links_122 = st.empty()
                links_122_visuais = re.findall(regex_url, link_122 or "")
                
                if links_122_visuais:
                    links_formatados = [
                        f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                        for u in links_122_visuais
                    ]
                    placeholder_links_122.markdown("**🔗 Link ativo:** " + " | ".join(links_formatados))

            # Exibição dinâmica de pontos calculados
            pts_previstos_122 = opcoes_122.get(val_radio_122, 0.0)
            if val_radio_122 != "Selecione...":
                st.code(f"📊 Pontuação Selecionada na Questão 1.2.2: {pts_previstos_122:.1f} pontos / 5.0 pontos máximos.", language="text")
            else:
                st.code("💡 Selecione uma opção para visualizar a pontuação da questão.", language="text")

            bloco_comentarios_func = globals().get("bloco_comentarios_ieduc", globals().get("bloco_comentarios"))
            if bloco_comentarios_func:
                bloco_comentarios_func("1.2.2", res_data, ano_sel)

            if st.button("💾 Salvar Questão 1.2.2", key=f"btn_salvar_1_2_2_{ano_sel}", type="primary"):
                val_salvar = st.session_state.get(chave_radio_122, v_salvo_122)
                pts_122 = float(opcoes_122.get(val_salvar, 0.0))
                lnk_val = link_122.strip()

                comentarios_historico = d122.get("comentarios", [])
                comentario_simples = d122.get("comentario", "")

                save_resp_func = globals().get("save_resp_ieduc", globals().get("save_resp"))
                if save_resp_func:
                    save_resp_func(
                        qid="1.2.2",
                        valor=val_salvar,
                        pontos=pts_122,
                        link=lnk_val,
                        comentario=comentario_simples,
                        comentarios=comentarios_historico
                    )

                links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(regex_url, lnk_val or "")]
                links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(regex_url, evidencia_122_salva or "")]

                if lnk_val != evidencia_122_salva and links_atuais and links_atuais != links_antigos:
                    st.session_state[f"links_pendentes_1_2_2_{ano_sel}"] = links_atuais
                    st.session_state[f"gatilho_modal_1_2_2_{ano_sel}"] = True

                st.cache_data.clear()
                st.toast("Resposta e histórico do Quesito 1.2.2 salvos com sucesso!", icon="✅")
                st.rerun()

    if st.session_state.get(f"gatilho_modal_1_2_2_{ano_sel}", False):
        modal_aviso_func = globals().get("modal_aviso_link")
        if modal_aviso_func:
            modal_aviso_func("1.2.2", st.session_state.get(f"links_pendentes_1_2_2_{ano_sel}", []), ano_sel)


# =============================================================================
# QUESITO 1.2.3 • DATA DA ÚLTIMA ENTREGA DE BRINQUEDOS (IEDUC)
# =============================================================================

def render_questao_1_2_3_ieduc(res_data: dict, ano_sel: str):
    """Renderiza a Questão 1.2.3 (Data da Última Entrega de Brinquedos)."""
    from datetime import date, datetime  # <--- Importação explícita e segura
    
    regex_url = globals().get("REGEX_PURE_URL", r'https?://[^\s]+')

    with st.container(key=f"container_bloco_ieduc_1_2_3_{ano_sel}", border=True):
        with st.expander(f"📌 Questão 1.2.3 • Data da Última Entrega de Brinquedos ({ano_sel})", expanded=True):
            st.subheader("1.2.3 • Data da Última Entrega de Brinquedos")
            st.write("**Informe a data da última entrega de brinquedos/materiais pedagógicos:**")
            st.caption("ℹ️ *Preencha os campos abaixo e clique no botão 'Salvar Questão 1.2.3' para registrar.*")

            d123 = res_data.get("1.2.3") or {
                "valor": "",
                "pontos": 0.0,
                "link": "",
                "comentarios": [],
                "comentario": ""
            }
            v_salvo_123 = d123.get("valor", "")
            evidencia_123_salva = d123.get("link", "")

            # Parsing seguro da data inicial vinda do banco de dados
            data_inicial = date.today()
            if v_salvo_123:
                try:
                    # Tenta formato DD/MM/YYYY
                    data_inicial = datetime.strptime(v_salvo_123, "%d/%m/%Y").date()
                except ValueError:
                    try:
                        # Fallback tenta formato YYYY-MM-DD
                        data_inicial = datetime.strptime(v_salvo_123, "%Y-%m-%d").date()
                    except ValueError:
                        data_inicial = date.today()

            chave_date_123 = f"dt_ieduc_123_{ano_sel}"
            chave_link_123 = f"l_123_txt_{ano_sel}"

            c123_1, c123_2 = st.columns([1, 1])
            
            with c123_1:
                st.markdown('<label style="font-size: 13px; font-weight: 600;">Selecione a Data da Entrega:</label>', unsafe_allow_html=True)
                dt_selecionada = st.date_input(
                    "Data da última entrega de brinquedos",
                    value=data_inicial,
                    format="DD/MM/YYYY",
                    key=chave_date_123,
                    label_visibility="collapsed"
                )
                str_data_formatada = dt_selecionada.strftime("%d/%m/%Y")

            with c123_2:
                link_123 = st.text_area(
                    "Link de Evidência (Termo de Recebimento, Notas Fiscais, Fotos, etc.):",
                    value=evidencia_123_salva,
                    key=chave_link_123,
                    placeholder="Insira o link oficial das evidências referente ao quesito 1.2.3...",
                    height=100,
                )
                
                placeholder_links_123 = st.empty()
                links_123_visuais = re.findall(regex_url, link_123 or "")
                
                if links_123_visuais:
                    links_formatados = [
                        f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                        for u in links_123_visuais
                    ]
                    placeholder_links_123.markdown("**🔗 Link ativo:** " + " | ".join(links_formatados))

            st.code(f"📅 Data Selecionada no Quesito 1.2.3: {str_data_formatada}", language="text")

            bloco_comentarios_func = globals().get("bloco_comentarios_ieduc", globals().get("bloco_comentarios"))
            if bloco_comentarios_func:
                bloco_comentarios_func("1.2.3", res_data, ano_sel)

            if st.button("💾 Salvar Questão 1.2.3", key=f"btn_salvar_1_2_3_{ano_sel}", type="primary"):
                val_salvar = str_data_formatada
                pts_123 = 0.0
                lnk_val = link_123.strip()

                comentarios_historico = d123.get("comentarios", [])
                comentario_simples = d123.get("comentario", "")

                save_resp_func = globals().get("save_resp_ieduc", globals().get("save_resp"))
                if save_resp_func:
                    save_resp_func(
                        qid="1.2.3",
                        valor=val_salvar,
                        pontos=pts_123,
                        link=lnk_val,
                        comentario=comentario_simples,
                        comentarios=comentarios_historico
                    )

                links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(regex_url, lnk_val or "")]
                links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(regex_url, evidencia_123_salva or "")]

                if lnk_val != evidencia_123_salva and links_atuais and links_atuais != links_antigos:
                    st.session_state[f"links_pendentes_1_2_3_{ano_sel}"] = links_atuais
                    st.session_state[f"gatilho_modal_1_2_3_{ano_sel}"] = True

                st.cache_data.clear()
                st.toast("Resposta e histórico do Quesito 1.2.3 salvos com sucesso!", icon="✅")
                st.rerun()

            st.markdown(
                "<span style='color:#6c757d; font-weight:bold;'>"
                "ℹ️ Status: Questão Informativa (Sem impacto na pontuação global)</span>",
                unsafe_allow_html=True,
            )

    if st.session_state.get(f"gatilho_modal_1_2_3_{ano_sel}", False):
        modal_aviso_func = globals().get("modal_aviso_link")
        if modal_aviso_func:
            modal_aviso_func("1.2.3", st.session_state.get(f"links_pendentes_1_2_3_{ano_sel}", []), ano_sel)

# =============================================================================
# QUESITO 1.3 • ESPAÇO POR ALUNO EM SALA DE AULA (IEDUC)
# =============================================================================

def render_questao_1_3_ieduc(res_data: dict, ano_sel: str):
    """Renderiza a Questão 1.3 (Espaço por Aluno em Sala de Aula)."""
    
    regex_url = globals().get("REGEX_PURE_URL", r'https?://[^\s]+')

    with st.container(key=f"container_bloco_ieduc_1_3_{ano_sel}", border=True):
        with st.expander(f"📌 Questão 1.3 • Espaço por Aluno em Sala de Aula ({ano_sel})", expanded=True):
            st.subheader("1.3 • Espaço por Aluno em Sala de Aula (Creche)")
            st.write("**Informe a quantidade de turmas de Creche em que o espaço por aluno em sala de aula (área da sala dividido pelo nº de alunos) era:**")
            st.caption("*Considerar como sala de aula o local principal ocupado pelos alunos para seu ensino e aprendizagem pelos professores.*")
            
            st.markdown("""
            **Fórmula de cálculo ($P_{máx} = 10,0$ pontos):**
            * $N_1 = 1,0 \\times P_1$ *(Superior ou igual a 2,30 m²)*
            * $N_2 = 0,5 \\times P_2$ *(Superior ou igual a 2,00 m² e inferior a 2,30 m²)*
            * $N_3 = 0,25 \\times P_3$ *(Superior ou igual a 1,50 m² e inferior a 2,00 m²)*
            * $N_4 = 0,0 \\times P_4$ *(Inferior a 1,50 m²)*
            * $NF = P_{máx} \\times (N_1 + N_2 + N_3 + N_4)$ — *onde $P_i$ é a proporção de turmas em cada faixa.*
            """)
            st.caption("ℹ️ *Preencha as quantidades abaixo e clique no botão 'Salvar Questão 1.3' para registrar.*")

            d13 = res_data.get("1.3") or {
                "valor": "F1:0,F2:0,F3:0,F4:0",
                "pontos": 0.0,
                "link": "",
                "comentarios": [],
                "comentario": ""
            }
            v_banco_13 = d13.get("valor", "F1:0,F2:0,F3:0,F4:0")
            evidencia_13_salva = d13.get("link", "")

            # Parsing seguro dos valores salvos no banco
            try:
                parts_13 = v_banco_13.split(",")
                init_f1 = int(parts_13[0].split(":")[1])
                init_f2 = int(parts_13[1].split(":")[1])
                init_f3 = int(parts_13[2].split(":")[1])
                init_f4 = int(parts_13[3].split(":")[1])
            except Exception:
                init_f1, init_f2, init_f3, init_f4 = 0, 0, 0, 0

            chave_f1_13 = f"num_q13_f1_{ano_sel}"
            chave_f2_13 = f"num_q13_f2_{ano_sel}"
            chave_f3_13 = f"num_q13_f3_{ano_sel}"
            chave_f4_13 = f"num_q13_f4_{ano_sel}"
            chave_link_13 = f"l_13_txt_{ano_sel}"

            c13_1, c13_2 = st.columns([1, 1])

            with c13_1:
                st.markdown('<label style="font-size: 13px; font-weight: 500;">Superior ou igual a 2,30 m² por aluno (F1):</label>', unsafe_allow_html=True)
                val_f1 = st.number_input("F1", min_value=0, value=init_f1, step=1, key=chave_f1_13, label_visibility="collapsed")

                st.markdown('<label style="font-size: 13px; font-weight: 500;">Superior ou igual a 2,00 m² e inferior a 2,30 m² por aluno (F2):</label>', unsafe_allow_html=True)
                val_f2 = st.number_input("F2", min_value=0, value=init_f2, step=1, key=chave_f2_13, label_visibility="collapsed")

                st.markdown('<label style="font-size: 13px; font-weight: 500;">Superior ou igual a 1,50 m² e inferior a 2,00 m² por aluno (F3):</label>', unsafe_allow_html=True)
                val_f3 = st.number_input("F3", min_value=0, value=init_f3, step=1, key=chave_f3_13, label_visibility="collapsed")

                st.markdown('<label style="font-size: 13px; font-weight: 500;">Inferior a 1,50 m² por aluno (F4):</label>', unsafe_allow_html=True)
                val_f4 = st.number_input("F4", min_value=0, value=init_f4, step=1, key=chave_f4_13, label_visibility="collapsed")

            with c13_2:
                link_13 = st.text_area(
                    "Link de Evidência (Relatório de Metragem, Fotos das Salas, Censo Escolar, etc.):",
                    value=evidencia_13_salva,
                    key=chave_link_13,
                    placeholder="Insira o link oficial das evidências referente ao quesito 1.3...",
                    height=270,
                )

                placeholder_links_13 = st.empty()
                links_13_visuais = re.findall(regex_url, link_13 or "")

                if links_13_visuais:
                    links_formatados = [
                        f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                        for u in links_13_visuais
                    ]
                    placeholder_links_13.markdown("**🔗 Link ativo:** " + " | ".join(links_formatados))

            # Cálculo Matemático Dinâmico para Feedback Visual
            total_turmas = val_f1 + val_f2 + val_f3 + val_f4
            if total_turmas > 0:
                p1 = val_f1 / total_turmas
                p2 = val_f2 / total_turmas
                p3 = val_f3 / total_turmas
                pts_calculados_13 = min(10.0, round(10.0 * (p1 + (0.5 * p2) + (0.25 * p3)), 2))
                st.code(f"📊 Total: {total_turmas} turmas apuradas ➡️ Pontuação Ponderada: {pts_calculados_13:.2f} / 10.00 pontos máximos.", language="text")
            else:
                pts_calculados_13 = 0.0
                st.code("💡 Insira a quantidade de turmas nas faixas correspondentes para calcular a pontuação.", language="text")

            bloco_comentarios_func = globals().get("bloco_comentarios_ieduc", globals().get("bloco_comentarios"))
            if bloco_comentarios_func:
                bloco_comentarios_func("1.3", res_data, ano_sel)

            if st.button("💾 Salvar Questão 1.3", key=f"btn_salvar_1_3_{ano_sel}", type="primary"):
                str_valor_salvar = f"F1:{val_f1},F2:{val_f2},F3:{val_f3},F4:{val_f4}"
                lnk_val = link_13.strip()

                comentarios_historico = d13.get("comentarios", [])
                comentario_simples = d13.get("comentario", "")

                save_resp_func = globals().get("save_resp_ieduc", globals().get("save_resp"))
                if save_resp_func:
                    save_resp_func(
                        qid="1.3",
                        valor=str_valor_salvar,
                        pontos=float(pts_calculados_13),
                        link=lnk_val,
                        comentario=comentario_simples,
                        comentarios=comentarios_historico
                    )

                links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(regex_url, lnk_val or "")]
                links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(regex_url, evidencia_13_salva or "")]

                if lnk_val != evidencia_13_salva and links_atuais and links_atuais != links_antigos:
                    st.session_state[f"links_pendentes_1_3_{ano_sel}"] = links_atuais
                    st.session_state[f"gatilho_modal_1_3_{ano_sel}"] = True

                st.cache_data.clear()
                st.toast("Resposta e histórico do Quesito 1.3 salvos com sucesso!", icon="✅")
                st.rerun()

    if st.session_state.get(f"gatilho_modal_1_3_{ano_sel}", False):
        modal_aviso_func = globals().get("modal_aviso_link")
        if modal_aviso_func:
            modal_aviso_func("1.3", st.session_state.get(f"links_pendentes_1_3_{ano_sel}", []), ano_sel)


# =============================================================================
# QUESITO 1.4 • FORMAÇÃO DOS PROFESSORES DE CRECHE (IEDUC)
# =============================================================================

def calcular_pontuacao_q14(g_val: int, t_val: int, p_val: int) -> float:
    """Calcula a nota final do quesito 1.4 baseada na proporção de graduação e pós-graduação."""
    if t_val <= 0:
        return 0.0

    # N1 (Licenciatura / Graduação)
    g_perc = min(1.0, g_val / t_val)
    if g_perc >= 1.0:
        n1 = 11.0
    elif g_perc >= 0.90:
        n1 = 7.0
    elif g_perc >= 0.80:
        n1 = 3.0
    elif g_perc >= 0.70:
        n1 = 1.0
    else:
        n1 = 0.0

    # N2 (Pós-Graduação)
    p_perc = min(1.0, p_val / t_val)
    if p_perc >= 0.50:
        n2 = 7.0
    elif p_perc >= 0.40:
        n2 = 5.0
    elif p_perc >= 0.20:
        n2 = 3.0
    else:
        n2 = 0.0

    return float(n1 + n2)


def render_questao_1_4_ieduc(res_data: dict, ano_sel: str):
    """Renderiza a Questão 1.4 (Formação dos Professores de Creche)."""
    
    regex_url = globals().get("REGEX_PURE_URL", r'https?://[^\s]+')

    with st.container(key=f"container_bloco_ieduc_1_4_{ano_sel}", border=True):
        with st.expander(f"📌 Questão 1.4 • Formação dos Professores de Creche ({ano_sel})", expanded=True):
            st.subheader("1.4 • Formação dos Professores de Creche")
            st.write("**Informe os dados sobre a formação dos professores regentes de Creche (Efetivos e Temporários - Censo Escolar):**")
            
            st.markdown("""
            **Regras de Pontuação ($P_{máx} = 18,0$ pontos):**
            * **N1 (Licenciatura - GRAD):** $100\\% = 11$ pts | $90\\%$ a $99,9\\% = 7$ pts | $80\\%$ a $89,9\\% = 3$ pts | $70\\%$ a $79,9\\% = 1$ pt | $< 70\\% = 0$ pts
            * **N2 (Pós-Graduação - PGRAD):** $\\ge 50\\% = 7$ pts | $40\\%$ a $49,9\\% = 5$ pts | $20\\%$ a $39,9\\% = 3$ pts | $< 20\\% = 0$ pts
            * **Nota Final:** $NF = N1 + N2$
            """)
            st.caption("ℹ️ *Preencha os dados abaixo e clique no botão 'Salvar Questão 1.4' para registrar.*")

            d14 = res_data.get("1.4") or {
                "valor": "GRAD:0,PGRAD:0,TOTAL:0",
                "pontos": 0.0,
                "link": "",
                "comentarios": [],
                "comentario": ""
            }
            v_banco_14 = d14.get("valor", "GRAD:0,PGRAD:0,TOTAL:0")
            evidencia_14_salva = d14.get("link", "")

            # Parsing seguro dos dados salvos no banco
            try:
                parts_14 = v_banco_14.split(",")
                init_grad, init_pgrad, init_total = 0, 0, 0
                for part in parts_14:
                    if "GRAD" in part and "PGRAD" not in part:
                        init_grad = int(part.split(":")[1])
                    if "PGRAD" in part:
                        init_pgrad = int(part.split(":")[1])
                    if "TOTAL" in part:
                        init_total = int(part.split(":")[1])
            except Exception:
                init_grad, init_pgrad, init_total = 0, 0, 0

            chave_total_14 = f"num_q14_total_{ano_sel}"
            chave_grad_14 = f"num_q14_grad_{ano_sel}"
            chave_pgrad_14 = f"num_q14_pgrad_{ano_sel}"
            chave_link_14 = f"l_14_txt_{ano_sel}"

            c14_1, c14_2 = st.columns([1, 1])

            with c14_1:
                st.markdown('<label style="font-size: 13px; font-weight: 600; color: #1E3A8A;">Total de Professores Regentes de Creche (Censo Escolar):</label>', unsafe_allow_html=True)
                val_total = st.number_input("TOTAL", min_value=0, value=init_total, step=1, key=chave_total_14, label_visibility="collapsed")

                st.markdown('<label style="font-size: 13px; font-weight: 500;">Professores com formação superior em LICENCIATURA (GRAD):</label>', unsafe_allow_html=True)
                val_grad = st.number_input("GRAD", min_value=0, value=init_grad, step=1, key=chave_grad_14, label_visibility="collapsed")

                st.markdown('<label style="font-size: 13px; font-weight: 500; color: #10B981;">Deste total, quantos possuem PÓS-GRADUAÇÃO (PGRAD):</label>', unsafe_allow_html=True)
                val_pgrad = st.number_input("PGRAD", min_value=0, value=init_pgrad, step=1, key=chave_pgrad_14, label_visibility="collapsed")

            with c14_2:
                link_14 = st.text_area(
                    "Link de Evidência (Relatório de Quadro Docente, Censo Escolar, Diplomas, etc.):",
                    value=evidencia_14_salva,
                    key=chave_link_14,
                    placeholder="Insira o link oficial das evidências referente ao quesito 1.4...",
                    height=220,
                )

                placeholder_links_14 = st.empty()
                links_14_visuais = re.findall(regex_url, link_14 or "")

                if links_14_visuais:
                    links_formatados = [
                        f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                        for u in links_14_visuais
                    ]
                    placeholder_links_14.markdown("**🔗 Link ativo:** " + " | ".join(links_formatados))

            # Cálculo de feedback dinâmico
            pts_calculados_14 = calcular_pontuacao_q14(val_grad, val_total, val_pgrad)
            
            if val_total > 0:
                perc_g = (val_grad / val_total) * 100
                perc_p = (val_pgrad / val_total) * 100
                st.code(
                    f"📊 Proporções: Licenciatura {perc_g:.1f}% | Pós-Graduação {perc_p:.1f}%\n"
                    f"🏆 Pontuação Calculada no Quesito 1.4: {pts_calculados_14:.2f} / 18.00 pontos máximos.",
                    language="text"
                )
            else:
                st.code("💡 Insira o Total de Professores Regentes para calcular a pontuação da questão.", language="text")

            bloco_comentarios_func = globals().get("bloco_comentarios_ieduc", globals().get("bloco_comentarios"))
            if bloco_comentarios_func:
                bloco_comentarios_func("1.4", res_data, ano_sel)

            if st.button("💾 Salvar Questão 1.4", key=f"btn_salvar_1_4_{ano_sel}", type="primary"):
                str_valor_salvar = f"GRAD:{val_grad},PGRAD:{val_pgrad},TOTAL:{val_total}"
                lnk_val = link_14.strip()

                comentarios_historico = d14.get("comentarios", [])
                comentario_simples = d14.get("comentario", "")

                save_resp_func = globals().get("save_resp_ieduc", globals().get("save_resp"))
                if save_resp_func:
                    save_resp_func(
                        qid="1.4",
                        valor=str_valor_salvar,
                        pontos=float(pts_calculados_14),
                        link=lnk_val,
                        comentario=comentario_simples,
                        comentarios=comentarios_historico
                    )

                links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(regex_url, lnk_val or "")]
                links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(regex_url, evidencia_14_salva or "")]

                if lnk_val != evidencia_14_salva and links_atuais and links_atuais != links_antigos:
                    st.session_state[f"links_pendentes_1_4_{ano_sel}"] = links_atuais
                    st.session_state[f"gatilho_modal_1_4_{ano_sel}"] = True

                st.cache_data.clear()
                st.toast("Resposta e histórico do Quesito 1.4 salvos com sucesso!", icon="✅")
                st.rerun()

    if st.session_state.get(f"gatilho_modal_1_4_{ano_sel}", False):
        modal_aviso_func = globals().get("modal_aviso_link")
        if modal_aviso_func:
            modal_aviso_func("1.4", st.session_state.get(f"links_pendentes_1_4_{ano_sel}", []), ano_sel)

# =============================================================================
# QUESITO 1.5 • PISO SALARIAL DOS PROFESSORES DE CRECHE (IEDUC)
# =============================================================================

def converte_monetario_15(texto: str):
    """Converte string no formato de moeda para float."""
    if not texto or not str(texto).strip():
        return None
    num_limpo = str(texto).replace("R$", "").replace(" ", "")
    if "." in num_limpo and "," in num_limpo:
        num_limpo = num_limpo.replace(".", "").replace(",", ".")
    elif "," in num_limpo:
        num_limpo = num_limpo.replace(",", ".")
    try:
        return float(num_limpo)
    except Exception:
        return None


def render_questao_1_5_ieduc(res_data: dict, ano_sel: str):
    """Renderiza a Questão 1.5 (Piso Salarial dos Professores de Creche)."""
    
    regex_url = globals().get("REGEX_PURE_URL", r'https?://[^\s]+')

    with st.container(key=f"container_bloco_ieduc_1_5_{ano_sel}", border=True):
        with st.expander(f"📌 Questão 1.5 • Piso Salarial dos Professores de Creche ({ano_sel})", expanded=True):
            st.subheader("1.5 • Piso Salarial dos Professores de Creche")
            st.write("**Qual o piso salarial mensal dos professores de Creche no município?**")
            st.caption("*Considerar o piso base proporcional para uma jornada de 40 horas semanais.*")
            
            st.markdown("""
            **Regras de Validação ($P_{máx} = 0,0$ pontos - Penalização Crítica):**
            * **Piso < Salário Mínimo:** $-20,0$ pontos *(Penalização no bloco)*
            * **Piso $\\ge$ Salário Mínimo:** $0,0$ pontos *(Sem penalização)*
            """)
            st.caption("ℹ️ *Preencha os valores monetários abaixo e clique no botão 'Salvar Questão 1.5' para registrar.*")

            d15 = res_data.get("1.5") or {
                "valor": "PISO:;MINIMO:",
                "pontos": 0.0,
                "link": "",
                "comentarios": [],
                "comentario": ""
            }
            v_banco_15 = d15.get("valor", "PISO:;MINIMO:")
            evidencia_15_salva = d15.get("link", "")

            # Extraction/Parsing seguro dos valores salvos
            v_piso, v_minimo = None, None
            try:
                if ";" in v_banco_15:
                    parts_15 = v_banco_15.split(";")
                    piso_str_salvo = parts_15[0].split(":")[1]
                    minimo_str_salvo = parts_15[1].split(":")[1]
                    v_piso = float(piso_str_salvo) if piso_str_salvo != "" else None
                    v_minimo = float(minimo_str_salvo) if minimo_str_salvo != "" else None
                elif v_banco_15:
                    v_piso = float(v_banco_15)
            except Exception:
                v_piso, v_minimo = None, None

            str_inicial_piso = f"R$ {v_piso:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if v_piso is not None else ""
            str_inicial_minimo = f"R$ {v_minimo:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if v_minimo is not None else ""

            chave_minimo_15 = f"txt_ieduc_15_min_{ano_sel}"
            chave_piso_15 = f"txt_ieduc_15_piso_{ano_sel}"
            chave_link_15 = f"l_15_txt_{ano_sel}"

            c15_1, c15_2 = st.columns([1, 1])

            with c15_1:
                st.markdown('<label style="font-size: 13px; font-weight: 600; color: #1E3A8A;">Valor do Salário Mínimo de Referência (R$):</label>', unsafe_allow_html=True)
                input_minimo_str = st.text_input("MINIMO", value=str_inicial_minimo, placeholder="Ex: 1.512,00", key=chave_minimo_15, label_visibility="collapsed")

                st.markdown('<label style="font-size: 13px; font-weight: 600; color: #1E3A8A;">Valor do Piso Salarial base informado (R$):</label>', unsafe_allow_html=True)
                input_piso_str = st.text_input("PISO", value=str_inicial_piso, placeholder="Ex: 4.580,57", key=chave_piso_15, label_visibility="collapsed")

            with c15_2:
                link_15 = st.text_area(
                    "Link de Evidência (Lei do Piso Salarial, Folha de Pagamento, Edital, etc.):",
                    value=evidencia_15_salva,
                    key=chave_link_15,
                    placeholder="Insira o link oficial das evidências referente ao quesito 1.5...",
                    height=165,
                )

                placeholder_links_15 = st.empty()
                links_15_visuais = re.findall(regex_url, link_15 or "")

                if links_15_visuais:
                    links_formatados = [
                        f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                        for u in links_15_visuais
                    ]
                    placeholder_links_15.markdown("**🔗 Link ativo:** " + " | ".join(links_formatados))

            # Cálculo e feedback dinâmico
            piso_informado = converte_monetario_15(input_piso_str)
            salario_minimo_ref = converte_monetario_15(input_minimo_str)

            if piso_informado is None or salario_minimo_ref is None:
                pts_15 = 0.0
                st.code("⚠️ Status: Aguardando preenchimento completo dos valores de Piso e Salário Mínimo.", language="text")
            elif piso_informado < salario_minimo_ref:
                pts_15 = -20.0
                st.code(
                    f"🚨 Alerta Urgente: Piso abaixo do Salário Mínimo!\n"
                    f"📊 Penalização: {pts_15:.1f} pontos (Piso: R$ {piso_informado:,.2f} < Mínimo: R$ {salario_minimo_ref:,.2f})",
                    language="text"
                )
            else:
                pts_15 = 0.0
                st.code(
                    f"📊 Status: Piso em conformidade legal.\n"
                    f"✅ Pontuação: {pts_15:.1f} pontos (Piso: R$ {piso_informado:,.2f} ≥ Mínimo: R$ {salario_minimo_ref:,.2f})",
                    language="text"
                )

            bloco_comentarios_func = globals().get("bloco_comentarios_ieduc", globals().get("bloco_comentarios"))
            if bloco_comentarios_func:
                bloco_comentarios_func("1.5", res_data, ano_sel)

            if st.button("💾 Salvar Questão 1.5", key=f"btn_salvar_1_5_{ano_sel}", type="primary"):
                piso_banco_str = f"{piso_informado:.2f}" if piso_informado is not None else ""
                minimo_banco_str = f"{salario_minimo_ref:.2f}" if salario_minimo_ref is not None else ""
                str_valor_salvar = f"PISO:{piso_banco_str};MINIMO:{minimo_banco_str}"
                lnk_val = link_15.strip()

                comentarios_historico = d15.get("comentarios", [])
                comentario_simples = d15.get("comentario", "")

                save_resp_func = globals().get("save_resp_ieduc", globals().get("save_resp"))
                if save_resp_func:
                    save_resp_func(
                        qid="1.5",
                        valor=str_valor_salvar,
                        pontos=float(pts_15),
                        link=lnk_val,
                        comentario=comentario_simples,
                        comentarios=comentarios_historico
                    )

                links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(regex_url, lnk_val or "")]
                links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(regex_url, evidencia_15_salva or "")]

                if lnk_val != evidencia_15_salva and links_atuais and links_atuais != links_antigos:
                    st.session_state[f"links_pendentes_1_5_{ano_sel}"] = links_atuais
                    st.session_state[f"gatilho_modal_1_5_{ano_sel}"] = True

                st.cache_data.clear()
                st.toast("Resposta e histórico do Quesito 1.5 salvos com sucesso!", icon="✅")
                st.rerun()

    if st.session_state.get(f"gatilho_modal_1_5_{ano_sel}", False):
        modal_aviso_func = globals().get("modal_aviso_link")
        if modal_aviso_func:
            modal_aviso_func("1.5", st.session_state.get(f"links_pendentes_1_5_{ano_sel}", []), ano_sel)


# =============================================================================
# QUESITO 1.6 • QUANTIDADE TOTAL DE AUSÊNCIAS DOS PROFESSORES (IEDUC)
# =============================================================================

def render_questao_1_6_ieduc(res_data: dict, ano_sel: str):
    """Renderiza a Questão 1.6 (Quantidade Total de Ausências - QTA)."""
    
    regex_url = globals().get("REGEX_PURE_URL", r'https?://[^\s]+')

    with st.container(key=f"container_bloco_ieduc_1_6_{ano_sel}", border=True):
        with st.expander(f"📌 Questão 1.6 • Quantidade Total de Ausências - QTA ({ano_sel})", expanded=True):
            st.subheader("1.6 • Quantidade Total de Ausências dos Professores (Creche)")
            st.write("**Informe a quantidade total (em dias) de ausência dos professores por faltas e afastamentos na etapa de Creche:**")
            st.caption("*Considerar todos os dias de ausência dos professores regentes no ano base do Censo anterior.*")
            st.caption("ℹ️ *Preencha os dados abaixo e clique no botão 'Salvar Questão 1.6' para registrar.*")

            d16 = res_data.get("1.6") or {
                "valor": "INJ:0,JUST:0,MED:0,MAT:0,ABO:0,OUT:0,TOTAL:0",
                "pontos": 0.0,
                "link": "",
                "comentarios": [],
                "comentario": ""
            }
            v_banco_16 = d16.get("valor", "INJ:0,JUST:0,MED:0,MAT:0,ABO:0,OUT:0,TOTAL:0")
            evidencia_16_salva = d16.get("link", "")

            # Parsing seguro das variáveis
            try:
                parts_16 = v_banco_16.split(",")
                init_inj = int(parts_16[0].split(":")[1])
                init_just = int(parts_16[1].split(":")[1])
                init_med = int(parts_16[2].split(":")[1])
                init_mat = int(parts_16[3].split(":")[1])
                init_abo = int(parts_16[4].split(":")[1])
                init_out = int(parts_16[5].split(":")[1])
            except Exception:
                init_inj, init_just, init_med, init_mat, init_abo, init_out = 0, 0, 0, 0, 0, 0

            chave_inj_16 = f"num_q16_inj_{ano_sel}"
            chave_just_16 = f"num_q16_just_{ano_sel}"
            chave_med_16 = f"num_q16_med_{ano_sel}"
            chave_mat_16 = f"num_q16_mat_{ano_sel}"
            chave_abo_16 = f"num_q16_abo_{ano_sel}"
            chave_out_16 = f"num_q16_out_{ano_sel}"
            chave_link_16 = f"l_16_txt_{ano_sel}"

            c16_1, c16_2 = st.columns([1, 1])

            with c16_1:
                st.markdown('<label style="font-size: 13px; font-weight: 500;">Faltas Injustificadas (dias):</label>', unsafe_allow_html=True)
                val_inj = st.number_input("INJ", min_value=0, value=init_inj, step=1, key=chave_inj_16, label_visibility="collapsed")

                st.markdown('<label style="font-size: 13px; font-weight: 500;">Faltas Justificadas (dias):</label>', unsafe_allow_html=True)
                val_just = st.number_input("JUST", min_value=0, value=init_just, step=1, key=chave_just_16, label_visibility="collapsed")

                st.markdown('<label style="font-size: 13px; font-weight: 500;">Licença Médica / Tratamento de Saúde (dias):</label>', unsafe_allow_html=True)
                val_med = st.number_input("MED", min_value=0, value=init_med, step=1, key=chave_med_16, label_visibility="collapsed")

                st.markdown('<label style="font-size: 13px; font-weight: 500;">Licença Maternidade / Paternidade (dias):</label>', unsafe_allow_html=True)
                val_mat = st.number_input("MAT", min_value=0, value=init_mat, step=1, key=chave_mat_16, label_visibility="collapsed")

                st.markdown('<label style="font-size: 13px; font-weight: 500;">Abonos / Faltas Abonadas (dias):</label>', unsafe_allow_html=True)
                val_abo = st.number_input("ABO", min_value=0, value=init_abo, step=1, key=chave_abo_16, label_visibility="collapsed")

                st.markdown('<label style="font-size: 13px; font-weight: 500;">Outros (ausências pontuais / amparadas por lei em dias):</label>', unsafe_allow_html=True)
                val_out = st.number_input("OUT", min_value=0, value=init_out, step=1, key=chave_out_16, label_visibility="collapsed")

            with c16_2:
                link_16 = st.text_area(
                    "Link de Evidência (Relatório de Frequência, Folha de Ponto, Sistema de Gestão, etc.):",
                    value=evidencia_16_salva,
                    key=chave_link_16,
                    placeholder="Insira o link oficial das evidências referente ao quesito 1.6...",
                    height=380,
                )

                placeholder_links_16 = st.empty()
                links_16_visuais = re.findall(regex_url, link_16 or "")

                if links_16_visuais:
                    links_formatados = [
                        f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                        for u in links_16_visuais
                    ]
                    placeholder_links_16.markdown("**🔗 Link ativo:** " + " | ".join(links_formatados))

            # Recálculo do somatório total
            tot_ausencias = val_inj + val_just + val_med + val_mat + val_abo + val_out
            st.code(f"📊 Quantidade Total de Ausências (QTA): {tot_ausencias} dias acumulados (Dados Informativos).", language="text")

            bloco_comentarios_func = globals().get("bloco_comentarios_ieduc", globals().get("bloco_comentarios"))
            if bloco_comentarios_func:
                bloco_comentarios_func("1.6", res_data, ano_sel)

            if st.button("💾 Salvar Questão 1.6", key=f"btn_salvar_1_6_{ano_sel}", type="primary"):
                str_valor_salvar = f"INJ:{val_inj},JUST:{val_just},MED:{val_med},MAT:{val_mat},ABO:{val_abo},OUT:{val_out},TOTAL:{tot_ausencias}"
                lnk_val = link_16.strip()

                comentarios_historico = d16.get("comentarios", [])
                comentario_simples = d16.get("comentario", "")

                save_resp_func = globals().get("save_resp_ieduc", globals().get("save_resp"))
                if save_resp_func:
                    save_resp_func(
                        qid="1.6",
                        valor=str_valor_salvar,
                        pontos=0.0,
                        link=lnk_val,
                        comentario=comentario_simples,
                        comentarios=comentarios_historico
                    )

                links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(regex_url, lnk_val or "")]
                links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(regex_url, evidencia_16_salva or "")]

                if lnk_val != evidencia_16_salva and links_atuais and links_atuais != links_antigos:
                    st.session_state[f"links_pendentes_1_6_{ano_sel}"] = links_atuais
                    st.session_state[f"gatilho_modal_1_6_{ano_sel}"] = True

                st.cache_data.clear()
                st.toast("Resposta e histórico do Quesito 1.6 salvos com sucesso!", icon="✅")
                st.rerun()

    if st.session_state.get(f"gatilho_modal_1_6_{ano_sel}", False):
        modal_aviso_func = globals().get("modal_aviso_link")
        if modal_aviso_func:
            modal_aviso_func("1.6", st.session_state.get(f"links_pendentes_1_6_{ano_sel}", []), ano_sel)

# =============================================================================
# QUESITO 1.7 • CURSOS DE CAPACITAÇÃO DOS PROFISSIONAIS (CRECHE)
# =============================================================================

def render_questao_1_7_ieduc(res_data: dict, ano_sel: str):
    """Renderiza a Questão 1.7 (Cursos de Capacitação - Creche)."""
    
    regex_url = globals().get("REGEX_PURE_URL", r'https?://[^\s]+')

    with st.container(key=f"container_bloco_ieduc_1_7_{ano_sel}", border=True):
        with st.expander(f"📌 Questão 1.7 • Cursos de Capacitação - Creche ({ano_sel})", expanded=True):
            st.subheader("1.7 • Cursos de Capacitação dos Profissionais (Creche)")
            st.write(f"**Os profissionais de Creche da rede municipal participaram de cursos de capacitação durante o ano de {ano_sel}?**")
            st.caption("ℹ️ *Selecione a opção desejada, insira os links de evidência e clique no botão 'Salvar Questão 1.7' para registrar.*")

            d17 = res_data.get("1.7") or {
                "valor": "",
                "pontos": 0.0,
                "link": "",
                "comentarios": [],
                "comentario": ""
            }
            opc17 = ["Sim", "Não"]
            v_banco_17 = d17.get("valor", "")
            idx17 = opc17.index(v_banco_17) if v_banco_17 in opc17 else None
            evidencia_17_salva = d17.get("link", "")

            chave_radio_17 = f"q17_radio_{ano_sel}"
            chave_link_17 = f"l_17_txt_{ano_sel}"

            c17_1, c17_2 = st.columns([1, 2])

            with c17_1:
                r17 = st.radio(
                    f"Selecione 1.7 ({ano_sel}):",
                    opc17,
                    index=idx17,
                    key=chave_radio_17,
                    help="Informe se houve capacitação para os profissionais no ano base."
                )

            with c17_2:
                link_17 = st.text_area(
                    f"Link/Evidência de comprovação (1.7) - {ano_sel}:",
                    value=evidencia_17_salva,
                    key=chave_link_17,
                    placeholder="Insira o link oficial das evidências referente ao quesito 1.7...",
                    height=110,
                )

                placeholder_links_17 = st.empty()
                links_17_visuais = re.findall(regex_url, link_17 or "")

                if links_17_visuais:
                    links_formatados = [
                        f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                        for u in links_17_visuais
                    ]
                    placeholder_links_17.markdown("**🔗 Link ativo:** " + " | ".join(links_formatados))

            # Quesito informativo (pontuação é sempre 0.0)
            pts_17 = 0.0
            if r17:
                st.code(f"📊 Status Selecionado: {r17} | Pontuação: {pts_17:.1f} pontos (Dado Qualificatório/Informativo).", language="text")
            else:
                st.code("⚠️ Status: Nenhuma opção selecionada.", language="text")

            bloco_comentarios_func = globals().get("bloco_comentarios_ieduc", globals().get("bloco_comentarios"))
            if bloco_comentarios_func:
                bloco_comentarios_func("1.7", res_data, ano_sel)

            if st.button("💾 Salvar Questão 1.7", key=f"btn_salvar_1_7_{ano_sel}", type="primary"):
                v_sel = r17 if r17 else ""
                lnk_val = link_17.strip()

                comentarios_historico = d17.get("comentarios", [])
                comentario_simples = d17.get("comentario", "")

                save_resp_func = globals().get("save_resp_ieduc", globals().get("save_resp"))
                if save_resp_func:
                    save_resp_func(
                        qid="1.7",
                        valor=v_sel,
                        pontos=float(pts_17),
                        link=lnk_val,
                        comentario=comentario_simples,
                        comentarios=comentarios_historico
                    )

                links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(regex_url, lnk_val or "")]
                links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(regex_url, evidencia_17_salva or "")]

                if lnk_val != evidencia_17_salva and links_atuais and links_atuais != links_antigos:
                    st.session_state[f"links_pendentes_1_7_{ano_sel}"] = links_atuais
                    st.session_state[f"gatilho_modal_1_7_{ano_sel}"] = True

                st.cache_data.clear()
                st.toast("Resposta e histórico do Quesito 1.7 salvos com sucesso!", icon="✅")
                st.rerun()

    if st.session_state.get(f"gatilho_modal_1_7_{ano_sel}", False):
        modal_aviso_func = globals().get("modal_aviso_link")
        if modal_aviso_func:
            modal_aviso_func("1.7", st.session_state.get(f"links_pendentes_1_7_{ano_sel}", []), ano_sel)


# =============================================================================
# QUESITO 1.7.1 • CAPACITAÇÃO DE PROFISSIONAIS DA EDUCAÇÃO INFANTIL (CRECHE)
# =============================================================================

def render_questao_1_7_1_ieduc(res_data: dict, ano_sel: str):
    """Renderiza a Questão 1.7.1 (Índice de Capacitação de Profissionais - PC)."""
    
    regex_url = globals().get("REGEX_PURE_URL", r'https?://[^\s]+')

    with st.container(key=f"container_bloco_ieduc_1_7_1_{ano_sel}", border=True):
        with st.expander(f"📌 Questão 1.7.1 • Capacitação de Profissionais da Educação Infantil ({ano_sel})", expanded=True):
            st.subheader("1.7.1 • Capacitação de Profissionais da Educação Infantil (Creche)")
            st.write(f"**Informe a quantidade de profissionais de Creche capacitados em {ano_sel}:**")
            st.caption("⚠️ *Nota: Não contar o mesmo profissional mais de uma vez, mesmo que tenha participado de vários cursos.*")
            
            # Fórmula oficial
            st.latex(r"PC = \frac{\text{Prof.Capacitados} + \text{Apoio.Capacitados} + \text{Gestores.Capacitados}}{\text{Total.Prof} + \text{Total.Apoio} + \text{Total.Gestores}} \times 100")

            st.markdown("""
            **Matriz de Pontuação ($P_{máx} = 7,0$ pontos):**
            * **$PC \\ge 100,0\\%$:** $7,0$ pontos *(Excelência / Cobertura Universal)*
            * **$70,0\\% \\le PC < 100,0\\%$:** $5,0$ pontos *(Alto Índice)*
            * **$50,0\\% \\le PC < 70,0\\%$:** $3,0$ pontos *(Regular)*
            * **$PC < 50,0\\%$:** $0,0$ ponto *(Crítico)*
            """)
            st.caption("ℹ️ *Preencha os quantitativos abaixo e clique no botão 'Salvar Questão 1.7.1' para registrar.*")

            d171 = res_data.get("1.7.1") or {
                "valor": "PCAP:0,ACAP:0,GCAP:0,TGEST:0,TPROF:0,TAPOI:0",
                "pontos": 0.0,
                "link": "",
                "comentarios": [],
                "comentario": ""
            }
            v_banco_171 = d171.get("valor", "PCAP:0,ACAP:0,GCAP:0,TGEST:0,TPROF:0,TAPOI:0")
            evidencia_171_salva = d171.get("link", "")

            # Parsing defensivo
            try:
                parts_171 = v_banco_171.split(",")
                v_pcap = int(parts_171[0].split(":")[1])
                v_acap = int(parts_171[1].split(":")[1])
                v_gcap = int(parts_171[2].split(":")[1])
                v_tgest = int(parts_171[3].split(":")[1])
                v_tprof = int(parts_171[4].split(":")[1]) if len(parts_171) > 4 else 0
                v_tapoi = int(parts_171[5].split(":")[1]) if len(parts_171) > 5 else 0
            except Exception:
                v_pcap, v_acap, v_gcap, v_tgest, v_tprof, v_tapoi = 0, 0, 0, 0, 0, 0

            # Atalho inteligente do Quesito 1.4 caso esteja zerado
            if v_tprof == 0 and f"q14_total_{ano_sel}" in st.session_state:
                v_tprof = st.session_state.get(f"q14_total_{ano_sel}", 0)

            chave_pcap_171 = f"q171_pcap_{ano_sel}"
            chave_acap_171 = f"q171_acap_{ano_sel}"
            chave_gcap_171 = f"q171_gcap_{ano_sel}"
            chave_tprof_171 = f"q171_tprof_{ano_sel}"
            chave_tapoi_171 = f"q171_tapoi_{ano_sel}"
            chave_tgest_171 = f"q171_tgest_{ano_sel}"
            chave_link_171 = f"l_171_txt_{ano_sel}"

            c171_1, c171_2 = st.columns([1, 2])

            with c171_1:
                st.markdown("##### 📝 Profissionais Capacitados")
                pcap = st.number_input("Professores regentes que participaram de cursos:", min_value=0, step=1, value=v_pcap, key=chave_pcap_171)
                acap = st.number_input("Profissionais de apoio/supervisão capacitados:", min_value=0, step=1, value=v_acap, key=chave_acap_171)
                gcap = st.number_input("Gestores escolares capacitados:", min_value=0, step=1, value=v_gcap, key=chave_gcap_171)

                st.markdown("##### 📊 Total do Quadro de Funcionários")
                tprof = st.number_input("Total de professores regentes da etapa:", min_value=0, step=1, value=v_tprof, key=chave_tprof_171)
                tapoi = st.number_input("Total de profissionais de apoio e supervisão:", min_value=0, step=1, value=v_tapoi, key=chave_tapoi_171)
                tgest = st.number_input("Total de gestores escolares de creche:", min_value=0, step=1, value=v_tgest, key=chave_tgest_171)

            with c171_2:
                link_171 = st.text_area(
                    f"Link/Evidência de comprovação das capacitações (1.7.1) - {ano_sel}:",
                    value=evidencia_171_salva,
                    key=chave_link_171,
                    placeholder="Insira os links oficiais comprovando os cursos e relatórios de capacitação...",
                    height=410,
                )

                placeholder_links_171 = st.empty()
                links_171_visuais = re.findall(regex_url, link_171 or "")

                if links_171_visuais:
                    links_formatados = [
                        f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                        for u in links_171_visuais
                    ]
                    placeholder_links_171.markdown("**🔗 Link ativo:** " + " | ".join(links_formatados))

            # Cálculos consolidados
            total_capacitados = pcap + acap + gcap
            total_geral_quadro = tprof + tapoi + tgest

            pc_pct = 0.0
            pts171 = 0.0

            if total_geral_quadro > 0:
                calculo_bruto = (total_capacitados / total_geral_quadro) * 100.0
                pc_pct = min(calculo_bruto, 100.0)

                if calculo_bruto >= 100.0:
                    pts171 = 7.0
                    status_desc = "🥇 EXCELÊNCIA: Capacitação universal ou acima do quadro permanente"
                elif 70.0 <= pc_pct < 100.0:
                    pts171 = 5.0
                    status_desc = "🟢 ALTO ÍNDICE: Ótimo aproveitamento de formação continuada"
                elif 50.0 <= pc_pct < 70.0:
                    pts171 = 3.0
                    status_desc = "🟡 REGULAR: Índice intermediário de capacitação pedagógica"
                else:
                    pts171 = 0.0
                    status_desc = "❌ CRÍTICO: Baixo envolvimento em programas de formação continuada"
                
                pct_exibicao = f"{pc_pct:.1f}%"
            else:
                pct_exibicao = "0.0%"
                status_desc = "⏳ Aguardando a inserção dos dados do quadro de funcionários."

            st.code(
                f"📊 Métrica Consolidada:\n"
                f"• Cobertura de Capacitação (PC): {pct_exibicao} ({total_capacitados} capacitados de {total_geral_quadro} no quadro)\n"
                f"• Status: {status_desc}\n"
                f"• Pontuação Resultante: {pts171:.1f} pontos",
                language="text"
            )

            bloco_comentarios_func = globals().get("bloco_comentarios_ieduc", globals().get("bloco_comentarios"))
            if bloco_comentarios_func:
                bloco_comentarios_func("1.7.1", res_data, ano_sel)

            if st.button("💾 Salvar Questão 1.7.1", key=f"btn_salvar_1_7_1_{ano_sel}", type="primary"):
                str_valor_salvar = f"PCAP:{pcap},ACAP:{acap},GCAP:{gcap},TGEST:{tgest},TPROF:{tprof},TAPOI:{tapoi}"
                lnk_val = link_171.strip()

                comentarios_historico = d171.get("comentarios", [])
                comentario_simples = d171.get("comentario", "")

                save_resp_func = globals().get("save_resp_ieduc", globals().get("save_resp"))
                if save_resp_func:
                    save_resp_func(
                        qid="1.7.1",
                        valor=str_valor_salvar,
                        pontos=float(pts171),
                        link=lnk_val,
                        comentario=comentario_simples,
                        comentarios=comentarios_historico
                    )

                links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(regex_url, lnk_val or "")]
                links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(regex_url, evidencia_171_salva or "")]

                if lnk_val != evidencia_171_salva and links_atuais and links_atuais != links_antigos:
                    st.session_state[f"links_pendentes_1_7_1_{ano_sel}"] = links_atuais
                    st.session_state[f"gatilho_modal_1_7_1_{ano_sel}"] = True

                st.cache_data.clear()
                st.toast("Resposta e histórico do Quesito 1.7.1 salvos com sucesso!", icon="✅")
                st.rerun()

    if st.session_state.get(f"gatilho_modal_1_7_1_{ano_sel}", False):
        modal_aviso_func = globals().get("modal_aviso_link")
        if modal_aviso_func:
            modal_aviso_func("1.7.1", st.session_state.get(f"links_pendentes_1_7_1_{ano_sel}", []), ano_sel)
