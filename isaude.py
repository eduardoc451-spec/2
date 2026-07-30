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
        load_respostas_isaude,
        modal_aviso_link,
        render_sidebar_isaude,
        save_resp_isaude,
    )
except ImportError:
    logging.warning("Módulo utils.py não encontrado. Carregando funções fallback de segurança.")

    def get_connection():
        """Conexão fallback com banco Neon usando URL das Secrets do Streamlit."""
        db_url = st.secrets.get("postgres", {}).get("url") or os.getenv("DATABASE_URL")
        return psycopg2.connect(db_url)

    def load_respostas_isaude(ano: int = None, forcar_recarga: bool = False) -> dict:
        """Fallback local para carregar respostas do iSaúde."""
        ano_sel = ano or st.session_state.get("ano_referencia_isaude", 2026)
        key_ano = f"respostas_isaude_{ano_sel}"
        return st.session_state.get(key_ano, {})

    def save_resp_isaude(qid, valor, pontos, link="", comentarios=None, comentario=""):
        """Fallback para manter na memória caso utils falhe."""
        ano_sel = st.session_state.get("ano_referencia_isaude", 2026)
        key_ano = f"respostas_isaude_{ano_sel}"
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
            key=f"coment_isaude_{qid}_{ano_sel}",
            placeholder="Escreva aqui observações ou justificativas...",
            height=80,
        )

    def modal_aviso_link(*args, **kwargs):
        pass

    def render_sidebar_isaude(*args, **kwargs):
        return 0, {}, datetime.now().year
        
# =============================================================================
# CONFIGURAÇÃO COMPLETA DE ESTILOS DE RELATÓRIO (PDF) - iSaúde
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

# ➔ VARIÁVEL DO ERRO:
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
    "TituloCapaISaude",
    parent=styles["Normal"],
    fontName="Helvetica-Bold",
    fontSize=24,
    leading=28,
    alignment=TA_CENTER,
    textColor=colors.HexColor("#0D9488"),
    spaceAfter=15,
)

style_subtitulo_capa = ParagraphStyle(
    "SubtituloCapaISaude",
    parent=styles["Normal"],
    fontName="Helvetica",
    fontSize=14,
    leading=18,
    alignment=TA_CENTER,
    textColor=colors.HexColor("#4B5563"),
    spaceAfter=20,
)

style_ano_capa = ParagraphStyle(
    "AnoCapaISaude",
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

PONTUACOES_MAX_ISAUDE = {
    "1": 5, "2": 10, "3": 10, "3.1": 4, "3.2": 4, "4": 6, "5": 4, "6": 5, "7": 3, "8": 2,
    "9": 18, "9.2": 5, "10": 100, "11": 10, "11.2": 2, "12.0": 10, "12.1": 50, "12.2": 40,
    "13": 5, "13.1": 15, "14": 1, "14.1": 10, "14.2": 2, "14.2.1": 10, "15": 2, "15.1": 7,
    "16": 10, "16.1": 5, "21": 10, "22": 30, "23.1": 30, "24.1": 10, "25": 5, "26": 10,
    "27": 5, "28": 5, "28.1": 5, "29": 15, "30.1.1": 9, "32.1": 45, "33.1": 10, "34.0": 5,
    "35.1": 15, "35.2": 10, "36": 40, "36.1": 40, "37": 90, "S2": 20, "S3": 25, "S4": 10,
    "S5": 10, "S6": 100, "S7": 20, "S17": 25, "S18": 25, "S19": 25, "S20": 25
}

CATEGORIAS_MAP_ISAUDE = {
    "atencao_basica": {
        "label": "1.0 Atenção Básica",
        "qids": ["1", "2", "3", "3.1", "3.2", "4", "5", "6", "7", "8", "9", "9.2"]
    },
    "vigilancia_saude": {
        "label": "2.0 Vigilância em Saúde",
        "qids": ["10", "11", "11.2", "12.0", "12.1", "12.2", "13", "13.1"]
    },
    "assistencia_farmaceutica": {
        "label": "3.0 Assistência Farmacêutica",
        "qids": ["14", "14.1", "14.2", "14.2.1", "15", "15.1", "16", "16.1"]
    },
    "infraestrutura_ubs": {
        "label": "4.0 Infraestrutura de UBS",
        "qids": ["21", "22", "23.1", "24.1", "25", "26", "27", "28", "28.1", "29"]
    },
    "gestao_recursos": {
        "label": "5.0 Gestão e Recursos Humanos",
        "qids": ["30.1.1", "32.1", "33.1", "34.0", "35.1", "35.2", "36", "36.1", "37"]
    },
    "financiamento_minimo": {
        "label": "6.0 Limite Constitucional (SIOPS)",
        "qids": ["S2", "S3", "S4", "S5", "S6", "S7", "S17", "S18", "S19", "S20"] 
    }
}

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
    qid_key = qid.replace('.', '_')
    chave_gatilho = f"gatilho_modal_{qid_key}_{ano_sel}"
    
    if st.button("Confirmo que o link está liberado para o público", key=f"btn_conf_{qid_key}_{ano_sel}", type="primary"):
        # Desliga o gatilho no session_state para fechar o modal e não reabrir em outros salvamentos
        st.session_state[chave_gatilho] = False
        st.rerun()
import json
import logging
import re
import streamlit as st
from datetime import datetime
from psycopg2.extras import RealDictCursor

# =============================================================================
# 1. GESTÃO DE ESTADO E PERSISTÊNCIA NEON POSTGRES - iSaúde
# =============================================================================

def get_ano_atual_isaude() -> int:
    """Recupera o ano de referência ativo para o iSaúde."""
    return int(
        st.session_state.get("ano_referencia_isaude")
        or st.session_state.get("ano_referencia_global")
        or 2026
    )


def load_respostas_isaude(ano: int = None, forcar_recarga: bool = False) -> dict:
    """Carrega respostas do Neon PostgreSQL diretamente para o st.session_state."""
    if ano is None:
        ano = get_ano_atual_isaude()

    key_ano = f"respostas_isaude_{ano}"

    if forcar_recarga or key_ano not in st.session_state:
        st.session_state[key_ano] = {}
        try:
            with get_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    cursor.execute(
                        "SELECT quesito, resposta, pontos, detalhes FROM respostas_isaude WHERE ano = %s",
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
            logging.error(f"Erro ao carregar respostas do banco iSaúde: {e}")

    return st.session_state[key_ano]


def save_resp_isaude(qid, valor, pontos, link="", comentarios=None, comentario=""):
    """Salva a resposta no Neon PostgreSQL e sincroniza o estado local reativamente."""
    ano_int = get_ano_atual_isaude()
    key_ano = f"respostas_isaude_{ano_int}"

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
                    INSERT INTO respostas_isaude (ano, quesito, resposta, pontos, detalhes, atualizado_em)
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
            load_respostas_isaude(ano=ano_int, forcar_recarga=True)
            return True

    except Exception as e:
        logging.error(f"Erro ao salvar no Neon (iSaúde): {e}")
        st.error(f"Erro ao salvar no banco Neon: {e}")
        return False


# =============================================================================
# 2. COMPONENTE DE DIÁLOGO INTERNO E COMENTÁRIOS (SISTEMA AVANÇADO)
# =============================================================================

def bloco_comentarios_isaude(questao_id: str, res_data: dict, sufixo: str = None):
    """Gera o diálogo interno avançado com histórico, status e salvamento direto no Neon."""
    ano_sel = get_ano_atual_isaude()
    usuario_atual = st.session_state.get("username", st.session_state.get("usuario", "Usuário Anônimo"))

    id_chave = f"{questao_id}_{sufixo}" if sufixo else questao_id
    key_texto = f"v_txt_com_isaude_{id_chave}_{ano_sel}"
    key_estado_limpar = f"limpar_input_isaude_{id_chave}_{ano_sel}"
    key_radio = f"rad_status_isaude_{id_chave}_{ano_sel}"

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
            save_resp_isaude(
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
                            f"""<div style="background-color: #f8f9fa; padding: 10px 15px; border-radius: 8px; margin-bottom: 6px; border-left: 3px solid #1e88e5;">
                                <span style="font-size: 11px; color: #1e88e5; font-weight: bold;">{autor}</span> 
                                <span style="font-size: 10px; color: #999; margin-left: 10px;">{data_com}</span>
                                <p style="margin: 4px 0 0 0; font-size: 13px; color: #333;">{texto_com}</p>
                            </div>""", unsafe_allow_html=True
                        )

                with col_lixeira:
                    if st.button("🗑️", key=f"btn_del_com_isaude_{id_chave}_{idx}_{ano_sel}"):
                        historico.pop(idx)
                        save_resp_isaude(
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
        if st.button("Postar Comentário", key=f"btn_com_isaude_{id_chave}_{ano_sel}", type="primary"):
            if novo_texto.strip():
                nova_mensagem = {
                    "autor": usuario_atual,
                    "data": datetime.now().strftime("%d/%m/%Y %H:%M"),
                    "texto": novo_texto.strip(),
                    "status_definido": status_global
                }
                historico.append(nova_mensagem)
                save_resp_isaude(
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
# 3. PAINEL DE RESUMO E PONTUAÇÃO (DESEMPENHO DO ISAÚDE)
# =============================================================================

def render_dashboard_isaude(questoes: list):
    """Exibe os cartões de status e progresso do iSaúde."""
    ano = get_ano_atual_isaude()
    respostas = load_respostas_isaude(ano)

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
        st.metric("Nota iSaúde", f"{nota_final:.2f} / 10.0")

    st.progress(min(progresso_pct / 100.0, 1.0))
    st.markdown("---")


# =============================================================================
# 4. RENDERIZADOR DE QUESITOS E FORMULÁRIO (PADRÃO IAMB INTEGRADO COM COMENTÁRIOS)
# =============================================================================

def render_modulo_isaude(questoes_isaude: list):
    """Interface principal do módulo iSaúde."""
    st.title("🏥 iSaúde - Índice de Saúde")
    
    # 1. Renderiza o resumo dinâmico
    render_dashboard_isaude(questoes_isaude)

    ano = get_ano_atual_isaude()
    respostas = load_respostas_isaude(ano)

    st.subheader("Formulário de Avaliação")

    for questao in questoes_isaude:
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
                key=f"select_isaude_{ano}_{qid}"
            )

            # Evidência / Link
            link_input = st.text_input(
                "Link da Evidência / Comprovação:",
                value=link_atual,
                key=f"link_isaude_{ano}_{qid}"
            )

            # Observações adicionais
            obs_input = st.text_area(
                "Observações / Justificativa:",
                value=obs_atual,
                key=f"obs_isaude_{ano}_{qid}"
            )

            # Ação de Salvar por Quesito
            if st.button(f"Salvar Quesito {qid}", key=f"btn_save_isaude_{ano}_{qid}", type="primary"):
                if opcao_sel != "-- Selecione --":
                    pts = float(pontos_map.get(opcao_sel, 0.0))
                    
                    sucesso = save_resp_isaude(
                        qid=qid,
                        valor=opcao_sel,
                        pontos=pts,
                        link=link_input,
                        comentario=obs_input
                    )
                    
                    if sucesso:
                        st.toast(f"Quesito {qid} salvo com sucesso!", icon="✅")
                        
                        # Modal de link (se houver a função)
                        links = re.findall(r'https?://[^\s]+', link_input)
                        if links and "modal_aviso_link" in globals():
                            modal_aviso_link(qid, links)
                            
                        st.rerun()
                else:
                    st.warning("Selecione uma opção válida antes de salvar.")

            # INTEGRAÇÃO DO DIÁLOGO INTERNO / HISTÓRICO DE COMENTÁRIOS
            bloco_comentarios_isaude(qid, respostas)

# =============================================================================
# CONFIGURAÇÃO DE ESTILOS PADRÃO PARA RELATÓRIOS PDF (iSaúde)
# =============================================================================
styles = getSampleStyleSheet()

# --- ESTILOS DE CAPA (ADICIONE ESTE BLOCO) ---
style_titulo_capa = ParagraphStyle(
    "TituloCapaISaude",
    parent=styles["Normal"],
    fontName="Helvetica-Bold",
    fontSize=24,
    leading=28,
    alignment=TA_CENTER,
    textColor=colors.HexColor("#0D9488"),  # Cor customizada (ex: Teal)
    spaceAfter=15,
)

style_subtitulo_capa = ParagraphStyle(
    "SubtituloCapaISaude",
    parent=styles["Normal"],
    fontName="Helvetica",
    fontSize=14,
    leading=18,
    alignment=TA_CENTER,
    textColor=colors.HexColor("#4B5563"),
    spaceAfter=30,
)

# =============================================================================
# 2. GERADOR DO RELATÓRIO PDF (i-Saúde)
# =============================================================================

def gerar_relatorio_pdf_isaude(dados, ano, total, faixa, all_data=None):
    """Gera o documento PDF consolidado para o i-Saúde sem dependências externas incorretas."""
    
    # 1. TRATAMENTO DE ANOS E DADOS HISTÓRICOS
    try:
        ano_atual = int(ano)
    except (ValueError, TypeError):
        ano_atual = datetime.now().year

    ano_ant = ano_atual - 1

    if all_data is None:
        try:
            all_data = get_all_years_data_isaude()
        except Exception:
            all_data = {}

    # 2. CÁLCULO DE VARIÁVEIS DE TENDÊNCIA
    nota_atual = float(total) if total is not None else 0.0
    faixa_real_atual = str(faixa) if faixa else "N/A"

    dados_ano_ant = all_data.get(ano_ant) or all_data.get(str(ano_ant))

    if dados_ano_ant:
        if isinstance(dados_ano_ant, dict):
            nota_ant = float(dados_ano_ant.get("pontuacao_total", 0.0))
        else:
            try:
                nota_ant = float(dados_ano_ant)
            except (ValueError, TypeError):
                nota_ant = 0.0

        variacao_pontos = nota_atual - nota_ant
        
        if nota_ant > 0:
            variacao_pct = (variacao_pontos / nota_ant) * 100
            texto_percentual = f"{variacao_pct:+.1f}%"
        else:
            texto_percentual = "N/A"

        if variacao_pontos > 0:
            seta_tendencia = "▲"
        elif variacao_pontos < 0:
            seta_tendencia = "▼"
        else:
            seta_tendencia = "="
    else:
        variacao_pontos = 0.0
        texto_percentual = "Sem dados ant."
        seta_tendencia = "-"

    # 3. CONFIGURAÇÃO DO REPORTLAB
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=30,
        leftMargin=30,
        topMargin=30,
        bottomMargin=50,
    )
    elements = []

    styles = getSampleStyleSheet()

    style_tabela_cabecalho = ParagraphStyle(
        "TabelaCabecalho",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=11,
        alignment=TA_CENTER,
        textColor=colors.whitesmoke,
    )

    style_tabela_esquerda = ParagraphStyle(
        "TabelaEsquerda",
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

    title_style = ParagraphStyle(
        "DocTitle",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=22,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#0d9488"),
    )

    subtitle_style = ParagraphStyle(
        "DocSubTitle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=11,
        leading=14,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#4b5563"),
    )

    section_header_style = ParagraphStyle(
        "SectionHeader",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=13,
        leading=16,
        textColor=colors.HexColor("#0f172a"),
    )

    # 4. MONTAGEM DO CONTEÚDO DO PDF
    elements.append(Paragraph("Relatório de Avaliação - i-Saúde", title_style))
    elements.append(Spacer(1, 6))
    elements.append(
        Paragraph(
            f"Ano de Referência: <b>{ano_atual}</b> | Pontuação Total: <b>{nota_atual:.2f} pts</b> ({faixa_real_atual})",
            subtitle_style,
        )
    )
    elements.append(Spacer(1, 15))

    # Tabela de Comparativo / Tendência Histórica
    elements.append(Paragraph("Resumo do Período e Evolução", section_header_style))
    elements.append(Spacer(1, 6))

    tabela_tendencia_dados = [
        [
            Paragraph("Ano", style_tabela_cabecalho),
            Paragraph("Pontuação", style_tabela_cabecalho),
            Paragraph("Faixa", style_tabela_cabecalho),
            Paragraph("Variação (Pts)", style_tabela_cabecalho),
            Paragraph("Variação (%)", style_tabela_cabecalho),
        ],
        [
            Paragraph(str(ano_atual), style_tabela_centro),
            Paragraph(f"{nota_atual:.2f} pts", style_tabela_centro),
            Paragraph(str(faixa_real_atual), style_tabela_centro),
            Paragraph(f"{seta_tendencia} {variacao_pontos:+.2f} pts", style_tabela_centro),
            Paragraph(f"{seta_tendencia} {texto_percentual}", style_tabela_centro),
        ],
    ]

    t_tendencia = Table(tabela_tendencia_dados, colWidths=[65, 110, 140, 110, 110])
    t_tendencia.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
        ])
    )
    elements.append(t_tendencia)
    elements.append(Spacer(1, 15))

    # Tabela com Resumo por Categoria (i-Saúde)
    elements.append(Paragraph("Desempenho por Categoria / Eixo", section_header_style))
    elements.append(Spacer(1, 6))

    tabela_resumo_dados = [
        [
            Paragraph("Categoria / Eixo", style_tabela_cabecalho),
            Paragraph("Pontuação Obtida", style_tabela_cabecalho),
        ]
    ]

    # Utiliza CATEGORIAS_MAP_ISAUDE ou fallback seguro
    mapa_categorias = globals().get("CATEGORIAS_MAP_ISAUDE", {})
    if mapa_categorias:
        for cat_key, cat_info in mapa_categorias.items():
            pts_cat = sum(dados.get(qid, {}).get("pontos", 0.0) for qid in cat_info.get("qids", []))
            tabela_resumo_dados.append([
                Paragraph(str(cat_info.get("label", cat_key)), style_tabela_esquerda),
                Paragraph(f"{pts_cat:.2f}", style_tabela_centro),
            ])

    t_resumo = Table(tabela_resumo_dados, colWidths=[385, 150])
    t_resumo.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0d9488")),
            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
        ])
    )
    elements.append(t_resumo)
    elements.append(Spacer(1, 15))

    # Detalhamento por Quesito
    elements.append(Paragraph("Detalhamento por Quesito", section_header_style))
    elements.append(Spacer(1, 6))

    tabela_detalhes_dados = [
        [
            Paragraph("Quesito", style_tabela_cabecalho),
            Paragraph("Resposta", style_tabela_cabecalho),
            Paragraph("Pontos", style_tabela_cabecalho),
            Paragraph("Evidência / Link", style_tabela_cabecalho),
        ]
    ]

    for qid, info in dados.items():
        if isinstance(info, dict):
            val = info.get("valor", "-")
            pts = info.get("pontos", 0.0)
            link = info.get("link", "-")
        else:
            val = str(info)
            pts = 0.0
            link = "-"

        link_formatado = html.escape(str(link)) if link else "-"

        tabela_detalhes_dados.append([
            Paragraph(str(qid), style_tabela_centro),
            Paragraph(str(val), style_tabela_esquerda),
            Paragraph(f"{pts:.2f}", style_tabela_centro),
            Paragraph(link_formatado, style_tabela_esquerda),
        ])

    t_detalhes = Table(tabela_detalhes_dados, colWidths=[60, 180, 55, 240])
    t_detalhes.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#334155")),
            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
        ])
    )
    elements.append(t_detalhes)

    # 5. GERAR PDF
    doc.build(elements)
    pdf = buffer.getvalue()
    buffer.close()
    return pdf

# -------------------------------------------------------------------------
    # FOLHA 1: CAPA
    # -------------------------------------------------------------------------
    elements.append(Spacer(1, 80))
    try:
        logo = Image("ifiscal.png", width=350, height=160)
        logo.hAlign = 'CENTER'
        elements.append(logo)
    except Exception:
        elements.append(Paragraph("<b>[ LOGO: i-Fiscal / i-Saúde ]</b>", style_titulo_capa))

    elements.append(Spacer(1, 40))
    elements.append(Paragraph("Relatório i-Fiscal / i-Saúde", style_titulo_capa))
    elements.append(Spacer(1, 5))
    elements.append(Paragraph(
        "Índice de Fiscalização e Gestão da Saúde Municipal",
        ParagraphStyle('SubCapa', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=13, leading=16, textColor=colors.HexColor("#718096"), alignment=TA_CENTER)
    ))
    elements.append(Spacer(1, 25))
    elements.append(Paragraph(f"Exercício de Reference: <b>{ano_atual}</b>", style_ano_capa))
    elements.append(PageBreak())

    # -------------------------------------------------------------------------
    # FOLHA 2: SUMÁRIO
    # -------------------------------------------------------------------------
    elements.append(Paragraph("<b>SUMÁRIO DE AUDITORIA</b>", styles["Heading1"]))
    elements.append(Spacer(1, 20))

    style_item_esquerda = ParagraphStyle('ItemEsq', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=10, leading=13, textColor=colors.HexColor("#2c3e50"))
    style_pag_direita = ParagraphStyle('PagDir', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=10, leading=13, textColor=colors.HexColor("#00897b"), alignment=TA_RIGHT)

    dados_sumario = [
        [Paragraph("1. Resumo Executivo (Análise Comparativa de Gestão da Saúde)", style_item_esquerda), Paragraph("Pág. 3", style_pag_direita)],
        [Paragraph("2. Análise de Desempenho por Quesito i-Fiscal", style_item_esquerda), Paragraph("Pág. 3", style_pag_direita)],
        [Paragraph("3. Análise de Impacto e Penalidades (Eficiência Preventiva)", style_item_esquerda), Paragraph("Pág. 4", style_pag_direita)],
        [Paragraph("4. Diagnóstico de Reincidências (Gargalos Persistentes)", style_item_esquerda), Paragraph("Pág. 4", style_pag_direita)],
        [Paragraph("5. Alinhamento com a Agenda 2030 (Metas ODS / ONU)", style_item_esquerda), Paragraph("Pág. 5", style_pag_direita)],
        [Paragraph("6. Análise Comparativa de Prazos e Indicadores Históricos", style_item_esquerda), Paragraph("Pág. 5", style_pag_direita)],
        [Paragraph("7. Série Histórica do i-Fiscal (Consolidado Final)", style_item_esquerda), Paragraph("Pág. 6", style_pag_direita)],
    ]

    tabela_sumario = Table(dados_sumario, colWidths=[420, 75])
    tabela_sumario.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('LINEBELOW', (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
    ]))
    elements.append(tabela_sumario)
    elements.append(PageBreak())

    # -------------------------------------------------------------------------
    # FOLHA 3+: CONTEÚDO TÉCNICO COMPLETO
    # -------------------------------------------------------------------------
    elements.append(Paragraph(f"RELATÓRIO DE AUDITORIA i-FISCAL (GESTÃO EM SAÚDE) - {ano_atual}", styles["Heading1"]))
    elements.append(Spacer(1, 10))

    # --- SEÇÃO 1: RESUMO EXECUTIVO ---
    elements.append(Paragraph("1. RESUMO EXECUTIVO (ANÁLISE COMPARATIVA DE GESTÃO DA SAÚDE)", styles["Heading2"]))
    elements.append(Spacer(1, 6))

    dados_comparativos = [
        [Paragraph("Exercício", style_th), Paragraph("Pontuação Obtida", style_th), Paragraph("Faixa / Conceito", style_th), Paragraph("Variação Nominal", style_th), Paragraph("Variação Percentual", style_th)],
        [Paragraph(str(ano_ant), style_td_ano), Paragraph(f"{nota_anterior:.1f} pts", style_td_pts), Paragraph(str(faixa_anterior), style_td_faixa), Paragraph("-", style_td_var), Paragraph("-", style_td_var)],
        [Paragraph(str(ano_atual), style_td_ano), Paragraph(f"{nota_atual:.1f} pts", style_td_pts), Paragraph(str(faixa_real_atual), style_td_faixa), Paragraph(f"{seta_tendencia} {variacao_pontos:+.1f} pts", style_td_var), Paragraph(f"{seta_tendencia} {texto_percentual}", style_td_var)]
    ]

    tabela_comp = Table(dados_comparativos, colWidths=[80, 105, 95, 105, 110])
    tabela_comp.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c3e50")),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#f8fafc")),
        ("BACKGROUND", (0, 2), (-1, 2), colors.white),
    ]))
    elements.append(tabela_comp)
    elements.append(Spacer(1, 8))

    if variacao_pontos > 0:
        texto_analise = f"<b>Análise de Tendência:</b> O município registrou uma evolução de desempenho com incremento de <b>{texto_percentual}</b> na sua pontuação global da gestão em saúde comparado ao exercício de {ano_ant}."
    elif variacao_pontos < 0:
        texto_analise = f"<b>Análise de Tendência:</b> <font color='#dc3545'><b>Alerta de Retrocesso:</b></font> Foi identificada uma redução de <b>{texto_percentual}</b> na eficiência dos indicadores assistenciais e orçamentários da saúde em relação a {ano_ant}."
    else:
        texto_analise = "<b>Análise de Tendência:</b> O município apresentou estagnação absoluta (0.00%) no seu índice geral de conformidade i-Fiscal."
    
    elements.append(Paragraph(texto_analise, style_analise))
    elements.append(Spacer(1, 12))

    # --- SEÇÃO 2: DESEMPENHO POR QUESITO ---
    elements.append(Paragraph("2. ANÁLISE DE DESEMPENHO POR QUESITO i-FISCAL", styles["Heading2"]))
    elements.append(Spacer(1, 6))

    lista_pontos_fortes = []
    lista_pontos_fracos = []
    dados_consolidados = {}

    pontuacoes_max_norm = {normalizar_chave(k): v for k, v in PONTUACOES_MAX_IFISCAL.items()}

    for qid, info in dados.items():
        if str(qid).startswith("COM_") or not isinstance(info, dict):
            continue
        pts_obtidos = float(info.get("pontos", 0))
        valor_resposta = info.get("valor", "")
        link_evidencia = info.get("link", "")
        qid_limpo = normalizar_chave(qid)

        if qid_limpo not in pontuacoes_max_norm:
            continue

        if qid_limpo not in dados_consolidados:
            dados_consolidados[qid_limpo] = {"pts_obtidos": 0.0, "valores": [], "links": []}

        dados_consolidados[qid_limpo]["pts_obtidos"] += pts_obtidos
        if valor_resposta:
            dados_consolidados[qid_limpo]["valores"].append(limpar_xml(valor_resposta))
        if link_evidencia:
            link_limpo = limpar_xml(link_evidencia)
            if link_limpo not in dados_consolidados[qid_limpo]["links"]:
                dados_consolidados[qid_limpo]["links"].append(link_limpo)

    for qid_norm, info in dados_consolidados.items():
        pts_maximo = float(pontuacoes_max_norm.get(qid_norm, 10.0))
        if pts_maximo <= 0:
            pts_maximo = 10.0
        pts_obtidos = max(0.0, min(info["pts_obtidos"], pts_maximo))
        eficiencia = (pts_obtidos / pts_maximo) * 100
        respostas_unificadas = " | ".join(info["valores"]) if info["valores"] else "-"
        evidencias_unificadas = ", ".join(info["links"]) if info["links"] else ""

        item_data = {
            "qid": qid_norm,
            "pts_obtidos": pts_obtidos,
            "pts_maximo": pts_maximo,
            "eficiencia": eficiencia,
            "valor": respostas_unificadas,
            "link": evidencias_unificadas
        }
        if eficiencia < 80.0:
            lista_pontos_fracos.append(item_data)
        else:
            lista_pontos_fortes.append(item_data)

    if lista_pontos_fortes:
        elements.append(Paragraph("<b>✅ Pontos Fortes da Gestão da Saúde (Eficiência >= 80%):</b>", styles["Heading3"]))
        data_fortes = [[Paragraph("Quesito", style_th), Paragraph("Nota / Teto", style_th), Paragraph("Eficiência", style_th), Paragraph("Resposta / Evidência", style_th)]]
        for item in sorted(lista_pontos_fortes, key=lambda x: x["eficiencia"], reverse=True):
            texto_celula = f"<b>{item['valor']}</b>"
            if item['link']:
                texto_celula += f"<br/><font size=7 color='gray'>{item['link']}</font>"
            data_fortes.append([
                Paragraph(item['qid'], style_tabela_centro),
                Paragraph(f"{item['pts_obtidos']:.1f} / {item['pts_maximo']:.1f}", style_tabela_centro),
                Paragraph(f"{item['eficiencia']:.1f}%", style_tabela_centro),
                Paragraph(texto_celula, style_tabela_padrao)
            ])
        tabela_fortes = Table(data_fortes, colWidths=[65, 75, 65, 290])
        tabela_fortes.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#00897b")),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        elements.append(tabela_fortes)
        elements.append(Spacer(1, 10))

    if lista_pontos_fracos:
        elements.append(Paragraph("<b>⚠️ Oportunidades de Melhoria / Fragilidades (< 80% de Eficiência):</b>", styles["Heading3"]))
        data_fracos = [[Paragraph("Quesito", style_th), Paragraph("Nota / Teto", style_th), Paragraph("Eficiência", style_th), Paragraph("Resposta / Evidência", style_th)]]
        for item in sorted(lista_pontos_fracos, key=lambda x: x["eficiencia"]):
            texto_celula = f"<b>{item['valor']}</b>"
            if item['link']:
                texto_celula += f"<br/><font size=7 color='gray'>{item['link']}</font>"
            data_fracos.append([
                Paragraph(item['qid'], style_tabela_centro),
                Paragraph(f"{item['pts_obtidos']:.1f} / {item['pts_maximo']:.1f}", style_tabela_centro),
                Paragraph(f"{item['eficiencia']:.1f}%", style_tabela_centro),
                Paragraph(texto_celula, style_tabela_padrao)
            ])
        tabela_fracos = Table(data_fracos, colWidths=[65, 75, 65, 290])
        tabela_fracos.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e67e22")),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        elements.append(tabela_fracos)
        elements.append(Spacer(1, 12))

    # --- SEÇÃO 3: IMPACTO E PENALIDADES ---
    elements.append(Paragraph("3. ANÁLISE DE IMPACTO E PENALIDADES (EFICIÊNCIA PREVENTIVA)", styles["Heading2"]))
    elements.append(Spacer(1, 6))

    penalidades_max_norm = {normalizar_chave(k): v for k, v in PENALIDADES_MAX.items()}
    dados_penalidades = {}

    for k, v in dados.items():
        if isinstance(v, dict):
            dados_penalidades[normalizar_chave(k)] = v

    for qid_pen, val_max in penalidades_max_norm.items():
        if qid_pen not in dados_penalidades:
            dados_penalidades[qid_pen] = {"pontos": val_max, "valor": "Não preenchido / Ocultado por condicional", "link": ""}

    lista_penalidades = []
    reincidencias_detectadas = []

    for qid_norm, pen_max in penalidades_max_norm.items():
        if qid_norm in dados_penalidades:
            info = dados_penalidades[qid_norm]
            nota_real = float(info.get("pontos", 0.0))
            nota_risco = nota_real if nota_real <= 0.0 else 0.0

            if pen_max != 0:
                eficiencia_preventiva = (1.0 - (nota_risco / pen_max)) * 100.0
            else:
                eficiencia_preventiva = 100.0

            eficiencia_preventiva = max(0.0, min(eficiencia_preventiva, 100.0))
            lista_penalidades.append({
                "qid": qid_norm, "nota_real": nota_real, "pen_max": pen_max, "eficiencia": eficiencia_preventiva,
                "valor": info.get("valor", ""), "link": info.get("link", "")
            })

            if eficiencia_preventiva < 100.0 and isinstance(all_data, dict) and (ano_ant in all_data or str(ano_ant) in all_data):
                dados_ant_norm = {normalizar_chave(ka): va for ka, va in dados_ano_anterior.items() if isinstance(va, dict)}
                if qid_norm in dados_ant_norm:
                    info_ant = dados_ant_norm[qid_norm]
                    nota_real_ant = float(info_ant.get("pontos", 0.0))
                    if nota_real == nota_real_ant:
                        reincidencias_detectadas.append({
                            "qid": qid_norm, "tipo": "Penalidade Aplicada",
                            "detalhe": f"Impacto Recorrente de Penalidade de {nota_real:.1f} pts",
                            "ant": f"{nota_real_ant:.1f} pts", "atual": f"{nota_real:.1f} pts"
                        })

    if lista_penalidades:
        data_penalidades = [[
            Paragraph("Quesito", style_th),
            Paragraph("Penalidade Aplicada", style_th),
            Paragraph("Pior Cenário", style_th),
            Paragraph("Eficiência Preventiva", style_th),
            Paragraph("Status de Risco", style_th)
        ]]

        def ordenar_quesitos(x):
            limpo = ''.join(c for c in x["qid"] if c.isdigit() or c == '.')
            partes = [int(i) for i in limpo.split('.') if i.isdigit()]
            return partes if partes else [999]

        for item in sorted(lista_penalidades, key=ordenar_quesitos):
            nota_txt = f"{item['nota_real']:.1f} pts"
            teto_txt = f"{item['pen_max']:.1f} pts"
            ef_txt = f"{item['eficiencia']:.1f}%"

            if item['eficiencia'] >= 100.0:
                status = "<font color='#2e7d32'><b>Risco Mitigado</b></font>"
            elif item['eficiencia'] <= 0.0:
                status = "<font color='#c0392b'><b>Impacto Máximo</b></font>"
            else:
                status = "<font color='#d35400'><b>Impacto Parcial</b></font>"

            data_penalidades.append([
                Paragraph(item['qid'], style_tabela_centro),
                Paragraph(nota_txt, style_tabela_centro),
                Paragraph(teto_txt, style_tabela_centro),
                Paragraph(ef_txt, style_tabela_centro),
                Paragraph(status, style_tabela_padrao)
            ])

        tabela_pen = Table(data_penalidades, colWidths=[70, 105, 80, 115, 125])
        tabela_pen.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1b4f72")),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        elements.append(tabela_pen)
        elements.append(Spacer(1, 12))

    # --- SEÇÃO 4: DIAGNÓSTICO DE REINCIDÊNCIAS ---
    elements.append(Paragraph("4. DIAGNÓSTICO DE REINCIDÊNCIAS (GARGALOS PERSISTENTES)", styles["Heading2"]))
    elements.append(Spacer(1, 6))

    dados_analise_reinc = dados.copy()

    if subquestoes_saude_local and resposta_condicional_na_local:
        for sub_id in subquestoes_saude_local:
            if sub_id not in dados_analise_reinc:
                dados_analise_reinc[sub_id] = {"pontos": 0.0, "valor": "Não se aplica / Zerado por Condicional", "link": ""}

    for qid, info_atual in dados_analise_reinc.items():
        if str(qid).startswith("COM_") or not isinstance(info_atual, dict):
            continue

        qid_str = str(qid).strip()
        qid_limpo = normalizar_chave(qid_str)

        valor_atual = str(info_atual.get("valor", "")).strip().lower()
        pts_obtidos_atual = float(info_atual.get("pontos", 0.0))

        if not valor_atual or "selecione" in valor_atual or pts_obtidos_atual == 0.0:
            continue

        if "_" in qid_limpo:
            chave_mae = qid_limpo.split("_")[0]
        else:
            partes_chave = qid_limpo.split('.')
            if len(partes_chave) > 2:
                chave_mae = f"{partes_chave[0]}.{partes_chave[1]}"
            else:
                chave_mae = qid_limpo

        if chave_mae not in TETOS_VALIDOS:
            continue

        if dados_ano_anterior and isinstance(dados_ano_anterior, dict):
            dados_ant_norm = {normalizar_chave(ka): va for ka, va in dados_ano_anterior.items() if isinstance(va, dict)}
            if qid_limpo in dados_ant_norm:
                info_ant = dados_ant_norm[qid_limpo]
                pts_ant = float(info_ant.get("pontos", 0.0))
                if pts_obtidos_atual < float(TETOS_VALIDOS[chave_mae]) and pts_obtidos_atual == pts_ant:
                    reincidencias_detectadas.append({
                        "qid": qid_limpo,
                        "tipo": "Perda Recorrente de Pontos",
                        "detalhe": f"Atingiu {pts_obtidos_atual:.1f} pts de {TETOS_VALIDOS[chave_mae]:.1f} pts em ambos exercícios",
                        "ant": f"{pts_ant:.1f} pts",
                        "atual": f"{pts_obtidos_atual:.1f} pts"
                    })

    if reincidencias_detectadas:
        data_reinc = [[Paragraph("Quesito", style_th), Paragraph("Tipo de Reincidência", style_th), Paragraph("Exercício Anterior", style_th), Paragraph("Exercício Atual", style_th), Paragraph("Detalhamento do Gargalo", style_th)]]
        for r in reincidencias_detectadas:
            data_reinc.append([
                Paragraph(r["qid"], style_tabela_centro),
                Paragraph(r["tipo"], style_tabela_padrao),
                Paragraph(r["ant"], style_tabela_centro),
                Paragraph(r["atual"], style_tabela_centro),
                Paragraph(r["detalhe"], style_tabela_padrao)
            ])
        tabela_reinc = Table(data_reinc, colWidths=[65, 110, 75, 75, 170])
        tabela_reinc.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#7f1d1d")),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        elements.append(tabela_reinc)
    else:
        elements.append(Paragraph("<i>Nenhuma reincidência crítica de perda de pontuação foi identificada entre o exercício atual e o anterior.</i>", style_analise))
    
    elements.append(Spacer(1, 12))

    # --- SEÇÃO 5: ALINHAMENTO AGENDA 2030 (ODS) ---
    elements.append(Paragraph("5. ALINHAMENTO COM A AGENDA 2030 (METAS ODS / ONU)", styles["Heading2"]))
    elements.append(Spacer(1, 6))
    
    data_ods = [
        [Paragraph("Objetivo de Desenvolvimento Sustentável (ODS)", style_th), Paragraph("Métrica / Vínculo i-Fiscal", style_th), Paragraph("Nível de Conformidade", style_th)],
        [Paragraph("ODS 3: Saúde e Bem-Estar", style_tabela_padrao), Paragraph("Cobertura da Atenção Básica e Medicamentos Essenciais", style_tabela_padrao), Paragraph("<font color='#2e7d32'><b>Conforme</b></font>", style_tabela_centro)],
        [Paragraph("ODS 16: Paz, Justiça e Instituições Eficazes", style_tabela_padrao), Paragraph("Transparência Ativa e Prestação de Contas no FMS", style_tabela_padrao), Paragraph("<font color='#d35400'><b>Parcial</b></font>", style_tabela_centro)],
    ]
    tabela_ods = Table(data_ods, colWidths=[160, 210, 125])
    tabela_ods.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f766e")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    elements.append(tabela_ods)
    elements.append(Spacer(1, 12))

    # --- SEÇÃO 6: ANÁLISE COMPARATIVA DE PRAZOS ---
    elements.append(Paragraph("6. ANÁLISE COMPARATIVA DE PRAZOS E INDICADORES HISTÓRICOS", styles["Heading2"]))
    elements.append(Spacer(1, 6))
    
    data_prazos = [
        [Paragraph("Indicador de Tempestividade", style_th), Paragraph("Prazo Regulamentar", style_th), Paragraph("Data de Envio / Cumprimento", style_th), Paragraph("Status", style_th)],
        [Paragraph("Envio do Relatório Quadrimestral (RQST)", style_tabela_padrao), Paragraph("30 dias pós-quadrimestre", style_tabela_centro), Paragraph("No Prazo", style_tabela_centro), Paragraph("<font color='#2e7d32'><b>Adimplente</b></font>", style_tabela_centro)],
        [Paragraph("Publicação do RGF / RREO da Saúde", style_tabela_padrao), Paragraph("30 dias pós-bimestre", style_tabela_centro), Paragraph("No Prazo", style_tabela_centro), Paragraph("<font color='#2e7d32'><b>Adimplente</b></font>", style_tabela_centro)],
    ]
    tabela_prazos = Table(data_prazos, colWidths=[160, 110, 125, 100])
    tabela_prazos.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#334155")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    elements.append(tabela_prazos)
    elements.append(Spacer(1, 12))

    # --- SEÇÃO 7: SÉRIE HISTÓRICA DO i-FISCAL ---
    elements.append(Paragraph("7. SÉRIE HISTÓRICA DO i-FISCAL (CONSOLIDADO FINAL)", styles["Heading2"]))
    elements.append(Spacer(1, 6))

    data_serie = [[Paragraph("Ano", style_th), Paragraph("Pontuação Total", style_th), Paragraph("Faixa Alcançada", style_th), Paragraph("Evolução", style_th)]]
    
    # Processa histórico disponível em all_data
    anos_ordenados = sorted([a for a in all_data.keys() if str(a).isdigit()], key=lambda x: int(x))
    if str(ano_atual) not in [str(a) for a in anos_ordenados]:
        anos_ordenados.append(str(ano_atual))

    for ano_item in anos_ordenados:
        if str(ano_item) == str(ano_atual):
            pts_h = nota_atual
            faixa_h = faixa_real_atual
        else:
            d_h = all_data.get(ano_item)
            if isinstance(d_h, dict):
                pts_h = float(d_h.get("pontuacao_total", 0.0))
            else:
                try:
                    pts_h = float(d_h)
                except (ValueError, TypeError):
                    pts_h = 0.0
            faixa_h = converter_pontos_em_faixa_ifiscal(pts_h)

        data_serie.append([
            Paragraph(str(ano_item), style_tabela_centro),
            Paragraph(f"{pts_h:.2f} pts", style_tabela_centro),
            Paragraph(str(faixa_h), style_tabela_centro),
            Paragraph("Consolidado", style_tabela_centro)
        ])

    tabela_serie = Table(data_serie, colWidths=[80, 130, 130, 155])
    tabela_serie.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    elements.append(tabela_serie)

    # -------------------------------------------------------------------------
    # 5. GERAR PDF FINAL
    # -------------------------------------------------------------------------
    doc.build(elements)
    pdf = buffer.getvalue()
    buffer.close()
    return pdf

import logging
import re
import plotly.graph_objects as go
import streamlit as st

import logging
import plotly.graph_objects as go
import streamlit as st

import logging
import plotly.graph_objects as go
import streamlit as st

# =============================================================================
# 4. SIDEBAR - iSaúde
# =============================================================================


def zerar_questionario_isaude(ano: int):
    """Deleta todas as respostas do ano selecionado na tabela respostas_isaude."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM respostas_isaude WHERE ano = %s",
                    (int(ano),),
                )
            conn.commit()
        st.cache_data.clear()  # Limpa o cache após deletar
    except Exception as e:
        logging.error(f"Erro ao zerar questionário iSaúde: {e}")
        st.error(f"Erro ao zerar questionário iSaúde: {e}")


@st.dialog("⚠️ Zerar Respostas do iSaúde")
def confirmar_zerar_dialog_isaude(ano):
    st.warning(
        f"Tem certeza que deseja apagar TODAS as respostas do iSaúde para o ano {ano}?"
    )
    st.write(
        "Esta ação é irreversível e excluirá os dados salvos no banco Neon."
    )

    # Campo para inserção da senha de confirmação (Igual ao iAMB)
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
                    zerar_questionario_isaude(ano)

                    # Limpa a sessão
                    key_ano = f"respostas_isaude_{ano}"
                    st.session_state[key_ano] = {}

                    st.toast(
                        "Respostas do iSaúde zeradas com sucesso!", icon="🗑️"
                    )
                    st.rerun()
                except Exception as e:
                    st.error(f"Erro ao zerar banco: {e}")
            else:
                st.error("🔒 Senha incorreta! Ação cancelada.")

    with col2:
        if st.button("Cancelar", use_container_width=True):
            st.rerun()


def render_sidebar_isaude():
    st.sidebar.title("🏥 Painel de Controle - iSaúde")
    anos = [2024, 2025, 2026, 2027, 2028, 2029, 2030]

    # Seleção do ano no session_state
    ano_sel = st.sidebar.selectbox(
        "Ano de Referência:", anos, key="ano_referencia_isaude"
    )

    if "load_respostas_isaude" in globals():
        res_data = load_respostas_isaude(ano_sel)
    else:
        res_data = load_respostas(ano_sel)

    total_pts = sum(
        float(item.get("pontos", 0.0))
        for item in res_data.values()
        if isinstance(item, dict)
    )

    # Régua de Classificação IEGM / iSaúde
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

    st.sidebar.metric("Pontuação Total iSaúde", f"{total_pts:.1f} pts")
    st.sidebar.markdown(
        f"**Faixa:** <span style='color:{cor}; font-size:18px; font-weight:bold;'>{faixa}</span>",
        unsafe_allow_html=True,
    )

    st.sidebar.divider()

    col1, col2 = st.sidebar.columns(2)

    # Botão de Download direto
    with col1:
        pdf_bytes = b""
        if "gerar_relatorio_pdf_isaude" in globals():
            res_pdf = gerar_relatorio_pdf_isaude(
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
            file_name=f"Relatorio_iSaude_{ano_sel}.pdf",
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
            confirmar_zerar_dialog_isaude(ano_sel)

    return total_pts, res_data, ano_sel


# =============================================================================
# 5. GRÁFICOS E HISTÓRICO - iSaúde
# =============================================================================


def get_all_years_data_isaude() -> dict:
    """Busca o histórico de dados de todos os anos salvos na tabela respostas_isaude e session_state."""
    all_data = {}

    # 1. Carrega via Banco
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT DISTINCT ano FROM respostas_isaude ORDER BY ano"
                )
                anos_banco = [row[0] for row in cursor.fetchall()]
                for a in anos_banco:
                    all_data[a] = (
                        load_respostas_isaude(a)
                        if "load_respostas_isaude" in globals()
                        else load_respostas(a)
                    )
    except Exception as e:
        logging.error(
            f"Erro ao buscar histórico de anos iSaúde no banco: {e}"
        )

    # 2. Carrega via Session State (para capturar anos ainda não persistidos)
    prefixo = "respostas_isaude_"
    for key in list(st.session_state.keys()):
        if key.startswith(prefixo):
            try:
                ano = int(key.replace(prefixo, ""))
                if ano not in all_data or not all_data[ano]:
                    all_data[ano] = st.session_state[key]
            except ValueError:
                continue

    return all_data


def get_faixa_isaude(total: float) -> str:
    if total <= 500:
        return "C - Inefetivo"
    if total <= 599:
        return "C+ - Em Adequação"
    if total <= 749:
        return "B - Efetivo"
    if total <= 899:
        return "B+ - Muito Efetivo"
    return "A - Altamente Efetivo"


def grafico_pontos_por_ano_isaude(all_data):
    """Gráfico de barras vertical com pontos totais por ano para o iSaúde."""
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
            hovertemplate="<b>Ano: %{x}</b><br>iSaúde Total: %{y:.1f} pts<extra></extra>",
        )
    )

    fig.update_layout(
        title="Índice Histórico iSaúde (Saúde Pública) por Exercício",
        xaxis_title="Ano",
        yaxis_title="Pontuação iSaúde",
        plot_bgcolor="white",
        paper_bgcolor="white",
        showlegend=False,
        height=400,
    )

    return fig


def render_graficos_isaude(res_data_atual, ano_sel):
    st.header("📊 Painel de Análise do iSaúde")

    all_data = get_all_years_data_isaude()

    if not all_data:
        st.info(
            "Nenhum dado do iSaúde registrado ainda. Preencha os itens para visualizar os gráficos."
        )
        return

    st.plotly_chart(
        grafico_pontos_por_ano_isaude(all_data), use_container_width=True
    )


# =============================================================================
# 6. FORMULÁRIO PRINCIPAL - iSaúde
# =============================================================================


def mostrar_formulario_saude():
    total_pts, res_data, ano_sel = render_sidebar_isaude()

    st.title(f"🏥 Saúde Pública (iSaúde) - Exercício {ano_sel}")

    aba_quest, aba_graf = st.tabs(
        ["📋 Questionário iSaúde", "📊 Gráficos e Evolução"]
    )

    with aba_quest:
        st.subheader("Formulário de Avaliação")
        st.caption(
            "ℹ *Atenção à consistência dos dados salvos no banco. Salvamento automático via callback.*"
        )

 # =============================================================================
        # QUESITO 1.0 • PLANO MUNICIPAL DE SAÚDE (MODELO PADRONIZADO iGov / iSaúde)
        # =============================================================================
        with st.container(key=f"container_bloco_isaude_1_0_{ano_sel}", border=True):
            with st.expander("📌 Quesito 1.0 - Participação do Conselho Municipal de Saúde", expanded=True):
                st.subheader("1.0 • Participação do Conselho Municipal de Saúde")
                st.write(
                    "**O Conselho Municipal de Saúde participou da elaboração do Plano Municipal de Saúde 2026-2029?**"
                )
                st.caption("ℹ *Preencha os campos abaixo e clique no botão 'Salvar Quesito 1.0' para registrar.*")

                # Dicionário com Mapeamento de Opções e Pontuações do iSaúde
                opcoes_10 = {
                    "Selecione...": 0.0,
                    "Sim, com propostas para construção das diretrizes e metas da saúde municipal – 05": 5.0,
                    "Sim, apenas aprovando as propostas da gestão (Secretaria Municipal) – 02": 2.0,
                    "Não – 00": 0.0,
                }

                # Estado inicial / persistente
                d10 = res_data.get("1.0") or {
                    "valor": "Selecione...",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_10 = d10.get("valor", "Selecione...")

                # Trata migração de legado caso no banco esteja salvo o formato simplificado/antigo
                if v_salvo_10 == "Sim, com propostas para construção das diretrizes e metas da saúde municipal":
                    v_salvo_10 = "Sim, com propostas para construção das diretrizes e metas da saúde municipal – 05"
                elif v_salvo_10 == "Sim, apenas aprovando as propostas da gestão (Secretaria Municipal)":
                    v_salvo_10 = "Sim, apenas aprovando as propostas da gestão (Secretaria Municipal) – 02"
                elif v_salvo_10 == "Não":
                    v_salvo_10 = "Não – 00"

                evidencia_10_salva = d10.get("link", "")

                # Chaves fixas por componente e ano
                chave_radio_10 = f"r_10_{ano_sel}"
                chave_link_10 = f"l_10_txt_{ano_sel}"

                c10_1, c10_2 = st.columns([1, 1])
                with c10_1:
                    lista_opcoes_10 = list(opcoes_10.keys())
                    idx_10 = lista_opcoes_10.index(v_salvo_10) if v_salvo_10 in lista_opcoes_10 else 0

                    val_radio_10 = st.radio(
                        "Selecione a alternativa correspondente:",
                        options=lista_opcoes_10,
                        index=idx_10,
                        key=chave_radio_10,
                    )

                with c10_2:
                    link_10 = st.text_area(
                        "Link de Evidência (Ata da reunião, Resolução do Conselho, etc.):",
                        value=evidencia_10_salva,
                        key=chave_link_10,
                        placeholder="Insira o link oficial da ata, resolução ou publicação referente ao quesito 1.0...",
                        height=100,
                    )
                    placeholder_links_10 = st.empty()
                    links_10_visuais = re.findall(REGEX_PURE_URL, link_10 or "")
                    if links_10_visuais:
                        placeholder_links_10.markdown(
                            "**🔗 Link ativo:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_10_visuais]
                            )
                        )

                # Renderização do chat de comentários
                bloco_comentarios_isaude("1.0", res_data)

                # Botão de salvamento
                if st.button("💾 Salvar Quesito 1.0", key=f"btn_salvar_1_0_{ano_sel}", type="primary"):
                    val_salvar = st.session_state.get(chave_radio_10, v_salvo_10)
                    pts_10 = float(opcoes_10.get(val_salvar, 0.0))
                    lnk_val = link_10.strip()

                    comentarios_historico = d10.get("comentarios", [])

                    save_resp_isaude(
                        qid="1.0",
                        valor=val_salvar,
                        pontos=pts_10,
                        link=lnk_val,
                        comentarios=comentarios_historico
                    )

                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_10_salva or "")]

                    # Se detectou novo link, ativa o modal antes de recarregar a tela
                    if lnk_val != evidencia_10_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_1_0_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_1_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 1.0 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                pts_atuais_10 = d10.get("pontos", 0.0)
                cor_txt_10 = "#28a745" if pts_atuais_10 > 0.0 else "#6c757d"

                st.markdown(
                    f"<span style='color:{cor_txt_10}; font-weight:bold;'>"
                    f"📊 Impacto de Pontuação no Quesito 1.0: +{pts_atuais_10:.1f} pontos</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 1.0 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_1_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("1.0", st.session_state.get(f"links_pendentes_1_0_{ano_sel}", []), ano_sel)

        # =============================================================================
        # QUESITO 2.0 • CONSELHO MUNICIPAL DE SAÚDE (MODELO PADRONIZADO iGov / iSaúde)
        # =============================================================================
        with st.container(key=f"container_bloco_isaude_2_0_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 2.0 - Conselho Municipal de Saúde em {ano_sel}", expanded=True):
                st.subheader("2.0 • Conselho Municipal de Saúde")
                st.write(
                    f"**O Conselho Municipal de Saúde está institucionalizado e em regular funcionamento no ano de {ano_sel}?**"
                )
                st.caption("ℹ *Preencha os campos abaixo e clique no botão 'Salvar Quesito 2.0' para registrar.*")

                # Dicionário com Mapeamento de Opções e Pontuações
                opcoes_20 = {
                    "Selecione...": 0.0,
                    "Sim": 2.0,
                    "Não": 0.0,
                }

                # Estado inicial / persistente
                d20 = res_data.get("2.0") or {
                    "valor": "Selecione...",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_20 = d20.get("valor", "Selecione...")
                evidencia_20_salva = d20.get("link", "")

                # Chaves fixas por componente e ano
                chave_radio_20 = f"r_20_{ano_sel}"
                chave_link_20 = f"l_20_txt_{ano_sel}"

                c20_1, c20_2 = st.columns([1, 1])
                with c20_1:
                    lista_opcoes_20 = list(opcoes_20.keys())
                    idx_20 = lista_opcoes_20.index(v_salvo_20) if v_salvo_20 in lista_opcoes_20 else 0

                    val_radio_20 = st.radio(
                        "Selecione a alternativa correspondente:",
                        options=lista_opcoes_20,
                        index=idx_20,
                        key=chave_radio_20,
                    )

                with c20_2:
                    link_20 = st.text_area(
                        "Link/Evidência (Atas das reuniões, lei de criação do conselho ou ato de nomeação dos conselheiros vigentes):",
                        value=evidencia_20_salva,
                        key=chave_link_20,
                        placeholder="Insira o link oficial referente ao quesito 2.0...",
                        height=100,
                    )
                    placeholder_links_20 = st.empty()
                    links_20_visuais = re.findall(REGEX_PURE_URL, link_20 or "")
                    if links_20_visuais:
                        placeholder_links_20.markdown(
                            "**🔗 Link ativo:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_20_visuais]
                            )
                        )

                # Renderização do chat de comentários
                bloco_comentarios_isaude("2.0", res_data)

                # Botão de salvamento
                if st.button("💾 Salvar Quesito 2.0", key=f"btn_salvar_2_0_{ano_sel}", type="primary"):
                    val_salvar = st.session_state.get(chave_radio_20, v_salvo_20)
                    pts_20 = float(opcoes_20.get(val_salvar, 0.0))
                    lnk_val = link_20.strip()

                    comentarios_historico = d20.get("comentarios", [])

                    save_resp_isaude(
                        qid="2.0",
                        valor=val_salvar,
                        pontos=pts_20,
                        link=lnk_val,
                        comentarios=comentarios_historico
                    )

                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_20_salva or "")]

                    if lnk_val != evidencia_20_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_2_0_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_2_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 2.0 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                pts_atuais_20 = d20.get("pontos", 0.0)
                cor_txt_20 = "#28a745" if pts_atuais_20 > 0.0 else "#6c757d"

                st.markdown(
                    f"<span style='color:{cor_txt_20}; font-weight:bold;'>"
                    f"📊 Impacto de Pontuação no Quesito 2.0: +{pts_atuais_20:.1f} pontos</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 2.0 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_2_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("2.0", st.session_state.get(f"links_pendentes_2_0_{ano_sel}", []), ano_sel)

        # =============================================================================
        # QUESITO 3.0 • APROVAÇÃO DA PAS (MODELO PADRONIZADO iGov / iSaúde)
        # =============================================================================
        with st.container(key=f"container_bloco_isaude_3_0_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 3.0 - Aprovação da Programação Anual de Saúde (PAS) {ano_sel}", expanded=True):
                st.subheader(f"3.0 • Aprovação da Programação Anual de Saúde (PAS) {ano_sel}")
                st.write(
                    f"**Quando ocorreu a aprovação da Programação Anual de Saúde de {ano_sel} pelo Conselho Municipal de Saúde?**"
                )
                st.caption("ℹ *Preencha os campos abaixo e clique no botão 'Salvar Quesito 3.0' para registrar.*")

                # Mapeamento de Opções e Pontuações do Quesito 3.0
                opcoes_30 = {
                    "Selecione...": 0.0,
                    f"Até prazo de envio à Câmara Municipal do projeto de lei de diretrizes orçamentárias {ano_sel} – 10": 10.0,
                    f"Aprovado após prazo de envio à Câmara Municipal do projeto de lei de diretrizes orçamentárias {ano_sel}, mas antes da aprovação da LDO {ano_sel} pela Câmara Municipal – 07": 7.0,
                    f"Aprovado após a aprovação da LDO {ano_sel} pela Câmara Municipal – 03": 3.0,
                    "Não aprovado – 00": 0.0,
                }

                # Estado inicial / persistente
                d30 = res_data.get("3.0") or {
                    "valor": "Selecione...",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_30 = d30.get("valor", "Selecione...")
                evidencia_30_salva = d30.get("link", "")

                # Chaves fixas por componente e ano
                chave_radio_30 = f"r_30_{ano_sel}"
                chave_link_30 = f"l_30_txt_{ano_sel}"

                c30_1, c30_2 = st.columns([1, 1])
                with c30_1:
                    lista_opcoes_30 = list(opcoes_30.keys())
                    idx_30 = lista_opcoes_30.index(v_salvo_30) if v_salvo_30 in lista_opcoes_30 else 0

                    val_radio_30 = st.radio(
                        "Selecione a alternativa correspondente:",
                        options=lista_opcoes_30,
                        index=idx_30,
                        key=chave_radio_30,
                    )

                with c30_2:
                    link_30 = st.text_area(
                        f"Link/Evidência (Ata/Resolução do CMS de aprovação da PAS pareada com a LDO {ano_sel}):",
                        value=evidencia_30_salva,
                        key=chave_link_30,
                        placeholder="Insira o link oficial referente ao quesito 3.0...",
                        height=100,
                    )
                    placeholder_links_30 = st.empty()
                    links_30_visuais = re.findall(REGEX_PURE_URL, link_30 or "")
                    if links_30_visuais:
                        placeholder_links_30.markdown(
                            "**🔗 Link ativo:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_30_visuais]
                            )
                        )

                # Renderização do chat de comentários
                bloco_comentarios_isaude("3.0", res_data)

                # Botão de salvamento
                if st.button("💾 Salvar Quesito 3.0", key=f"btn_salvar_3_0_{ano_sel}", type="primary"):
                    val_salvar = st.session_state.get(chave_radio_30, v_salvo_30)
                    pts_30 = float(opcoes_30.get(val_salvar, 0.0))
                    lnk_val = link_30.strip()

                    comentarios_historico = d30.get("comentarios", [])

                    save_resp_isaude(
                        qid="3.0",
                        valor=val_salvar,
                        pontos=pts_30,
                        link=lnk_val,
                        comentarios=comentarios_historico
                    )

                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_30_salva or "")]

                    if lnk_val != evidencia_30_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_3_0_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_3_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 3.0 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                pts_atuais_30 = d30.get("pontos", 0.0)
                cor_txt_30 = "#28a745" if pts_atuais_30 > 0.0 else "#6c757d"

                st.markdown(
                    f"<span style='color:{cor_txt_30}; font-weight:bold;'>"
                    f"📊 Impacto de Pontuação no Quesito 3.0: +{pts_atuais_30:.1f} pontos</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 3.0 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_3_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("3.0", st.session_state.get(f"links_pendentes_3_0_{ano_sel}", []), ano_sel)

        # =============================================================================
        # QUESITO 3.1 • EXECUÇÃO DAS AÇÕES DA PAS (MODELO PADRONIZADO iGov / iSaúde)
        # =============================================================================
        with st.container(key=f"container_bloco_isaude_3_1_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 3.1 - Execução das Ações Previstas na PAS {ano_sel}", expanded=True):
                st.subheader(f"3.1 • Execução das Ações Previstas na PAS {ano_sel}")
                st.write(
                    f"**As ações previstas na Programação Anual de Saúde de {ano_sel} foram executadas?**"
                )
                st.caption("ℹ *Preencha os campos abaixo e clique no botão 'Salvar Quesito 3.1' para registrar.*")

                # Mapeamento de Opções e Pontuações do Quesito 3.1
                opcoes_31 = {
                    "Selecione...": 0.0,
                    "Sim, todas as ações foram executadas – 04": 4.0,
                    "Sim, a maior parte das ações foram executadas – 02": 2.0,
                    "Sim, a menor parte das ações foram executadas – 01": 1.0,
                    "Nenhuma ação foi executada – 00": 0.0,
                }

                # Estado inicial / persistente
                d31 = res_data.get("3.1") or {
                    "valor": "Selecione...",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_31 = d31.get("valor", "Selecione...")
                evidencia_31_salva = d31.get("link", "")

                # Chaves fixas por componente e ano
                chave_radio_31 = f"r_31_{ano_sel}"
                chave_link_31 = f"l_31_txt_{ano_sel}"

                c31_1, c31_2 = st.columns([1, 1])
                with c31_1:
                    lista_opcoes_31 = list(opcoes_31.keys())
                    idx_31 = lista_opcoes_31.index(v_salvo_31) if v_salvo_31 in lista_opcoes_31 else 0

                    val_radio_31 = st.radio(
                        "Selecione a alternativa correspondente:",
                        options=lista_opcoes_31,
                        index=idx_31,
                        key=chave_radio_31,
                    )

                with c31_2:
                    link_31 = st.text_area(
                        "Link/Evidência (Relatório Anual de Gestão - RAG, balanço de metas físicas):",
                        value=evidencia_31_salva,
                        key=chave_link_31,
                        placeholder="Insira o link oficial referente ao quesito 3.1...",
                        height=100,
                    )
                    placeholder_links_31 = st.empty()
                    links_31_visuais = re.findall(REGEX_PURE_URL, link_31 or "")
                    if links_31_visuais:
                        placeholder_links_31.markdown(
                            "**🔗 Link ativo:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_31_visuais]
                            )
                        )

                # Renderização do chat de comentários
                bloco_comentarios_isaude("3.1", res_data)

                # Botão de salvamento
                if st.button("💾 Salvar Quesito 3.1", key=f"btn_salvar_3_1_{ano_sel}", type="primary"):
                    val_salvar = st.session_state.get(chave_radio_31, v_salvo_31)
                    pts_31 = float(opcoes_31.get(val_salvar, 0.0))
                    lnk_val = link_31.strip()

                    comentarios_historico = d31.get("comentarios", [])

                    save_resp_isaude(
                        qid="3.1",
                        valor=val_salvar,
                        pontos=pts_31,
                        link=lnk_val,
                        comentarios=comentarios_historico
                    )

                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_31_salva or "")]

                    if lnk_val != evidencia_31_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_3_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_3_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 3.1 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                pts_atuais_31 = d31.get("pontos", 0.0)
                cor_txt_31 = "#28a745" if pts_atuais_31 > 0.0 else "#6c757d"

                st.markdown(
                    f"<span style='color:{cor_txt_31}; font-weight:bold;'>"
                    f"📊 Impacto de Pontuação no Quesito 3.1: +{pts_atuais_31:.1f} pontos</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 3.1 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_3_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("3.1", st.session_state.get(f"links_pendentes_3_1_{ano_sel}", []), ano_sel)

        # =============================================================================
        # QUESITO 3.2 • CUMPRIMENTO DE METAS DE INDICADORES NA PAS
        # =============================================================================
        with st.container(key=f"container_bloco_isaude_3_2_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 3.2 - Cumprimento de Metas de Indicadores na PAS {ano_sel}", expanded=True):
                st.subheader(f"3.2 • Cumprimento de Metas de Indicadores na PAS {ano_sel}")
                st.write(
                    f"**As metas previstas para os indicadores foram atingidas na Programação Anual de Saúde de {ano_sel}?**"
                )
                st.caption("ℹ *Preencha os campos abaixo e clique no botão 'Salvar Quesito 3.2' para registrar.*")

                # Mapeamento de Opções e Pontuações do Quesito 3.2
                opcoes_32 = {
                    "Selecione...": 0.0,
                    "Sim, todas as metas foram atingidas – 04": 4.0,
                    "Sim, a maior parte das metas foram atingidas – 02": 2.0,
                    "Sim, a menor parte das metas foram atingidas – 01": 1.0,
                    "Não – 00": 0.0,
                }

                # Estado inicial / persistente
                d32 = res_data.get("3.2") or {
                    "valor": "Selecione...",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_32 = d32.get("valor", "Selecione...")
                evidencia_32_salva = d32.get("link", "")

                # Chaves fixas por componente e ano
                chave_radio_32 = f"r_32_{ano_sel}"
                chave_link_32 = f"l_32_txt_{ano_sel}"

                c32_1, c32_2 = st.columns([1, 1])
                with c32_1:
                    lista_opcoes_32 = list(opcoes_32.keys())
                    idx_32 = lista_opcoes_32.index(v_salvo_32) if v_salvo_32 in lista_opcoes_32 else 0

                    val_radio_32 = st.radio(
                        "Selecione a alternativa correspondente:",
                        options=lista_opcoes_32,
                        index=idx_32,
                        key=chave_radio_32,
                    )

                with c32_2:
                    link_32 = st.text_area(
                        "Link/Evidência (Painel de indicadores do SIOPS, DigiSUS ou atas de monitoramento):",
                        value=evidencia_32_salva,
                        key=chave_link_32,
                        placeholder="Insira o link oficial referente ao quesito 3.2...",
                        height=100,
                    )
                    placeholder_links_32 = st.empty()
                    links_32_visuais = re.findall(REGEX_PURE_URL, link_32 or "")
                    if links_32_visuais:
                        placeholder_links_32.markdown(
                            "**🔗 Link ativo:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_32_visuais]
                            )
                        )

                # Renderização do chat de comentários
                bloco_comentarios_isaude("3.2", res_data)

                # Botão de salvamento
                if st.button("💾 Salvar Quesito 3.2", key=f"btn_salvar_3_2_{ano_sel}", type="primary"):
                    val_salvar = st.session_state.get(chave_radio_32, v_salvo_32)
                    pts_32 = float(opcoes_32.get(val_salvar, 0.0))
                    lnk_val = link_32.strip()

                    comentarios_historico = d32.get("comentarios", [])

                    save_resp_isaude(
                        qid="3.2",
                        valor=val_salvar,
                        pontos=pts_32,
                        link=lnk_val,
                        comentarios=comentarios_historico
                    )

                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_32_salva or "")]

                    if lnk_val != evidencia_32_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_3_2_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_3_2_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 3.2 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                pts_atuais_32 = d32.get("pontos", 0.0)
                cor_txt_32 = "#28a745" if pts_atuais_32 > 0.0 else "#6c757d"

                st.markdown(
                    f"<span style='color:{cor_txt_32}; font-weight:bold;'>"
                    f"📊 Impacto de Pontuação no Quesito 3.2: +{pts_atuais_32:.1f} pontos</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 3.2 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_3_2_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("3.2", st.session_state.get(f"links_pendentes_3_2_{ano_sel}", []), ano_sel)

        # =============================================================================
        # QUESITO 4.0 • CURSOS E TREINAMENTOS OFERECIDOS (MÚLTIPLA ESCOLHA)
        # =============================================================================
        with st.container(key=f"container_bloco_isaude_4_0_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 4.0 - Cursos/Treinamento sobre Saúde em {ano_sel}", expanded=True):
                st.subheader(f"4.0 • Cursos/Treinamento sobre Saúde em {ano_sel}")
                st.write(
                    f"**A Secretaria Municipal de Saúde ou similar ofereceu cursos/treinamento sobre saúde para qual público no ano de {ano_sel}?**"
                )
                st.caption("ℹ *Este quesito permite marcação múltipla. Os pontos são somados até o limite máximo de 6,0 pontos. Clique em 'Salvar Quesito 4.0' para registrar.*")

                # Estado inicial / persistente
                d40 = res_data.get("4.0") or {
                    "valor": "[]",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                
                # Deserialização segura do estado das opções marcadas
                val_raw_40 = d40.get("valor", "[]")
                try:
                    opcoes_salvas_40 = json.loads(val_raw_40) if isinstance(val_raw_40, str) and val_raw_40.startswith("[") else []
                except Exception:
                    opcoes_salvas_40 = []

                evidencia_40_salva = d40.get("link", "")
                chave_link_40 = f"l_40_txt_{ano_sel}"

                c40_1, c40_2 = st.columns([1, 1])
                with c40_1:
                    st.markdown("**Marque todas as opções que se aplicam:**")

                    chk_escola = st.checkbox("Para escolas (+2.5 pts)", value="escola" in opcoes_salvas_40, key=f"chk_4_0_esc_{ano_sel}")
                    chk_sec = st.checkbox("Para outras secretarias / entidades municipais (+1.0 pt)", value="secretarias" in opcoes_salvas_40, key=f"chk_4_0_sec_{ano_sel}")
                    chk_cons = st.checkbox("Para membros do Conselho Municipal de Saúde (+1.0 pt)", value="conselho" in opcoes_salvas_40, key=f"chk_4_0_con_{ano_sel}")
                    chk_mun = st.checkbox("Para munícipes ou empresas (+1.5 pts)", value="municipes" in opcoes_salvas_40, key=f"chk_4_0_mun_{ano_sel}")
                    chk_nao = st.checkbox("Não ofereceu nenhum curso/treinamento no ano (0.0 pts)", value="nenhum" in opcoes_salvas_40, key=f"chk_4_0_nao_{ano_sel}")

                with c40_2:
                    link_40 = st.text_area(
                        "Link/Evidência (Listas de presença, certificados, portarias ou relatórios de capacitação):",
                        value=evidencia_40_salva,
                        key=chave_link_40,
                        placeholder="Insira o link oficial referente ao quesito 4.0...",
                        height=160,
                    )
                    placeholder_links_40 = st.empty()
                    links_40_visuais = re.findall(REGEX_PURE_URL, link_40 or "")
                    if links_40_visuais:
                        placeholder_links_40.markdown(
                            "**🔗 Link ativo:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_40_visuais]
                            )
                        )

                # Renderização do chat de comentários
                bloco_comentarios_isaude("4.0", res_data)

                # Botão de salvamento
                if st.button("💾 Salvar Quesito 4.0", key=f"btn_salvar_4_0_{ano_sel}", type="primary"):
                    # Processamento lógico da escolha múltipla
                    opcoes_finais_40 = []
                    pts_calculados_40 = 0.0

                    if chk_nao and not any([chk_escola, chk_sec, chk_cons, chk_mun]):
                        opcoes_finais_40 = ["nenhum"]
                        pts_calculados_40 = 0.0
                    else:
                        if chk_escola:
                            opcoes_finais_40.append("escola")
                            pts_calculados_40 += 2.5
                        if chk_sec:
                            opcoes_finais_40.append("secretarias")
                            pts_calculados_40 += 1.0
                        if chk_cons:
                            opcoes_finais_40.append("conselho")
                            pts_calculados_40 += 1.0
                        if chk_mun:
                            opcoes_finais_40.append("municipes")
                            pts_calculados_40 += 1.5

                    pts_calculados_40 = min(pts_calculados_40, 6.0)
                    str_opcoes_40 = json.dumps(opcoes_finais_40)
                    lnk_val = link_40.strip()

                    comentarios_historico = d40.get("comentarios", [])

                    save_resp_isaude(
                        qid="4.0",
                        valor=str_opcoes_40,
                        pontos=pts_calculados_40,
                        link=lnk_val,
                        comentarios=comentarios_historico
                    )

                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_40_salva or "")]

                    if lnk_val != evidencia_40_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_4_0_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_4_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 4.0 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                pts_atuais_40 = d40.get("pontos", 0.0)
                cor_txt_40 = "#28a745" if pts_atuais_40 > 0.0 else "#6c757d"

                st.markdown(
                    f"<span style='color:{cor_txt_40}; font-weight:bold;'>"
                    f"📊 Impacto de Pontuação no Quesito 4.0: +{pts_atuais_40:.1f} pontos</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 4.0 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_4_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("4.0", st.session_state.get(f"links_pendentes_4_0_{ano_sel}", []), ano_sel)

        # =============================================================================
        # QUESITO 5.0 • MOVIMENTAÇÃO FINANCEIRA DO SUS EM CONTAS PRÓPRIAS
        # =============================================================================
        with st.container(key=f"container_bloco_isaude_5_0_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 5.0 - Contas Bancárias Próprias do SUS em {ano_sel}", expanded=True):
                st.subheader(f"5.0 • Movimentação Financeira do SUS ({ano_sel})")
                st.write(
                    "**Os recursos financeiros municipais (fonte 1) destinados ao Sistema Único de Saúde (SUS) são movimentados em contas bancárias próprias?**"
                )
                st.caption("ℹ *Preencha os campos abaixo e clique no botão 'Salvar Quesito 5.0' para registrar.*")

                # Mapeamento de Opções com pontuação ao lado e valores numéricos
                opcoes_50 = {
                    "Selecione...": 0.0,
                    "Sim – 04": 4.0,
                    "Não – 00": 0.0,
                }

                # Estado inicial / persistente
                d50 = res_data.get("5.0") or {
                    "valor": "Selecione...",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_50 = d50.get("valor", "Selecione...")
                evidencia_50_salva = d50.get("link", "")

                # Compatibilidade com gravações antigas que usavam apenas "Sim" ou "Não"
                if v_salvo_50 == "Sim":
                    v_salvo_50 = "Sim – 04"
                elif v_salvo_50 == "Não":
                    v_salvo_50 = "Não – 00"

                # Chaves fixas por componente e ano
                chave_radio_50 = f"r_50_{ano_sel}"
                chave_link_50 = f"l_50_txt_{ano_sel}"

                c50_1, c50_2 = st.columns([1, 1])
                with c50_1:
                    lista_opcoes_50 = list(opcoes_50.keys())
                    idx_50 = lista_opcoes_50.index(v_salvo_50) if v_salvo_50 in lista_opcoes_50 else 0

                    val_radio_50 = st.radio(
                        "Selecione a alternativa correspondente:",
                        options=lista_opcoes_50,
                        index=idx_50,
                        key=chave_radio_50,
                    )

                with c50_2:
                    link_50 = st.text_area(
                        "Link/Evidência (Extratos bancários das contas específicas do Fundo Municipal de Saúde, relatório do SIOPS ou demonstrativo de movimentação financeira por fonte):",
                        value=evidencia_50_salva,
                        key=chave_link_50,
                        placeholder="Insira o link oficial referente ao quesito 5.0...",
                        height=100,
                    )
                    placeholder_links_50 = st.empty()
                    links_50_visuais = re.findall(REGEX_PURE_URL, link_50 or "")
                    if links_50_visuais:
                        placeholder_links_50.markdown(
                            "**🔗 Link ativo:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_50_visuais]
                            )
                        )

                # Renderização do chat de comentários
                bloco_comentarios_isaude("5.0", res_data)

                # Botão de salvamento
                if st.button("💾 Salvar Quesito 5.0", key=f"btn_salvar_5_0_{ano_sel}", type="primary"):
                    val_salvar = st.session_state.get(chave_radio_50, v_salvo_50)
                    pts_50 = float(opcoes_50.get(val_salvar, 0.0))
                    lnk_val = link_50.strip()

                    comentarios_historico = d50.get("comentarios", [])

                    save_resp_isaude(
                        qid="5.0",
                        valor=val_salvar,
                        pontos=pts_50,
                        link=lnk_val,
                        comentarios=comentarios_historico
                    )

                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_50_salva or "")]

                    if lnk_val != evidencia_50_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_5_0_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_5_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 5.0 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                pts_atuais_50 = d50.get("pontos", 0.0)
                cor_txt_50 = "#28a745" if pts_atuais_50 > 0.0 else "#6c757d"

                st.markdown(
                    f"<span style='color:{cor_txt_50}; font-weight:bold;'>"
                    f"📊 Impacto de Pontuação no Quesito 5.0: +{pts_atuais_50:.1f} pontos</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 5.0 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_5_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("5.0", st.session_state.get(f"links_pendentes_5_0_{ano_sel}", []), ano_sel)

        # =============================================================================
        # QUESITO 5.1 • INFORMAÇÕES DA CONTA BANCÁRIA PRÓPRIA (INFORMATIVO)
        # =============================================================================
        with st.container(key=f"container_bloco_isaude_5_1_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 5.1 - Informações da Conta Bancária Própria em {ano_sel}", expanded=True):
                st.subheader(f"5.1 • Informações da Conta Bancária Própria ({ano_sel})")
                st.write(f"**Informe o Banco, Agência e nº da conta em {ano_sel}:**")
                st.caption("ℹ *Preencha os campos abaixo e clique no botão 'Salvar Quesito 5.1' para registrar.*")

                # Estado inicial / persistente
                d51 = res_data.get("5.1") or {
                    "valor": "",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_51 = d51.get("valor", "")
                evidencia_51_salva = d51.get("link", "")

                # Chaves fixas por componente e ano
                chave_input_51 = f"txt_saude_5_1_dados_{ano_sel}"
                chave_link_51 = f"l_51_txt_{ano_sel}"

                c51_1, c51_2 = st.columns([1, 1])
                with c51_1:
                    input_5_1 = st.text_input(
                        "Dados Bancários:",
                        value=v_salvo_51,
                        placeholder="Ex: Banco do Brasil, Ag: 1234-5, C/C: 98765-4",
                        key=chave_input_51,
                    )

                with c51_2:
                    link_51 = st.text_area(
                        "Link/Evidência (opcional):",
                        value=evidencia_51_salva,
                        key=chave_link_51,
                        placeholder="Insira o link oficial referente ao quesito 5.1...",
                        height=100,
                    )
                    placeholder_links_51 = st.empty()
                    links_51_visuais = re.findall(REGEX_PURE_URL, link_51 or "")
                    if links_51_visuais:
                        placeholder_links_51.markdown(
                            "**🔗 Link ativo:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_51_visuais]
                            )
                        )

                # Renderização do chat de comentários
                bloco_comentarios_isaude("5.1", res_data)

                # Botão de salvamento
                if st.button("💾 Salvar Quesito 5.1", key=f"btn_salvar_5_1_{ano_sel}", type="primary"):
                    val_salvar_51 = st.session_state.get(chave_input_51, input_5_1).strip()
                    lnk_val = link_51.strip()
                    comentarios_historico_51 = d51.get("comentarios", [])

                    save_resp_isaude(
                        qid="5.1",
                        valor=val_salvar_51,
                        pontos=0.0,
                        link=lnk_val,
                        comentarios=comentarios_historico_51
                    )

                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_51_salva or "")]

                    if lnk_val != evidencia_51_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_5_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_5_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Informações do Quesito 5.1 salvas com sucesso!", icon="✅")
                    st.rerun()

                # Exibição de pontuação fixa informativa
                st.markdown(
                    "<span style='color:#6c757d; font-weight:bold;'>"
                    "📊 Impacto de Pontuação no Quesito 5.1: 0.0 pontos (Quesito Informativo)</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 5.1 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_5_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("5.1", st.session_state.get(f"links_pendentes_5_1_{ano_sel}", []), ano_sel)

        # =============================================================================
        # QUESITO 6.0 • RESPONSABILIDADE E GESTÃO DO FUNDO MUNICIPAL DE SAÚDE
        # =============================================================================
        with st.container(key=f"container_bloco_isaude_6_0_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 6.0 - Gestão do Fundo de Saúde em {ano_sel}", expanded=True):
                st.subheader(f"6.0 • Gestão do Fundo de Saúde ({ano_sel})")
                st.write(
                    f"**As despesas consideradas, para fins de apuração do mínimo constitucional de aplicação de recursos próprios em saúde, foram de responsabilidade específica do setor de saúde e com recursos municipais movimentados somente pelo Fundo Municipal de Saúde em {ano_sel}?**"
                )
                st.caption("ℹ *Preencha os campos abaixo e clique no botão 'Salvar Quesito 6.0' para registrar.*")

                # Mapeamento de Opções e Pontuações do Quesito 6.0
                opcoes_60 = {
                    "Selecione...": 0.0,
                    "Sim, com responsabilidade específica do setor de saúde e com recursos movimentados exclusivamente pelo Fundo – 05": 5.0,
                    "Sim, com responsabilidade específica do setor de saúde, mas não houve movimentação de recursos exclusivamente pelo Fundo – 03": 3.0,
                    "Sim, com recursos movimentados exclusivamente pelo Fundo, mas sem responsabilidade específica do setor de saúde – 01": 1.0,
                    "Não – 00": 0.0,
                }

                # Estado inicial / persistente
                d60 = res_data.get("6.0") or {
                    "valor": "Selecione...",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_60 = d60.get("valor", "Selecione...")
                evidencia_60_salva = d60.get("link", "")

                # Chaves fixas por componente e ano
                chave_radio_60 = f"r_60_{ano_sel}"
                chave_link_60 = f"l_60_txt_{ano_sel}"

                c60_1, c60_2 = st.columns([1, 1])
                with c60_1:
                    lista_opcoes_60 = list(opcoes_60.keys())
                    idx_60 = lista_opcoes_60.index(v_salvo_60) if v_salvo_60 in lista_opcoes_60 else 0

                    val_radio_60 = st.radio(
                        "Selecione a alternativa correspondente:",
                        options=lista_opcoes_60,
                        index=idx_60,
                        key=chave_radio_60,
                    )

                with c60_2:
                    link_60 = st.text_area(
                        "Link/Evidência (Relatório do SIOPS, leis orçamentárias ou decretos de delegação de competência da gestão do fundo):",
                        value=evidencia_60_salva,
                        key=chave_link_60,
                        placeholder="Insira o link oficial referente ao quesito 6.0...",
                        height=140,
                    )
                    placeholder_links_60 = st.empty()
                    links_60_visuais = re.findall(REGEX_PURE_URL, link_60 or "")
                    if links_60_visuais:
                        placeholder_links_60.markdown(
                            "**🔗 Link ativo:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_60_visuais]
                            )
                        )

                # Renderização do chat de comentários
                bloco_comentarios_isaude("6.0", res_data)

                # Botão de salvamento
                if st.button("💾 Salvar Quesito 6.0", key=f"btn_salvar_6_0_{ano_sel}", type="primary"):
                    val_salvar = st.session_state.get(chave_radio_60, v_salvo_60)
                    pts_60 = float(opcoes_60.get(val_salvar, 0.0))
                    lnk_val = link_60.strip()

                    comentarios_historico = d60.get("comentarios", [])

                    save_resp_isaude(
                        qid="6.0",
                        valor=val_salvar,
                        pontos=pts_60,
                        link=lnk_val,
                        comentarios=comentarios_historico
                    )

                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_60_salva or "")]

                    if lnk_val != evidencia_60_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_6_0_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_6_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 6.0 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                pts_atuais_60 = d60.get("pontos", 0.0)
                cor_txt_60 = "#28a745" if pts_atuais_60 > 0.0 else "#6c757d"

                st.markdown(
                    f"<span style='color:{cor_txt_60}; font-weight:bold;'>"
                    f"📊 Impacto de Pontuação no Quesito 6.0: +{pts_atuais_60:.1f} pontos</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 6.0 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_6_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("6.0", st.session_state.get(f"links_pendentes_6_0_{ano_sel}", []), ano_sel)

        # =============================================================================
        # QUESITO 7.0 • RELATÓRIOS QUADRIMESTRAIS (MÚLTIPLA ESCOLHA)
        # =============================================================================
        with st.container(key=f"container_bloco_isaude_7_0_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 7.0 - Relatórios Quadrimestrais de {ano_sel} (LC 141/2012)", expanded=True):
                st.subheader(f"7.0 • Relatórios Quadrimestrais em {ano_sel}")
                st.write(
                    f"**O gestor municipal de saúde apresentou quais Relatórios Quadrimestrais de {ano_sel} previstos no art. 36 da Lei Complementar 141/2012 em audiência pública na Câmara Municipal?**"
                )
                st.caption("ℹ *Este quesito permite uma ou mais marcações. Seleções negativas impactam o somatório total. Clique em 'Salvar Quesito 7.0' para registrar.*")

                # Estado inicial / persistente
                d70 = res_data.get("7.0") or {
                    "valor": "[]",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }

                # Deserialização segura do estado das opções marcadas
                val_raw_70 = d70.get("valor", "[]")
                try:
                    opcoes_salvas_70 = json.loads(val_raw_70) if isinstance(val_raw_70, str) and val_raw_70.startswith("[") else []
                except Exception:
                    opcoes_salvas_70 = []

                evidencia_70_salva = d70.get("link", "")
                chave_link_70 = f"l_70_txt_{ano_sel}"

                c70_1, c70_2 = st.columns([1, 1])
                with c70_1:
                    st.markdown("**Marque todas as opções que se aplicam:**")

                    chk_q1 = st.checkbox(f"Relatório do 1º Quadrimestre - até o final do mês de maio de {ano_sel} (+1.0 pt)", value="q1" in opcoes_salvas_70, key=f"chk_7_0_q1_{ano_sel}")
                    chk_q2 = st.checkbox(f"Relatório do 2º Quadrimestre - até o final do mês de setembro de {ano_sel} (+1.0 pt)", value="q2" in opcoes_salvas_70, key=f"chk_7_0_q2_{ano_sel}")
                    chk_q3 = st.checkbox(f"Relatório do 3º Quadrimestre - até o final do mês de fevereiro do ano seguinte (+1.0 pt)", value="q3" in opcoes_salvas_70, key=f"chk_7_0_q3_{ano_sel}")
                    chk_nenhum_prazo = st.checkbox("Não apresentou nenhum relatório quadrimestral dentro do prazo (0.0 pts)", value="nenhum_prazo" in opcoes_salvas_70, key=f"chk_7_0_np_{ano_sel}")
                    chk_nenhum_aud = st.checkbox("Não apresentou nenhum relatório quadrimestral em audiência pública na Câmara Municipal (-1.0 pt)", value="nenhum_aud" in opcoes_salvas_70, key=f"chk_7_0_na_{ano_sel}")

                with c70_2:
                    link_70 = st.text_area(
                        "Link/Evidência (Atas das audiências públicas ou editais de convocação):",
                        value=evidencia_70_salva,
                        key=chave_link_70,
                        placeholder="Insira o link oficial referente ao quesito 7.0...",
                        height=180,
                    )
                    placeholder_links_70 = st.empty()
                    links_70_visuais = re.findall(REGEX_PURE_URL, link_70 or "")
                    if links_70_visuais:
                        placeholder_links_70.markdown(
                            "**🔗 Link ativo:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_70_visuais]
                            )
                        )

                # Renderização do chat de comentários
                bloco_comentarios_isaude("7.0", res_data)

                # Botão de salvamento
                if st.button("💾 Salvar Quesito 7.0", key=f"btn_salvar_7_0_{ano_sel}", type="primary"):
                    # Processamento lógico das regras de pontuação
                    opcoes_finais_70 = []
                    pts_calculados_70 = 0.0

                    if chk_nenhum_aud:
                        opcoes_finais_70 = ["nenhum_aud"]
                        pts_calculados_70 = -1.0
                    elif chk_nenhum_prazo:
                        opcoes_finais_70 = ["nenhum_prazo"]
                        pts_calculados_70 = 0.0
                    else:
                        if chk_q1:
                            opcoes_finais_70.append("q1")
                            pts_calculados_70 += 1.0
                        if chk_q2:
                            opcoes_finais_70.append("q2")
                            pts_calculados_70 += 1.0
                        if chk_q3:
                            opcoes_finais_70.append("q3")
                            pts_calculados_70 += 1.0

                    str_opcoes_70 = json.dumps(opcoes_finais_70)
                    lnk_val = link_70.strip()

                    comentarios_historico = d70.get("comentarios", [])

                    save_resp_isaude(
                        qid="7.0",
                        valor=str_opcoes_70,
                        pontos=pts_calculados_70,
                        link=lnk_val,
                        comentarios=comentarios_historico
                    )

                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_70_salva or "")]

                    if lnk_val != evidencia_70_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_7_0_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_7_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 7.0 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                pts_atuais_70 = d70.get("pontos", 0.0)
                if pts_atuais_70 > 0.0:
                    cor_txt_70 = "#28a745"
                elif pts_atuais_70 < 0.0:
                    cor_txt_70 = "#dc3545"
                else:
                    cor_txt_70 = "#6c757d"

                st.markdown(
                    f"<span style='color:{cor_txt_70}; font-weight:bold;'>"
                    f"📊 Impacto de Pontuação no Quesito 7.0: {pts_atuais_70:+.1f} pontos</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 7.0 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_7_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("7.0", st.session_state.get(f"links_pendentes_7_0_{ano_sel}", []), ano_sel)

        # =============================================================================
        # QUESITO 8.0 • RELATÓRIO ANUAL DE GESTÃO (RAG)
        # =============================================================================
        with st.container(key=f"container_bloco_isaude_8_0_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 8.0 - Relatório Anual de Gestão (RAG) de {ano_sel}", expanded=True):
                st.subheader(f"8.0 • Encaminhamento do RAG de {ano_sel}")
                st.write(
                    f"**O Relatório Anual de Gestão de {ano_sel} foi encaminhado ao Conselho Municipal de Saúde até 30/03/{ano_sel + 1} (ano seguinte ao da execução financeira)?**"
                )
                st.caption("ℹ *Preencha os campos abaixo e clique no botão 'Salvar Quesito 8.0' para registrar.*")

                # Mapeamento de Opções e Pontuações do Quesito 8.0
                opcoes_80 = {
                    "Selecione...": 0.0,
                    "Sim, meio eletrônico – 02": 2.0,
                    "Sim, meio físico – 02": 2.0,
                    "Não – 00": 0.0,
                }

                # Estado inicial / persistente
                d80 = res_data.get("8.0") or {
                    "valor": "Selecione...",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_80 = d80.get("valor", "Selecione...")
                evidencia_80_salva = d80.get("link", "")

                # Chaves fixas por componente e ano
                chave_radio_80 = f"r_80_{ano_sel}"
                chave_link_80 = f"l_80_txt_{ano_sel}"

                c80_1, c80_2 = st.columns([1, 1])
                with c80_1:
                    lista_opcoes_80 = list(opcoes_80.keys())
                    idx_80 = lista_opcoes_80.index(v_salvo_80) if v_salvo_80 in lista_opcoes_80 else 0

                    val_radio_80 = st.radio(
                        "Selecione a alternativa correspondente:",
                        options=lista_opcoes_80,
                        index=idx_80,
                        key=chave_radio_80,
                    )

                with c80_2:
                    link_80 = st.text_area(
                        "Link/Evidência (Ofício de encaminhamento protocolado no CMS ou comprovante do DigiSUS):",
                        value=evidencia_80_salva,
                        key=chave_link_80,
                        placeholder="Insira o link oficial referente ao quesito 8.0...",
                        height=110,
                    )
                    placeholder_links_80 = st.empty()
                    links_80_visuais = re.findall(REGEX_PURE_URL, link_80 or "")
                    if links_80_visuais:
                        placeholder_links_80.markdown(
                            "**🔗 Link ativo:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_80_visuais]
                            )
                        )

                # Renderização do chat de comentários
                bloco_comentarios_isaude("8.0", res_data)

                # Botão de salvamento
                if st.button("💾 Salvar Quesito 8.0", key=f"btn_salvar_8_0_{ano_sel}", type="primary"):
                    val_salvar = st.session_state.get(chave_radio_80, v_salvo_80)
                    pts_80 = float(opcoes_80.get(val_salvar, 0.0))
                    lnk_val = link_80.strip()

                    comentarios_historico = d80.get("comentarios", [])

                    save_resp_isaude(
                        qid="8.0",
                        valor=val_salvar,
                        pontos=pts_80,
                        link=lnk_val,
                        comentarios=comentarios_historico
                    )

                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_80_salva or "")]

                    if lnk_val != evidencia_80_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_8_0_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_8_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 8.0 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                pts_atuais_80 = d80.get("pontos", 0.0)
                cor_txt_80 = "#28a745" if pts_atuais_80 > 0.0 else "#6c757d"

                st.markdown(
                    f"<span style='color:{cor_txt_80}; font-weight:bold;'>"
                    f"📊 Impacto de Pontuação no Quesito 8.0: +{pts_atuais_80:.1f} pontos</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 8.0 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_8_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("8.0", st.session_state.get(f"links_pendentes_8_0_{ano_sel}", []), ano_sel)

        # =============================================================================
        # QUESITO 9.0 • PARECER CONCLUSIVO DO RAG
        # =============================================================================
        with st.container(key=f"container_bloco_isaude_9_0_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 9.0 - Parecer Conclusivo sobre o RAG de {ano_sel}", expanded=True):
                st.subheader(f"9.0 • Status do Parecer do RAG ({ano_sel})")
                st.write(
                    f"**O Parecer Conclusivo sobre o Relatório Anual de Gestão de {ano_sel} foi 'aprovado sem ressalvas', 'aprovado com ressalvas' ou 'irregular/não aprovado'?**"
                )
                st.caption("ℹ *Preencha os campos abaixo e clique no botão 'Salvar Quesito 9.0' para registrar.*")

                # Mapeamento de Opções e Pontuações do Quesito 9.0
                opcoes_90 = {
                    "Selecione...": 0.0,
                    "Aprovado sem ressalvas – 18": 18.0,
                    "Aprovado com ressalvas – 10": 10.0,
                    "Irregular/Não aprovado – 00": 0.0,
                    "Não apreciado – -10": -10.0,
                }

                # Estado inicial / persistente
                d90 = res_data.get("9.0") or {
                    "valor": "Selecione...",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_90 = d90.get("valor", "Selecione...")
                evidencia_90_salva = d90.get("link", "")

                # Chaves fixas por componente e ano
                chave_radio_90 = f"r_90_{ano_sel}"
                chave_link_90 = f"l_90_txt_{ano_sel}"

                c90_1, c90_2 = st.columns([1, 1])
                with c90_1:
                    lista_opcoes_90 = list(opcoes_90.keys())
                    idx_90 = lista_opcoes_90.index(v_salvo_90) if v_salvo_90 in lista_opcoes_90 else 0

                    val_radio_90 = st.radio(
                        "Selecione a alternativa correspondente:",
                        options=lista_opcoes_90,
                        index=idx_90,
                        key=chave_radio_90,
                    )

                with c90_2:
                    link_90 = st.text_area(
                        "Link/Evidência (Resolução do CMS contendo o Parecer Conclusivo homologado):",
                        value=evidencia_90_salva,
                        key=chave_link_90,
                        placeholder="Insira o link oficial referente ao quesito 9.0...",
                        height=140,
                    )
                    placeholder_links_90 = st.empty()
                    links_90_visuais = re.findall(REGEX_PURE_URL, link_90 or "")
                    if links_90_visuais:
                        placeholder_links_90.markdown(
                            "**🔗 Link ativo:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_90_visuais]
                            )
                        )

                # Renderização do chat de comentários
                bloco_comentarios_isaude("9.0", res_data)

                # Botão de salvamento
                if st.button("💾 Salvar Quesito 9.0", key=f"btn_salvar_9_0_{ano_sel}", type="primary"):
                    val_salvar = st.session_state.get(chave_radio_90, v_salvo_90)
                    pts_90 = float(opcoes_90.get(val_salvar, 0.0))
                    lnk_val = link_90.strip()

                    comentarios_historico = d90.get("comentarios", [])

                    save_resp_isaude(
                        qid="9.0",
                        valor=val_salvar,
                        pontos=pts_90,
                        link=lnk_val,
                        comentarios=comentarios_historico
                    )

                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_90_salva or "")]

                    if lnk_val != evidencia_90_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_9_0_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_9_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 9.0 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                pts_atuais_90 = d90.get("pontos", 0.0)
                if pts_atuais_90 > 0.0:
                    cor_txt_90 = "#28a745"
                elif pts_atuais_90 < 0.0:
                    cor_txt_90 = "#dc3545"
                else:
                    cor_txt_90 = "#6c757d"

                st.markdown(
                    f"<span style='color:{cor_txt_90}; font-weight:bold;'>"
                    f"📊 Impacto de Pontuação no Quesito 9.0: {pts_atuais_90:+.1f} pontos</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 9.0 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_9_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("9.0", st.session_state.get(f"links_pendentes_9_0_{ano_sel}", []), ano_sel)

        # =============================================================================
        # QUESITO 9.1 • FORMA E DATA DA PUBLICAÇÃO
        # =============================================================================
        with st.container(key=f"container_bloco_isaude_9_1_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 9.1 - Forma e Data da Publicação (RAG {ano_sel})", expanded=True):
                st.subheader(f"9.1 • Dados da Publicação ({ano_sel})")
                st.write(
                    f"**Informe a forma e Data da publicação do Parecer Conclusivo sobre o Relatório Anual de Gestão de {ano_sel}:**"
                )
                st.caption("ℹ *Preencha a informação abaixo e clique no botão 'Salvar Quesito 9.1' para registrar.*")

                # Estado inicial / persistente
                d91 = res_data.get("9.1") or {
                    "valor": "",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_91 = d91.get("valor", "")

                # Chave fixa por componente e ano
                chave_txt_91 = f"t_91_txt_{ano_sel}"

                val_input_91 = st.text_input(
                    "Forma e Data da Publicação:",
                    value=v_salvo_91,
                    key=chave_txt_91,
                    placeholder=f"Ex: Diário Oficial do Município, em 15/04/{ano_sel + 1}",
                )

                # Renderização do chat de comentários
                bloco_comentarios_isaude("9.1", res_data)

                # Botão de salvamento
                if st.button("💾 Salvar Quesito 9.1", key=f"btn_salvar_9_1_{ano_sel}", type="primary"):
                    texto_salvar_91 = val_input_91.strip()
                    comentarios_historico = d91.get("comentarios", [])

                    save_resp_isaude(
                        qid="9.1",
                        valor=texto_salvar_91,
                        pontos=0.0,
                        link="",
                        comentarios=comentarios_historico
                    )

                    st.cache_data.clear()
                    st.toast("Informações do Quesito 9.1 salvas com sucesso!", icon="✅")
                    st.rerun()

                st.markdown(
                    "<span style='color:#6c757d; font-weight:bold;'>"
                    "📊 Impacto de Pontuação no Quesito 9.1: 0.0 pontos (Quesito Informativo)</span>",
                    unsafe_allow_html=True,
                )

        # =============================================================================
        # QUESITO 9.2 • LINK PARA O PARECER CONCLUSIVO
        # =============================================================================
        with st.container(key=f"container_bloco_isaude_9_2_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 9.2 - Link de Divulgação do Parecer Conclusivo (RAG {ano_sel})", expanded=True):
                st.subheader(f"9.2 • Divulgação Eletrônica ({ano_sel})")
                st.write(
                    f"**Informe a página eletrônica (link na internet) de divulgação do Parecer Conclusivo sobre o Relatório Anual de Gestão de {ano_sel}:**"
                )
                st.caption("⚠️ *Se não estiver disponível na internet, insira exatamente o texto **XYZ**.*")

                # Estado inicial / persistente
                d92 = res_data.get("9.2") or {
                    "valor": "",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_92 = d92.get("valor", "")

                # Chave fixa por componente e ano
                chave_txt_92 = f"t_92_txt_{ano_sel}"

                val_input_92 = st.text_input(
                    "Link Eletrônico de Divulgação:",
                    value=v_salvo_92,
                    key=chave_txt_92,
                    placeholder="Insira o link completo ou XYZ...",
                )

                placeholder_links_92 = st.empty()
                links_92_visuais = re.findall(REGEX_PURE_URL, val_input_92 or "")
                if links_92_visuais:
                    placeholder_links_92.markdown(
                        "**🔗 Link ativo:** "
                        + " | ".join(
                            [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_92_visuais]
                        )
                    )

                # Renderização do chat de comentários
                bloco_comentarios_isaude("9.2", res_data)

                # Botão de salvamento
                if st.button("💾 Salvar Quesito 9.2", key=f"btn_salvar_9_2_{ano_sel}", type="primary"):
                    texto_salvar_92 = val_input_92.strip()
                    val_limpo = texto_salvar_92.upper()

                    # Regra de cálculo automatizada
                    pts_92 = 0.0 if val_limpo in ["XYZ", ""] else 5.0
                    comentarios_historico = d92.get("comentarios", [])

                    save_resp_isaude(
                        qid="9.2",
                        valor=texto_salvar_92,
                        pontos=pts_92,
                        link="",
                        comentarios=comentarios_historico
                    )

                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, texto_salvar_92 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, v_salvo_92 or "")]

                    if texto_salvar_92 != v_salvo_92 and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_9_2_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_9_2_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 9.2 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                pts_atuais_92 = d92.get("pontos", 0.0)
                cor_txt_92 = "#28a745" if pts_atuais_92 > 0.0 else "#6c757d"

                st.markdown(
                    f"<span style='color:{cor_txt_92}; font-weight:bold;'>"
                    f"📊 Impacto de Pontuação no Quesito 9.2: +{pts_atuais_92:.1f} pontos</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 9.2 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_9_2_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("9.2", st.session_state.get(f"links_pendentes_9_2_{ano_sel}", []), ano_sel)

        # =============================================================================
        # QUESITO 10.0 • INDICADORES DE INFRAESTRUTURA DOS ESTABELECIMENTOS DE SAÚDE
        # =============================================================================
        with st.container(key=f"container_bloco_isaude_10_0_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 10.0 - Indicadores de Infraestrutura e Funcionamento (RAG {ano_sel})", expanded=True):
                st.subheader(f"10.0 • Infraestrutura sob Gestão Municipal ({ano_sel})")
                st.write(
                    f"**Sobre os estabelecimentos de saúde sob gestão municipal, em dezembro de {ano_sel}, informe os dados de infraestrutura e funcionamento:**"
                )
                st.caption("ℹ️ *Preencha os campos numéricos, insira as evidências se houver e clique no botão 'Salvar Quesito 10.0' para registrar.*")

                # 1. Recuperação dos dados do estado local
                d10_total_est = res_data.get("10.0_total_est") or {"valor": "0", "pontos": 0.0, "link": "", "comentarios": []}
                d10_com_avcb  = res_data.get("10.0_com_avcb")  or {"valor": "0", "pontos": 0.0, "link": "", "comentarios": []}
                d10_com_visa  = res_data.get("10.0_com_visa")  or {"valor": "0", "pontos": 0.0, "link": "", "comentarios": []}
                d10_reparos   = res_data.get("10.0_reparos")   or {"valor": "0", "pontos": 0.0, "link": "", "comentarios": []}
                d10_interromp = res_data.get("10.0_interromp") or {"valor": "0", "pontos": 0.0, "link": "", "comentarios": []}
                d10_mestre    = res_data.get("10.0")           or {"valor": "",  "pontos": 0.0, "link": "", "comentarios": []}

                val_total_salvo = int(d10_total_est.get("valor", "0") if str(d10_total_est.get("valor", "0")).isdigit() else "0")
                max_limite = max(val_total_salvo, 1) if val_total_salvo > 0 else None

                c23, c24 = st.columns([1, 1])

                with c23:
                    st.markdown("**Dados do Cadastro Geral:**")
                    val_total_est = st.number_input(
                        "Estabelecimentos de saúde sob gestão municipal:",
                        min_value=0,
                        step=1,
                        value=val_total_salvo,
                        key=f"num_10_tot_{ano_sel}"
                    )

                    st.markdown("---")
                    st.markdown("**Dados de Certificações e Condições:**")

                    v_avcb = int(d10_com_avcb.get("valor", "0") if str(d10_com_avcb.get("valor", "0")).isdigit() else "0")
                    v_visa = int(d10_com_visa.get("valor", "0") if str(d10_com_visa.get("valor", "0")).isdigit() else "0")
                    v_rep  = int(d10_reparos.get("valor", "0") if str(d10_reparos.get("valor", "0")).isdigit() else "0")
                    v_int  = int(d10_interromp.get("valor", "0") if str(d10_interromp.get("valor", "0")).isdigit() else "0")

                    val_com_avcb  = st.number_input("Quantidade com AVCB:", min_value=0, max_value=max_limite, step=1, value=v_avcb, key=f"num_10_avcb_{ano_sel}")
                    val_com_visa  = st.number_input("Quantidade com licença da vigilância sanitária:", min_value=0, max_value=max_limite, step=1, value=v_visa, key=f"num_10_visa_{ano_sel}")
                    val_reparos   = st.number_input("Quantidade que necessitavam de reparos:", min_value=0, max_value=max_limite, step=1, value=v_rep, key=f"num_10_rep_{ano_sel}")
                    val_interromp = st.number_input("Quantidade com funcionamento interrompido no ano:", min_value=0, max_value=max_limite, step=1, value=v_int, key=f"num_10_int_{ano_sel}")

                # Cálculo dinâmico para exibição visual
                pts_avcb = (val_com_avcb / val_total_est) * 50.0 if val_total_est > 0 else 0.0
                pts_visa = (val_com_visa / val_total_est) * 25.0 if val_total_est > 0 else 0.0
                pts_reparos = (1.0 - (val_reparos / val_total_est)) * 25.0 if val_total_est > 0 else 0.0
                pts_interromp = (val_interromp / val_total_est) * -50.0 if val_total_est > 0 else 0.0
                pts_final_10 = pts_avcb + pts_visa + pts_reparos + pts_interromp

                with c24:
                    val_input_10_link = st.text_area(
                        "Link/Evidência (Relação CNES, laudos do Corpo de Bombeiros, certidões da VISA e relatórios de engenharia):",
                        value=d10_mestre.get("link", ""),
                        key=f"txt_saude_10_0_{ano_sel}",
                        height=220
                    )

                    placeholder_links_10 = st.empty()
                    links_10_visuais = re.findall(REGEX_PURE_URL, val_input_10_link or "")
                    if links_10_visuais:
                        placeholder_links_10.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_10_visuais]
                            )
                        )

                    st.markdown('<div style="background-color: #f7f9fa; padding: 12px; border-radius: 6px; border: 1px solid #e1e4e6;">', unsafe_allow_html=True)
                    st.markdown("**🧮 Extrato Estatístico Estimado:**")
                    st.markdown(f"• Nota Parcial AVCB: `{pts_avcb:.2f} / 50.0 pts`")
                    st.markdown(f"• Nota Parcial Vig. Sanitária: `{pts_visa:.2f} / 25.0 pts`")
                    st.markdown(f"• Nota Parcial Reparos: `{pts_reparos:.2f} / 25.0 pts`")
                    st.markdown(f"• Penalidade Interrupções: `{pts_interromp:.2f} pts`")
                    st.markdown('</div>', unsafe_allow_html=True)

                # Renderização do chat de comentários no quesito mestre
                bloco_comentarios_isaude("10.0", res_data)

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 10.0", key=f"btn_salvar_10_0_{ano_sel}", type="primary"):
                    t_est = val_total_est
                    c_avcb = val_com_avcb
                    c_visa = val_com_visa
                    c_rep = val_reparos
                    c_int = val_interromp
                    lk_10 = val_input_10_link.strip()

                    p_avcb_s = (c_avcb / t_est) * 50.0 if t_est > 0 else 0.0
                    p_visa_s = (c_visa / t_est) * 25.0 if t_est > 0 else 0.0
                    p_rep_s = (1.0 - (c_rep / t_est)) * 25.0 if t_est > 0 else 0.0
                    p_int_s = (c_int / t_est) * -50.0 if t_est > 0 else 0.0
                    p_tot_s = p_avcb_s + p_visa_s + p_rep_s + p_int_s

                    # Persistência de sub-quesitos e mestre
                    save_resp_isaude("10.0_total_est", str(t_est), p_avcb_s, "", d10_total_est.get("comentarios", []))
                    save_resp_isaude("10.0_com_avcb", str(c_avcb), 0.0, "", d10_com_avcb.get("comentarios", []))
                    save_resp_isaude("10.0_com_visa", str(c_visa), 0.0, "", d10_com_visa.get("comentarios", []))
                    save_resp_isaude("10.0_reparos", str(c_rep), p_rep_s, "", d10_reparos.get("comentarios", []))
                    save_resp_isaude("10.0_interromp", str(c_int), p_int_s, "", d10_interromp.get("comentarios", []))
                    save_resp_isaude("10.0", f"Cadastro {t_est} unidades", p_tot_s, lk_10, d10_mestre.get("comentarios", []))

                    v_link_salvo_10 = d10_mestre.get("link", "")
                    links_atuais_10 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lk_10 or "")]
                    links_antigos_10 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, v_link_salvo_10 or "")]

                    if lk_10 != v_link_salvo_10 and links_atuais_10 and links_atuais_10 != links_antigos_10:
                        st.session_state[f"links_pendentes_10_0_{ano_sel}"] = links_atuais_10
                        st.session_state[f"gatilho_modal_10_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Dados do Quesito 10.0 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                pts_atuais_10 = d10_mestre.get("pontos", 0.0)
                cor_txt_10 = "#28a745" if pts_atuais_10 > 0.0 else "#6c757d"

                st.markdown(
                    f"<span style='color:{cor_txt_10}; font-weight:bold;'>"
                    f"📊 Pontuação Consolidada no Quesito 10.0: {pts_atuais_10:.2f} pontos</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 10.0 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_10_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("10.0", st.session_state.get(f"links_pendentes_10_0_{ano_sel}", []), ano_sel)

        # =============================================================================
        # QUESITO 11.0 • EXISTÊNCIA DO PCCS
        # =============================================================================
        with st.container(key=f"container_bloco_isaude_11_0_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 11.0 - Existência de PCCS específico da Saúde (RAG {ano_sel})", expanded=True):
                st.subheader(f"11.0 • PCCS dos Profissionais de Saúde ({ano_sel})")
                st.write(
                    f"**O município possui Plano de Carreira, Cargos e Salários (PCCS) específico elaborado e implantado para seus profissionais de saúde em {ano_sel}?**"
                )
                st.caption("⚠️ *Nota: PCCS geral dos servidores públicos do município não é considerado PCCS específico para profissionais de saúde.*")

                opts_11_0 = {
                    "Selecione...": 0.0,
                    "Sim – 10": 10.0,
                    "Não – 00": 0.0
                }

                # Recupera do banco
                d11_0 = res_data.get("11.0") or {
                    "valor": "Selecione...",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_11_0 = d11_0.get("valor", "Selecione...")
                l_salvo_11_0 = d11_0.get("link", "")

                c110_1, c110_2 = st.columns([1, 1])

                with c110_1:
                    idx_11_0 = list(opts_11_0.keys()).index(v_salvo_11_0) if v_salvo_11_0 in opts_11_0 else 0
                    sel_11_0 = st.radio(
                        "Alternativas para o quesito 11.0:",
                        options=list(opts_11_0.keys()),
                        index=idx_11_0,
                        key=f"rb_saude_11_0_{ano_sel}",
                        label_visibility="collapsed"
                    )

                with c110_2:
                    val_input_11_0_link = st.text_area(
                        "Link/Evidência Geral (11.0):",
                        value=l_salvo_11_0,
                        key=f"txt_saude_11_0_{ano_sel}",
                        height=90
                    )

                    placeholder_links_11_0 = st.empty()
                    links_11_0_visuais = re.findall(REGEX_PURE_URL, val_input_11_0_link or "")
                    if links_11_0_visuais:
                        placeholder_links_11_0.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_11_0_visuais]
                            )
                        )

                # Renderização do chat de comentários
                bloco_comentarios_isaude("11.0", res_data)

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 11.0", key=f"btn_salvar_11_0_{ano_sel}", type="primary"):
                    val_opcao_11_0 = sel_11_0
                    val_link_11_0 = val_input_11_0_link.strip()
                    pts_11_0 = opts_11_0.get(val_opcao_11_0, 0.0)
                    comentarios_historico = d11_0.get("comentarios", [])

                    save_resp_isaude(
                        qid="11.0",
                        valor=val_opcao_11_0,
                        pontos=pts_11_0,
                        link=val_link_11_0,
                        comentarios=comentarios_historico
                    )

                    links_atuais_11 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, val_link_11_0 or "")]
                    links_antigos_11 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_11_0 or "")]

                    if val_link_11_0 != l_salvo_11_0 and links_atuais_11 and links_atuais_11 != links_antigos_11:
                        st.session_state[f"links_pendentes_11_0_{ano_sel}"] = links_atuais_11
                        st.session_state[f"gatilho_modal_11_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 11.0 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                pts_atuais_11_0 = d11_0.get("pontos", 0.0)
                cor_txt_11_0 = "#28a745" if pts_atuais_11_0 > 0.0 else "#6c757d"

                st.markdown(
                    f"<span style='color:{cor_txt_11_0}; font-weight:bold;'>"
                    f"📊 Pontuação Obtida no Quesito 11.0: +{pts_atuais_11_0:.1f} pontos</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 11.0 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_11_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("11.0", st.session_state.get(f"links_pendentes_11_0_{ano_sel}", []), ano_sel)

        # =============================================================================
        # QUESITO 11.1 • INSTRUMENTO NORMATIVO
        # =============================================================================
        with st.container(key=f"container_bloco_isaude_11_1_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 11.1 - Instrumento Normativo de Regulamentação (RAG {ano_sel})", expanded=True):
                st.subheader(f"11.1 • Regulamentação do PCCS ({ano_sel})")
                st.write(
                    f"**Informe o instrumento normativo de regulamentação do Plano de Carreira, Cargos e Salários (PCCS) específico para os profissionais da saúde em {ano_sel}, contendo Número e Data da publicação:**"
                )
                st.caption("ℹ️ *Preencha os campos textuais/links e clique no botão 'Salvar Quesito 11.1' para registrar.*")

                # Recupera os dados atuais do banco
                d11_1 = res_data.get("11.1") or {
                    "valor": "",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_11_1 = d11_1.get("valor", "")
                l_salvo_11_1 = d11_1.get("link", "")

                c111_1, c111_2 = st.columns([1, 1])

                with c111_1:
                    val_input_11_1_txt = st.text_area(
                        "Instrumento normativo, número e data de publicação:",
                        value=v_salvo_11_1,
                        height=120,
                        placeholder="Ex: Lei Complementar nº 123, de 10 de Março de 2021",
                        key=f"txt_area_saude_11_1_{ano_sel}"
                    )

                with c111_2:
                    val_input_11_1_link = st.text_input(
                        "Link do Documento / Evidência Digital:",
                        value=l_salvo_11_1,
                        key=f"txt_link_saude_11_1_{ano_sel}"
                    )

                    # Varre tanto o text_area quanto o text_input em busca de URLs ativas
                    texto_completo_11_1 = f"{val_input_11_1_txt} {val_input_11_1_link}"
                    links_11_1_visuais = re.findall(REGEX_PURE_URL, texto_completo_11_1 or "")
                    if links_11_1_visuais:
                        st.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_11_1_visuais]
                            )
                        )

                # Renderização do chat de comentários
                bloco_comentarios_isaude("11.1", res_data)

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 11.1", key=f"btn_salvar_11_1_{ano_sel}", type="primary"):
                    val_txt_11_1 = val_input_11_1_txt.strip()
                    val_lk_11_1 = val_input_11_1_link.strip()
                    pts_11_1 = 0.0  # Quesito Informativo / Sem impacto de nota direta
                    comentarios_historico = d11_1.get("comentarios", [])

                    save_resp_isaude(
                        qid="11.1",
                        valor=val_txt_11_1,
                        pontos=pts_11_1,
                        link=val_lk_11_1,
                        comentarios=comentarios_historico
                    )

                    # Verificação de modal de aviso para novos links digitados
                    texto_antigo_11_1 = f"{v_salvo_11_1} {l_salvo_11_1}"
                    links_atuais_11_1 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, texto_completo_11_1 or "")]
                    links_antigos_11_1 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, texto_antigo_11_1 or "")]

                    if (val_txt_11_1 != v_salvo_11_1 or val_lk_11_1 != l_salvo_11_1) and links_atuais_11_1 and links_atuais_11_1 != links_antigos_11_1:
                        st.session_state[f"links_pendentes_11_1_{ano_sel}"] = links_atuais_11_1
                        st.session_state[f"gatilho_modal_11_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 11.1 salvos com sucesso!", icon="✅")
                    st.rerun()

                st.markdown(
                    "<span style='color:#6c757d; font-weight:bold;'>"
                    "📊 Impacto de Pontuação no Quesito 11.1: 0.0 pontos (Quesito Informativo)</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 11.1 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_11_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("11.1", st.session_state.get(f"links_pendentes_11_1_{ano_sel}", []), ano_sel)

        # =============================================================================
        # QUESITO 11.2 • PÁGINA ELETRÔNICA / DIVULGAÇÃO
        # =============================================================================
        with st.container(key=f"container_bloco_isaude_11_2_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 11.2 - Página Eletrônica de Divulgação do PCCS (RAG {ano_sel})", expanded=True):
                st.subheader(f"11.2 • Divulgação Eletrônica do PCCS ({ano_sel})")
                st.write(
                    f"**Informe a página eletrônica (link na internet) de divulgação do Plano de Carreira, Cargos e Salários (PCCS) específico para os profissionais de saúde:**"
                )
                st.caption("⚠️ *Se não estiver disponível na internet, insira exatamente o texto **XYZ**.*")

                # Recupera os dados atuais do banco
                d11_2 = res_data.get("11.2") or {
                    "valor": "",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_11_2 = d11_2.get("valor", "")
                if not v_salvo_11_2:
                    v_salvo_11_2 = "XYZ"
                l_salvo_11_2 = d11_2.get("link", "")

                c112_1, c112_2 = st.columns([1, 1])

                with c112_1:
                    val_input_11_2_txt = st.text_input(
                        "Página eletrônica (link na internet) ou insira 'XYZ':",
                        value=v_salvo_11_2,
                        key=f"txt_val_saude_11_2_{ano_sel}"
                    )

                with c112_2:
                    val_input_11_2_link = st.text_input(
                        "Link auxiliar de auditoria (opcional):",
                        value=l_salvo_11_2,
                        key=f"txt_link_saude_11_2_{ano_sel}"
                    )

                    # Varre ambos os campos buscando URLs ativas
                    texto_completo_11_2 = f"{val_input_11_2_txt} {val_input_11_2_link}"
                    links_11_2_visuais = re.findall(REGEX_PURE_URL, texto_completo_11_2 or "")
                    if links_11_2_visuais:
                        st.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_11_2_visuais]
                            )
                        )

                # Renderização do chat de comentários
                bloco_comentarios_isaude("11.2", res_data)

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 11.2", key=f"btn_salvar_11_2_{ano_sel}", type="primary"):
                    val_txt_11_2 = val_input_11_2_txt.strip()
                    val_lk_11_2 = val_input_11_2_link.strip()
                    val_limpo_11_2 = val_txt_11_2.upper()

                    # Regra automatizada de pontuação
                    pts_11_2 = 0.0 if val_limpo_11_2 in ["XYZ", ""] else 2.0
                    comentarios_historico = d11_2.get("comentarios", [])

                    save_resp_isaude(
                        qid="11.2",
                        valor=val_txt_11_2,
                        pontos=pts_11_2,
                        link=val_lk_11_2,
                        comentarios=comentarios_historico
                    )

                    # Verificação do disparo do modal de links
                    texto_antigo_11_2 = f"{v_salvo_11_2} {l_salvo_11_2}"
                    links_atuais_11_2 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, texto_completo_11_2 or "")]
                    links_antigos_11_2 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, texto_antigo_11_2 or "")]

                    if (val_txt_11_2 != v_salvo_11_2 or val_lk_11_2 != l_salvo_11_2) and links_atuais_11_2 and links_atuais_11_2 != links_antigos_11_2:
                        st.session_state[f"links_pendentes_11_2_{ano_sel}"] = links_atuais_11_2
                        st.session_state[f"gatilho_modal_11_2_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 11.2 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                pts_atuais_11_2 = d11_2.get("pontos", 0.0)
                cor_txt_11_2 = "#28a745" if pts_atuais_11_2 > 0.0 else "#6c757d"

                st.markdown(
                    f"<span style='color:{cor_txt_11_2}; font-weight:bold;'>"
                    f"📊 Pontuação Obtida no Quesito 11.2: +{pts_atuais_11_2:.1f} pontos</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 11.2 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_11_2_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("11.2", st.session_state.get(f"links_pendentes_11_2_{ano_sel}", []), ano_sel)

        # =============================================================================
        # QUESITO 12.0 • ESTRATÉGIA DE SAÚDE DA FAMÍLIA (ESF)
        # =============================================================================
        with st.container(key=f"container_bloco_isaude_12_0_{ano_sel}", border=True):
            with st.expander(f"📌 QUESITO 12.0 • Estratégia de Saúde da Família (ESF) como Prioridade em {ano_sel}", expanded=True):
                st.subheader(f"12.0 • Priorização da ESF em {ano_sel}")
                st.write(
                    f"**O município adotou a Estratégia de Saúde da Família em sua rede de serviços como a estratégia prioritária de organização da Atenção Básica em {ano_sel}?**"
                )
                st.caption("ℹ️ *Selecione a opção, preencha as evidências e clique no botão 'Salvar Quesito 12.0' para registrar.*")

                opts_12_0 = {
                    "Selecione...": 0.0,
                    "Sim – 10": 10.0,
                    "Não – 00": 0.0
                }

                # Recupera os dados atuais do banco
                d12_0 = res_data.get("12.0") or {
                    "valor": "Selecione...",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_12_0 = d12_0.get("valor", "Selecione...")
                l_salvo_12_0 = d12_0.get("link", "")

                c25, c26 = st.columns([1, 1])

                with c25:
                    idx_12_0 = list(opts_12_0.keys()).index(v_salvo_12_0) if v_salvo_12_0 in opts_12_0 else 0
                    sel_12_0 = st.radio(
                        "Alternativas para o quesito 12.0:",
                        options=list(opts_12_0.keys()),
                        index=idx_12_0,
                        key=f"rb_saude_12_0_{ano_sel}",
                        label_visibility="collapsed"
                    )

                with c26:
                    link_12_0_input = st.text_area(
                        "Link/Evidência (Plano Municipal de Saúde ou normativas de reorganização da atenção básica):",
                        value=l_salvo_12_0,
                        key=f"txt_saude_12_0_{ano_sel}",
                        height=100
                    )

                    # Varre a área de texto em busca de URLs ativas
                    links_12_0_visuais = re.findall(REGEX_PURE_URL, link_12_0_input or "")
                    if links_12_0_visuais:
                        st.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_12_0_visuais]
                            )
                        )

                # Renderização do chat de comentários
                bloco_comentarios_isaude("12.0", res_data)

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 12.0", key=f"btn_salvar_12_0_{ano_sel}", type="primary"):
                    val_sel_12_0 = sel_12_0 if sel_12_0 is not None else "Selecione..."
                    val_lk_12_0 = link_12_0_input.strip()
                    pts_12_0 = opts_12_0.get(val_sel_12_0, 0.0)
                    comentarios_historico = d12_0.get("comentarios", [])

                    save_resp_isaude(
                        qid="12.0",
                        valor=val_sel_12_0,
                        pontos=pts_12_0,
                        link=val_lk_12_0,
                        comentarios=comentarios_historico
                    )

                    # Verificação de disparo do modal de aviso para novos links digitados
                    links_atuais_12_0 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_12_0_input or "")]
                    links_antigos_12_0 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_12_0 or "")]

                    if (val_sel_12_0 != v_salvo_12_0 or val_lk_12_0 != l_salvo_12_0) and links_atuais_12_0 and links_atuais_12_0 != links_antigos_12_0:
                        st.session_state[f"links_pendentes_12_0_{ano_sel}"] = links_atuais_12_0
                        st.session_state[f"gatilho_modal_12_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 12.0 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                pts_atuais_12_0 = d12_0.get("pontos", 0.0)
                cor_txt_12_0 = "#28a745" if pts_atuais_12_0 > 0.0 else "#6c757d"

                st.markdown(
                    f"<span style='color:{cor_txt_12_0}; font-weight:bold;'>"
                    f"📊 Pontuação Obtida no Quesito 12.0: +{pts_atuais_12_0:.1f} pontos</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 12.0 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_12_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("12.0", st.session_state.get(f"links_pendentes_12_0_{ano_sel}", []), ano_sel)

        # =============================================================================
        # QUESITO 12.1 • EQUIPES COMPLETAS E INCOMPLETAS
        # =============================================================================
        with st.container(key=f"container_bloco_isaude_12_1_{ano_sel}", border=True):
            with st.expander(f"📋 QUESITO 12.1 • Composição das Equipes (eSF + eAP) em {ano_sel}", expanded=True):
                st.subheader("12.1 • Equipes Completas e Incompletas")
                st.write(f"**Informe o total de equipes de saúde da família e equipes de atenção primária (eSF+eAP) em {ano_sel}:**")
                st.caption("ℹ️ *Equipe Completa: eSF (Médico, Enfermeiro, Aux/Téc Enfermagem e ACS) ou eAP (Médico e Enfermeiro). No descumprimento, classifique como Incompleta.*")

                # Recupera os dados salvos das subchaves e da chave mestre
                d12_1_ec = res_data.get("12.1_ec") or {"valor": "0", "pontos": 0.0, "link": "", "comentarios": []}
                d12_1_ei = res_data.get("12.1_ei") or {"valor": "0", "pontos": 0.0, "link": "", "comentarios": []}
                d12_1_mestre = res_data.get("12.1") or {"valor": "", "pontos": 0.0, "link": "", "comentarios": []}

                try:
                    v_ec_salvo = int(d12_1_ec.get("valor", 0))
                except (ValueError, TypeError):
                    v_ec_salvo = 0

                try:
                    v_ei_salvo = int(d12_1_ei.get("valor", 0))
                except (ValueError, TypeError):
                    v_ei_salvo = 0

                l_salvo_12_1 = d12_1_mestre.get("link", "")

                c27, c28 = st.columns([1, 1])

                with c27:
                    val_ec = st.number_input(
                        "Nº de equipes completas (EC):",
                        min_value=0,
                        step=1,
                        value=v_ec_salvo,
                        key=f"num_12_1_ec_{ano_sel}"
                    )
                    val_ei = st.number_input(
                        "Nº de equipes incompletas (EI):",
                        min_value=0,
                        step=1,
                        value=v_ei_salvo,
                        key=f"num_12_1_ei_{ano_sel}"
                    )

                # Cálculo de Proporção Dinâmico: NF = [EC / (EC + EI)] * 50
                total_equipes = val_ec + val_ei
                pts_12_1_calc = (val_ec / total_equipes) * 50.0 if total_equipes > 0 else 0.0

                with c28:
                    link_12_1_input = st.text_area(
                        "Link/Evidência (Relatório de equipes CNES ou validação do e-Gestor Atenção Básica):",
                        value=l_salvo_12_1,
                        key=f"txt_saude_12_1_{ano_sel}",
                        height=115
                    )

                    # Varre a área de texto em busca de URLs ativas
                    links_12_1_visuais = re.findall(REGEX_PURE_URL, link_12_1_input or "")
                    if links_12_1_visuais:
                        st.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_12_1_visuais]
                            )
                        )

                # Renderização do chat de comentários
                bloco_comentarios_isaude("12.1", res_data)

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 12.1", key=f"btn_salvar_12_1_{ano_sel}", type="primary"):
                    val_lk_12_1 = link_12_1_input.strip()
                    hist_ec = d12_1_ec.get("comentarios", [])
                    hist_ei = d12_1_ei.get("comentarios", [])
                    hist_mestre = d12_1_mestre.get("comentarios", [])

                    # Persiste subchaves e mestre no banco de dados
                    save_resp_isaude(
                        qid="12.1_ec",
                        valor=str(val_ec),
                        pontos=pts_12_1_calc,
                        link="",
                        comentarios=hist_ec
                    )
                    save_resp_isaude(
                        qid="12.1_ei",
                        valor=str(val_ei),
                        pontos=0.0,
                        link="",
                        comentarios=hist_ei
                    )
                    save_resp_isaude(
                        qid="12.1",
                        valor=f"EC: {val_ec} | EI: {val_ei}",
                        pontos=pts_12_1_calc,
                        link=val_lk_12_1,
                        comentarios=hist_mestre
                    )

                    # Verificação do disparo do modal de aviso para links novos
                    links_atuais_12_1 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_12_1_input or "")]
                    links_antigos_12_1 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_12_1 or "")]

                    if (val_ec != v_ec_salvo or val_ei != v_ei_salvo or val_lk_12_1 != l_salvo_12_1) and links_atuais_12_1 and links_atuais_12_1 != links_antigos_12_1:
                        st.session_state[f"links_pendentes_12_1_{ano_sel}"] = links_atuais_12_1
                        st.session_state[f"gatilho_modal_12_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 12.1 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                pts_atuais_12_1 = d12_1_mestre.get("pontos", 0.0)
                cor_txt_12_1 = "#28a745" if pts_atuais_12_1 > 0.0 else "#6c757d"

                st.markdown(
                    f"<span style='color:{cor_txt_12_1}; font-weight:bold;'>"
                    f"📊 Pontuação Obtida no Quesito 12.1: +{pts_atuais_12_1:.2f} / 50.0 pontos</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 12.1 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_12_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("12.1", st.session_state.get(f"links_pendentes_12_1_{ano_sel}", []), ano_sel)

        # =============================================================================
        # QUESITO 12.2 • PESSOAS CADASTRADAS POR EQUIPE
        # =============================================================================
        with st.container(key=f"container_bloco_isaude_12_2_{ano_sel}", border=True):
            with st.expander(f"🌐 QUESITO 12.2 • Proporção de Pessoas Cadastradas por Equipe em {ano_sel}", expanded=True):
                st.subheader("12.2 • Parâmetro Populacional por Equipe")
                st.write(f"**Informe o número de pessoas cadastradas nas equipes em {ano_sel}:**")
                st.caption("ℹ️ *A média por equipe e pontuação são recalculadas. Preencha e clique no botão 'Salvar Quesito 12.2' para registrar.*")

                # Recupera os dados salvos das subchaves e da chave mestre
                d12_2_esf = res_data.get("12.2_esf") or {"valor": "0", "pontos": 0.0, "link": "", "comentarios": []}
                d12_2_eap = res_data.get("12.2_eap") or {"valor": "0", "pontos": 0.0, "link": "", "comentarios": []}
                d12_2_mestre = res_data.get("12.2") or {"valor": "", "pontos": 0.0, "link": "", "comentarios": []}

                try:
                    v_esf_salvo = int(d12_2_esf.get("valor", 0))
                except (ValueError, TypeError):
                    v_esf_salvo = 0

                try:
                    v_eap_salvo = int(d12_2_eap.get("valor", 0))
                except (ValueError, TypeError):
                    v_eap_salvo = 0

                l_salvo_12_2 = d12_2_mestre.get("link", "")

                c29, c30 = st.columns([1, 1])

                with c29:
                    val_cad_esf = st.number_input(
                        "Nº de pessoas cadastradas nas Equipes de Saúde da Família (ESF):",
                        min_value=0,
                        step=1,
                        value=v_esf_salvo,
                        key=f"num_12_2_esf_{ano_sel}"
                    )
                    val_cad_eap = st.number_input(
                        "Nº de pessoas cadastradas nas Equipes de Atenção Primária (EAP):",
                        min_value=0,
                        step=1,
                        value=v_eap_salvo,
                        key=f"num_12_2_eap_{ano_sel}"
                    )

                # Regra de cálculo de cobertura média por equipe: (ESF + EAP) / total_equipes (obtido no Quesito 12.1)
                total_cadastrados = val_cad_esf + val_cad_eap
                pts_12_2_calc = 0.0
                media_por_equipe = 0.0

                if total_equipes > 0:
                    media_por_equipe = total_cadastrados / total_equipes
                    if 2000 <= media_por_equipe <= 4000:
                        pts_12_2_calc = 40.0

                with c30:
                    link_12_2_input = st.text_area(
                        "Link/Evidência (Relatórios de cadastros do SISAB - Sistema de Informação em Saúde para a Atenção Básica):",
                        value=l_salvo_12_2,
                        key=f"txt_saude_12_2_{ano_sel}",
                        height=115
                    )

                    # Varre a área de texto em busca de URLs ativas
                    links_12_2_visuais = re.findall(REGEX_PURE_URL, link_12_2_input or "")
                    if links_12_2_visuais:
                        st.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_12_2_visuais]
                            )
                        )

                    if total_equipes > 0:
                        st.markdown(f"ℹ️ *Média Calculada: `{media_por_equipe:.0f}` pessoas por equipe.*")
                    else:
                        st.markdown("⚠️ *Preencha o total de equipes no Quesito 12.1 para calcular a média por equipe.*")

                # Renderização do chat de comentários
                bloco_comentarios_isaude("12.2", res_data)

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 12.2", key=f"btn_salvar_12_2_{ano_sel}", type="primary"):
                    val_lk_12_2 = link_12_2_input.strip()
                    hist_esf = d12_2_esf.get("comentarios", [])
                    hist_eap = d12_2_eap.get("comentarios", [])
                    hist_mestre_12_2 = d12_2_mestre.get("comentarios", [])

                    # Persiste subchaves e mestre no banco de dados
                    save_resp_isaude(
                        qid="12.2_esf",
                        valor=str(val_cad_esf),
                        pontos=pts_12_2_calc,
                        link="",
                        comentarios=hist_esf
                    )
                    save_resp_isaude(
                        qid="12.2_eap",
                        valor=str(val_cad_eap),
                        pontos=0.0,
                        link="",
                        comentarios=hist_eap
                    )
                    save_resp_isaude(
                        qid="12.2",
                        valor=f"ESF: {val_cad_esf} | EAP: {val_cad_eap}",
                        pontos=pts_12_2_calc,
                        link=val_lk_12_2,
                        comentarios=hist_mestre_12_2
                    )

                    # Verificação do disparo do modal de aviso para links novos
                    links_atuais_12_2 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_12_2_input or "")]
                    links_antigos_12_2 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_12_2 or "")]

                    if (val_cad_esf != v_esf_salvo or val_cad_eap != v_eap_salvo or val_lk_12_2 != l_salvo_12_2) and links_atuais_12_2 and links_atuais_12_2 != links_antigos_12_2:
                        st.session_state[f"links_pendentes_12_2_{ano_sel}"] = links_atuais_12_2
                        st.session_state[f"gatilho_modal_12_2_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 12.2 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                pts_atuais_12_2 = d12_2_mestre.get("pontos", 0.0)
                cor_txt_12_2 = "#28a745" if pts_atuais_12_2 > 0.0 else "#6c757d"

                st.markdown(
                    f"<span style='color:{cor_txt_12_2}; font-weight:bold;'>"
                    f"📊 Pontuação Obtida no Quesito 12.2: +{pts_atuais_12_2:.1f} / 40.0 pontos</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 12.2 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_12_2_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("12.2", st.session_state.get(f"links_pendentes_12_2_{ano_sel}", []), ano_sel)

        # =============================================================================
        # QUESITO 13.0 • REGISTRO DE FREQUÊNCIA ELETRÔNICA
        # =============================================================================
        with st.container(key=f"container_bloco_isaude_13_0_{ano_sel}", border=True):
            with st.expander(f"📌 QUESITO 13.0 • Registro de Frequência Eletrônica em {ano_sel}", expanded=True):
                st.subheader(f"13.0 • Frequência Eletrônica na Atenção Básica ({ano_sel})")
                st.write(
                    f"**A Prefeitura registra a frequência dos profissionais de saúde da Atenção Básica de forma eletrônica em {ano_sel}?**"
                )
                st.caption("⚠️ *Obs: O encaminhamento de planilhas de ponto não será considerado como modalidade de registro eletrônico.*")
                st.caption("ℹ️ *Selecione a opção, preencha as evidências e clique no botão 'Salvar Quesito 13.0' para registrar.*")

                opts_13_0 = {
                    "Selecione...": 0.0,
                    "Sim, para todos os profissionais da saúde – 05": 5.0,
                    "Sim, para a maior parte dos profissionais da saúde – 03": 3.0,
                    "Sim, para a menor parte dos profissionais da saúde – 01": 1.0,
                    "Não houve registro eletrônico de nenhum profissional de saúde – 00": 0.0
                }

                # Recupera os dados atuais do banco
                d13_0 = res_data.get("13.0") or {
                    "valor": "Selecione...",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_13_0 = d13_0.get("valor", "Selecione...")
                l_salvo_13_0 = d13_0.get("link", "")

                c31, c32 = st.columns([1, 1])

                with c31:
                    idx_13_0 = list(opts_13_0.keys()).index(v_salvo_13_0) if v_salvo_13_0 in opts_13_0 else 0
                    sel_13_0 = st.radio(
                        "Alternativas para o quesito 13.0:",
                        options=list(opts_13_0.keys()),
                        index=idx_13_0,
                        key=f"rb_saude_13_0_{ano_sel}",
                        label_visibility="collapsed"
                    )

                with c32:
                    link_13_0_input = st.text_area(
                        "Link/Evidência (Relatório ou telas do sistema de ponto eletrônico biométrico/digital):",
                        value=l_salvo_13_0,
                        key=f"txt_saude_13_0_{ano_sel}",
                        height=110
                    )

                    # Varre a área de texto em busca de URLs ativas
                    links_13_0_visuais = re.findall(REGEX_PURE_URL, link_13_0_input or "")
                    if links_13_0_visuais:
                        st.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_13_0_visuais]
                            )
                        )

                # Renderização do chat de comentários
                bloco_comentarios_isaude("13.0", res_data)

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 13.0", key=f"btn_salvar_13_0_{ano_sel}", type="primary"):
                    val_sel_13_0 = sel_13_0 if sel_13_0 is not None else "Selecione..."
                    val_lk_13_0 = link_13_0_input.strip()
                    pts_13_0 = opts_13_0.get(val_sel_13_0, 0.0)
                    comentarios_historico = d13_0.get("comentarios", [])

                    save_resp_isaude(
                        qid="13.0",
                        valor=val_sel_13_0,
                        pontos=pts_13_0,
                        link=val_lk_13_0,
                        comentarios=comentarios_historico
                    )

                    # Verificação de disparo do modal de aviso para novos links digitados
                    links_atuais_13_0 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_13_0_input or "")]
                    links_antigos_13_0 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_13_0 or "")]

                    if (val_sel_13_0 != v_salvo_13_0 or val_lk_13_0 != l_salvo_13_0) and links_atuais_13_0 and links_atuais_13_0 != links_antigos_13_0:
                        st.session_state[f"links_pendentes_13_0_{ano_sel}"] = links_atuais_13_0
                        st.session_state[f"gatilho_modal_13_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 13.0 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                pts_atuais_13_0 = d13_0.get("pontos", 0.0)
                cor_txt_13_0 = "#28a745" if pts_atuais_13_0 > 0.0 else "#6c757d"

                st.markdown(
                    f"<span style='color:{cor_txt_13_0}; font-weight:bold;'>"
                    f"📊 Pontuação Obtida no Quesito 13.0: +{pts_atuais_13_0:.1f} pontos</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 13.0 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_13_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("13.0", st.session_state.get(f"links_pendentes_13_0_{ano_sel}", []), ano_sel)


        # =============================================================================
        # QUESITO 13.1 • CUMPRIMENTO DA JORNADA DE TRABALHO DOS MÉDICOS
        # =============================================================================
        with st.container(key=f"container_bloco_isaude_13_1_{ano_sel}", border=True):
            with st.expander(f"📋 QUESITO 13.1 • Cumprimento da Jornada de Trabalho dos Médicos em {ano_sel}", expanded=True):
                st.subheader(f"13.1 • Jornada de Trabalho Médica ({ano_sel})")
                st.write(
                    f"**Os médicos da Atenção Básica cumprem integralmente sua jornada de trabalho em {ano_sel}?**"
                )
                st.caption("ℹ️ *Selecione a opção, preencha as evidências e clique no botão 'Salvar Quesito 13.1' para registrar.*")

                opts_13_1 = {
                    "Selecione...": 0.0,
                    "Sim, todos cumprem integralmente a jornada de trabalho – 15": 15.0,
                    "Sim, a maior parte cumpre integralmente a jornada de trabalho – 08": 8.0,
                    "Sim, todos permanecem apenas nas consultas agendadas – 05": 5.0,
                    "Sim, a maior parte permanece apenas nas consultas agendadas – 02": 2.0,
                    "Não – 00": 0.0
                }

                # Recupera os dados atuais do banco
                d13_1 = res_data.get("13.1") or {
                    "valor": "Selecione...",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_13_1 = d13_1.get("valor", "Selecione...")
                l_salvo_13_1 = d13_1.get("link", "")

                c33, c34 = st.columns([1, 1])

                with c33:
                    idx_13_1 = list(opts_13_1.keys()).index(v_salvo_13_1) if v_salvo_13_1 in opts_13_1 else 0
                    sel_13_1 = st.radio(
                        "Alternativas para o quesito 13.1:",
                        options=list(opts_13_1.keys()),
                        index=idx_13_1,
                        key=f"rb_saude_13_1_{ano_sel}",
                        label_visibility="collapsed"
                    )

                with c34:
                    link_13_1_input = st.text_area(
                        "Link/Evidência (Espelhos de ponto homologados, agendas do e-SUS ou relatórios de produtividade/atendimento):",
                        value=l_salvo_13_1,
                        key=f"txt_saude_13_1_{ano_sel}",
                        height=130
                    )

                    # Varre a área de texto em busca de URLs ativas
                    links_13_1_visuais = re.findall(REGEX_PURE_URL, link_13_1_input or "")
                    if links_13_1_visuais:
                        st.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_13_1_visuais]
                            )
                        )

                # Renderização do chat de comentários
                bloco_comentarios_isaude("13.1", res_data)

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 13.1", key=f"btn_salvar_13_1_{ano_sel}", type="primary"):
                    val_sel_13_1 = sel_13_1 if sel_13_1 is not None else "Selecione..."
                    val_lk_13_1 = link_13_1_input.strip()
                    pts_13_1 = opts_13_1.get(val_sel_13_1, 0.0)
                    comentarios_historico = d13_1.get("comentarios", [])

                    save_resp_isaude(
                        qid="13.1",
                        valor=val_sel_13_1,
                        pontos=pts_13_1,
                        link=val_lk_13_1,
                        comentarios=comentarios_historico
                    )

                    # Verificação de disparo do modal de aviso para novos links digitados
                    links_atuais_13_1 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_13_1_input or "")]
                    links_antigos_13_1 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_13_1 or "")]

                    if (val_sel_13_1 != v_salvo_13_1 or val_lk_13_1 != l_salvo_13_1) and links_atuais_13_1 and links_atuais_13_1 != links_antigos_13_1:
                        st.session_state[f"links_pendentes_13_1_{ano_sel}"] = links_atuais_13_1
                        st.session_state[f"gatilho_modal_13_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 13.1 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                pts_atuais_13_1 = d13_1.get("pontos", 0.0)
                cor_txt_13_1 = "#28a745" if pts_atuais_13_1 > 0.0 else "#6c757d"

                st.markdown(
                    f"<span style='color:{cor_txt_13_1}; font-weight:bold;'>"
                    f"📊 Pontuação Obtida no Quesito 13.1: +{pts_atuais_13_1:.1f} pontos</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 13.1 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_13_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("13.1", st.session_state.get(f"links_pendentes_13_1_{ano_sel}", []), ano_sel)

        # =============================================================================
        # QUESITO 14.0 • INTERVALO DE AGENDAMENTO DE CONSULTAS
        # =============================================================================
        with st.container(key=f"container_bloco_isaude_14_0_{ano_sel}", border=True):
            with st.expander(f"📌 QUESITO 14.0 • Intervalo de Agendamento de Consultas em {ano_sel}", expanded=True):
                st.subheader(f"14.0 • Intervalo de Agendamento de Consultas ({ano_sel})")
                st.write(
                    f"**Assinale o intervalo de agendamento das consultas médicas na Atenção Básica em {ano_sel}:**"
                )
                st.caption("ℹ️ *Selecione a opção, preencha as evidências e clique no botão 'Salvar Quesito 14.0' para registrar.*")

                opts_14_0 = {
                    "Selecione...": 0.0,
                    "Não há agendamento de consultas, pois todos os atendimentos são de pronto atendimento – 01": 1.0,
                    "Agendamento de cada paciente em horário único com, no mínimo, 15 minutos de atendimento – 01": 1.0,
                    "Agendamento de cada paciente em horário único com menos de 15 minutos de atendimento – 00": 0.0,
                    "Agendamento de 2 ou mais pacientes no mesmo horário – 00": 0.0
                }

                # Recupera os dados atuais do banco
                d14_0 = res_data.get("14.0") or {
                    "valor": "Selecione...",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_14_0 = d14_0.get("valor", "Selecione...")
                l_salvo_14_0 = d14_0.get("link", "")

                c35, c36 = st.columns([1, 1])

                with c35:
                    idx_14_0 = list(opts_14_0.keys()).index(v_salvo_14_0) if v_salvo_14_0 in opts_14_0 else 0
                    sel_14_0 = st.radio(
                        "Alternativas para o quesito 14.0:",
                        options=list(opts_14_0.keys()),
                        index=idx_14_0,
                        key=f"rb_saude_14_0_{ano_sel}",
                        label_visibility="collapsed"
                    )

                with c36:
                    link_14_0_input = st.text_area(
                        "Link/Evidência (Protocolo de agendamento ou prints das telas de parametrização de horários do prontuário eletrônico):",
                        value=l_salvo_14_0,
                        key=f"txt_saude_14_0_{ano_sel}",
                        height=110
                    )

                    # Varre a área de texto em busca de URLs ativas
                    links_14_0_visuais = re.findall(REGEX_PURE_URL, link_14_0_input or "")
                    if links_14_0_visuais:
                        st.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_14_0_visuais]
                            )
                        )

                # Renderização do chat de comentários
                bloco_comentarios_isaude("14.0", res_data)

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 14.0", key=f"btn_salvar_14_0_{ano_sel}", type="primary"):
                    val_sel_14_0 = sel_14_0 if sel_14_0 is not None else "Selecione..."
                    val_lk_14_0 = link_14_0_input.strip()
                    pts_14_0 = opts_14_0.get(val_sel_14_0, 0.0)
                    comentarios_historico = d14_0.get("comentarios", [])

                    save_resp_isaude(
                        qid="14.0",
                        valor=val_sel_14_0,
                        pontos=pts_14_0,
                        link=val_lk_14_0,
                        comentarios=comentarios_historico
                    )

                    # Verificação de disparo do modal de aviso para novos links digitados
                    links_atuais_14_0 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_14_0_input or "")]
                    links_antigos_14_0 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_14_0 or "")]

                    if (val_sel_14_0 != v_salvo_14_0 or val_lk_14_0 != l_salvo_14_0) and links_atuais_14_0 and links_atuais_14_0 != links_antigos_14_0:
                        st.session_state[f"links_pendentes_14_0_{ano_sel}"] = links_atuais_14_0
                        st.session_state[f"gatilho_modal_14_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 14.0 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                pts_atuais_14_0 = d14_0.get("pontos", 0.0)
                cor_txt_14_0 = "#28a745" if pts_atuais_14_0 > 0.0 else "#6c757d"

                st.markdown(
                    f"<span style='color:{cor_txt_14_0}; font-weight:bold;'>"
                    f"📊 Pontuação Obtida no Quesito 14.0: +{pts_atuais_14_0:.1f} pontos</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 14.0 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_14_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("14.0", st.session_state.get(f"links_pendentes_14_0_{ano_sel}", []), ano_sel)


        # =============================================================================
        # QUESITO 14.1 • SERVIÇO DE AGENDAMENTO REMOTO
        # =============================================================================
        with st.container(key=f"container_bloco_isaude_14_1_{ano_sel}", border=True):
            with st.expander(f"📱 QUESITO 14.1 • Serviço de Agendamento Remoto em {ano_sel}", expanded=True):
                st.subheader(f"14.1 • Agendamento Remoto ({ano_sel})")
                st.write(
                    f"**O município disponibilizou serviço de agendamento remoto para consulta médica na Atenção Básica em {ano_sel}?**"
                )
                st.caption("ℹ️ *Exemplos de Agendamento Remoto: por telefone, internet, aplicativo, Voip, etc.*")
                st.caption("ℹ️ *Selecione a opção, preencha as evidências e clique no botão 'Salvar Quesito 14.1' para registrar.*")

                opts_14_1 = {
                    "Selecione...": 0.0,
                    "Sim – 10": 10.0,
                    "Não – 00": 0.0
                }

                # Recupera os dados atuais do banco
                d14_1 = res_data.get("14.1") or {
                    "valor": "Selecione...",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_14_1 = d14_1.get("valor", "Selecione...")
                l_salvo_14_1 = d14_1.get("link", "")

                c37, c38 = st.columns([1, 1])

                with c37:
                    idx_14_1 = list(opts_14_1.keys()).index(v_salvo_14_1) if v_salvo_14_1 in opts_14_1 else 0
                    sel_14_1 = st.radio(
                        "Alternativas para o quesito 14.1:",
                        options=list(opts_14_1.keys()),
                        index=idx_14_1,
                        key=f"rb_saude_14_1_{ano_sel}",
                        label_visibility="collapsed"
                    )

                with c38:
                    link_14_1_input = st.text_area(
                        "Link/Evidência (Print do canal web, app, normativas do serviço telefônico ou central de agendamentos):",
                        value=l_salvo_14_1,
                        key=f"txt_saude_14_1_{ano_sel}",
                        height=100
                    )

                    # Varre a área de texto em busca de URLs ativas
                    links_14_1_visuais = re.findall(REGEX_PURE_URL, link_14_1_input or "")
                    if links_14_1_visuais:
                        st.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_14_1_visuais]
                            )
                        )

                # Renderização do chat de comentários
                bloco_comentarios_isaude("14.1", res_data)

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 14.1", key=f"btn_salvar_14_1_{ano_sel}", type="primary"):
                    val_sel_14_1 = sel_14_1 if sel_14_1 is not None else "Selecione..."
                    val_lk_14_1 = link_14_1_input.strip()
                    pts_14_1 = opts_14_1.get(val_sel_14_1, 0.0)
                    comentarios_historico = d14_1.get("comentarios", [])

                    save_resp_isaude(
                        qid="14.1",
                        valor=val_sel_14_1,
                        pontos=pts_14_1,
                        link=val_lk_14_1,
                        comentarios=comentarios_historico
                    )

                    # Verificação de disparo do modal de aviso para novos links digitados
                    links_atuais_14_1 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_14_1_input or "")]
                    links_antigos_14_1 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_14_1 or "")]

                    if (val_sel_14_1 != v_salvo_14_1 or val_lk_14_1 != l_salvo_14_1) and links_atuais_14_1 and links_atuais_14_1 != links_antigos_14_1:
                        st.session_state[f"links_pendentes_14_1_{ano_sel}"] = links_atuais_14_1
                        st.session_state[f"gatilho_modal_14_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 14.1 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                pts_atuais_14_1 = d14_1.get("pontos", 0.0)
                cor_txt_14_1 = "#28a745" if pts_atuais_14_1 > 0.0 else "#6c757d"

                st.markdown(
                    f"<span style='color:{cor_txt_14_1}; font-weight:bold;'>"
                    f"📊 Pontuação Obtida no Quesito 14.1: +{pts_atuais_14_1:.1f} pontos</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 14.1 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_14_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("14.1", st.session_state.get(f"links_pendentes_14_1_{ano_sel}", []), ano_sel)

        # =============================================================================
        # QUESITO 14.2 • CONTROLE DE ABSENTEÍSMO
        # =============================================================================
        with st.container(key=f"container_bloco_isaude_14_2_{ano_sel}", border=True):
            with st.expander(f"📊 QUESITO 14.2 • Controle de Absenteísmo em {ano_sel}", expanded=True):
                st.subheader(f"14.2 • Controle de Absenteísmo ({ano_sel})")
                st.write(
                    f"**O município possui controle de absenteísmo (gestão de faltas de pacientes) para as consultas médicas da Atenção Básica em {ano_sel}?**"
                )
                st.caption("ℹ️ *Selecione a opção, preencha as evidências e clique no botão 'Salvar Quesito 14.2' para registrar.*")

                opts_14_2 = {
                    "Selecione...": 0.0,
                    "Sim, para todas as consultas – 02": 2.0,
                    "Sim, para a maior parte das consultas – 01": 1.0,
                    "Sim, para a menor parte das consultas – 0.5": 0.5,
                    "Não – 00": 0.0
                }

                # Recupera os dados atuais do banco
                d14_2 = res_data.get("14.2") or {
                    "valor": "Selecione...",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_14_2 = d14_2.get("valor", "Selecione...")
                l_salvo_14_2 = d14_2.get("link", "")

                c39, c40 = st.columns([1, 1])

                with c39:
                    idx_14_2 = list(opts_14_2.keys()).index(v_salvo_14_2) if v_salvo_14_2 in opts_14_2 else 0
                    sel_14_2 = st.radio(
                        "Alternativas para o quesito 14.2:",
                        options=list(opts_14_2.keys()),
                        index=idx_14_2,
                        key=f"rb_saude_14_2_{ano_sel}",
                        label_visibility="collapsed"
                    )

                with c40:
                    link_14_2_input = st.text_area(
                        "Link/Evidência (Relatórios estatísticos de faltas ou relatórios emitidos via Prontuário Eletrônico/SISAB):",
                        value=l_salvo_14_2,
                        key=f"txt_saude_14_2_{ano_sel}",
                        height=110
                    )

                    # Varre a área de texto em busca de URLs ativas
                    links_14_2_visuais = re.findall(REGEX_PURE_URL, link_14_2_input or "")
                    if links_14_2_visuais:
                        st.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_14_2_visuais]
                            )
                        )

                # Renderização do chat de comentários
                bloco_comentarios_isaude("14.2", res_data)

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 14.2", key=f"btn_salvar_14_2_{ano_sel}", type="primary"):
                    val_sel_14_2 = sel_14_2 if sel_14_2 is not None else "Selecione..."
                    val_lk_14_2 = link_14_2_input.strip()
                    pts_14_2 = opts_14_2.get(val_sel_14_2, 0.0)
                    comentarios_historico = d14_2.get("comentarios", [])

                    save_resp_isaude(
                        qid="14.2",
                        valor=val_sel_14_2,
                        pontos=pts_14_2,
                        link=val_lk_14_2,
                        comentarios=comentarios_historico
                    )

                    # Verificação de disparo do modal de aviso para novos links digitados
                    links_atuais_14_2 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_14_2_input or "")]
                    links_antigos_14_2 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_14_2 or "")]

                    if (val_sel_14_2 != v_salvo_14_2 or val_lk_14_2 != l_salvo_14_2) and links_atuais_14_2 and links_atuais_14_2 != links_antigos_14_2:
                        st.session_state[f"links_pendentes_14_2_{ano_sel}"] = links_atuais_14_2
                        st.session_state[f"gatilho_modal_14_2_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 14.2 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                pts_atuais_14_2 = d14_2.get("pontos", 0.0)
                cor_txt_14_2 = "#28a745" if pts_atuais_14_2 > 0.0 else "#6c757d"

                st.markdown(
                    f"<span style='color:{cor_txt_14_2}; font-weight:bold;'>"
                    f"📊 Pontuação Obtida no Quesito 14.2: +{pts_atuais_14_2:.1f} pontos</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 14.2 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_14_2_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("14.2", st.session_state.get(f"links_pendentes_14_2_{ano_sel}", []), ano_sel)

        # =============================================================================
        # QUESITO 14.2.1 • TAXA HISTÓRICA DE ABSENTEÍSMO
        # =============================================================================
        with st.container(key=f"container_filho_14_2_1_{ano_sel}", border=True):
            st.subheader(f"14.2.1 • Taxa Histórica de Absenteísmo ({ano_sel})")
            st.write(f"**Informe a taxa de absenteísmo de consulta médica nas UBSs (em %):**")
            st.caption("ℹ️ *Preencha os valores, informe as evidências e clique no botão 'Salvar Quesito 14.2.1' para registrar.*")

            # Resgata dados numéricos históricos e main do banco
            d14_2_1_ta2 = res_data.get("14.2.1_ta2") or {"valor": "0.0", "pontos": 0.0, "link": "", "comentarios": []}
            d14_2_1_ta1 = res_data.get("14.2.1_ta1") or {"valor": "0.0", "pontos": 0.0, "link": "", "comentarios": []}
            d14_2_1_ta  = res_data.get("14.2.1_ta")  or {"valor": "0.0", "pontos": 0.0, "link": "", "comentarios": []}
            d14_2_1_main = res_data.get("14.2.1")    or {"valor": "", "pontos": 0.0, "link": "", "comentarios": []}

            v_ta2_salvo = float(d14_2_1_ta2.get("valor", 0.0) or 0.0)
            v_ta1_salvo = float(d14_2_1_ta1.get("valor", 0.0) or 0.0)
            v_ta_salvo  = float(d14_2_1_ta.get("valor", 0.0) or 0.0)
            l_salvo_14_2_1 = d14_2_1_main.get("link", "")

            c41, c42 = st.columns([1, 1])

            with c41:
                val_ta2 = st.number_input(
                    f"Taxa de absenteísmo em consultas médicas nas UBSs em {ano_sel - 2} (TA-2):", 
                    min_value=0.0, 
                    max_value=100.0, 
                    step=0.1, 
                    value=v_ta2_salvo, 
                    key=f"num_14_2_1_ta2_{ano_sel}"
                )
                val_ta1 = st.number_input(
                    f"Taxa de absenteísmo em consultas médicas nas UBSs em {ano_sel - 1} (TA-1):", 
                    min_value=0.0, 
                    max_value=100.0, 
                    step=0.1, 
                    value=v_ta1_salvo, 
                    key=f"num_14_2_1_ta1_{ano_sel}"
                )
                val_ta  = st.number_input(
                    f"Taxa de absenteísmo em consultas médicas nas UBSs em {ano_sel} (TA):", 
                    min_value=0.0, 
                    max_value=100.0, 
                    step=0.1, 
                    value=v_ta_salvo, 
                    key=f"num_14_2_1_ta_{ano_sel}"
                )

            # Cálculo de pontuação: Se TA <= média dos 2 últimos anos = 10 pontos | Senão = 0 pontos
            media_dois_anos = (val_ta2 + val_ta1) / 2.0
            if val_ta <= media_dois_anos and (val_ta2 > 0 or val_ta1 > 0):
                pts_14_2_1 = 10.0
            else:
                pts_14_2_1 = 0.0

            with c42:
                link_14_2_1_input = st.text_area(
                    "Link/Evidência (Série histórica compactada ou telas consolidadas de auditoria do absenteísmo):",
                    value=l_salvo_14_2_1,
                    key=f"txt_saude_14_2_1_{ano_sel}",
                    height=150
                )

                if val_ta2 > 0 or val_ta1 > 0:
                    st.markdown(f"📈 *Média dos 2 anos anteriores ({ano_sel-2}/{ano_sel-1}): `{media_dois_anos:.2f}%`*")

                links_14_2_1_visuais = re.findall(REGEX_PURE_URL, link_14_2_1_input or "")
                if links_14_2_1_visuais:
                    st.markdown(
                        "**🔗 Links ativos:** "
                        + " | ".join(
                            [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_14_2_1_visuais]
                        )
                    )

            # Comentários
            bloco_comentarios_isaude("14.2.1", res_data)

            # Botão de salvamento
            if st.button("💾 Salvar Quesito 14.2.1", key=f"btn_salvar_14_2_1_{ano_sel}", type="primary"):
                val_lk_14_2_1 = link_14_2_1_input.strip()
                comentarios_14_2_1 = d14_2_1_main.get("comentarios", [])
                texto_main_valor = f"TA {val_ta}% (Média: {media_dois_anos:.2f}%)"

                # Persistência das subchaves numéricas e chave principal
                save_resp_isaude(qid="14.2.1_ta2", valor=str(val_ta2), pontos=pts_14_2_1, link="", comentarios=[])
                save_resp_isaude(qid="14.2.1_ta1", valor=str(val_ta1), pontos=0.0, link="", comentarios=[])
                save_resp_isaude(qid="14.2.1_ta", valor=str(val_ta), pontos=0.0, link="", comentarios=[])
                save_resp_isaude(qid="14.2.1", valor=texto_main_valor, pontos=pts_14_2_1, link=val_lk_14_2_1, comentarios=comentarios_14_2_1)

                # Modal de verificação de links
                links_atuais_14_2_1 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_14_2_1_input or "")]
                links_antigos_14_2_1 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_14_2_1 or "")]

                if val_lk_14_2_1 != l_salvo_14_2_1 and links_atuais_14_2_1 and links_atuais_14_2_1 != links_antigos_14_2_1:
                    st.session_state[f"links_pendentes_14_2_1_{ano_sel}"] = links_atuais_14_2_1
                    st.session_state[f"gatilho_modal_14_2_1_{ano_sel}"] = True

                st.cache_data.clear()
                st.toast("Resposta e histórico do Quesito 14.2.1 salvos com sucesso!", icon="✅")
                st.rerun()

            # Impacto de pontuação
            pts_atuais_14_2_1 = d14_2_1_main.get("pontos", 0.0)
            cor_txt_14_2_1 = "#28a745" if pts_atuais_14_2_1 > 0.0 else "#6c757d"
            st.markdown(
                f"<span style='color:{cor_txt_14_2_1}; font-weight:bold;'>"
                f"📊 Pontuação Obtida no Quesito 14.2.1: +{pts_atuais_14_2_1:.1f} / 10.0 pontos</span>",
                unsafe_allow_html=True,
            )

        # GATILHO DO MODAL 14.2.1 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_14_2_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("14.2.1", st.session_state.get(f"links_pendentes_14_2_1_{ano_sel}", []), ano_sel)

        # =============================================================================
        # QUESITO 14.2.2 • MEDIDAS PARA REDUÇÃO DO ABSENTEÍSMO
        # =============================================================================
        with st.container(key=f"container_filho_14_2_2_{ano_sel}", border=True):
            st.subheader(f"14.2.2 • Medidas para Redução do Absenteísmo ({ano_sel})")
            st.write(f"**O município realiza medidas para a redução desta taxa de absenteísmo em {ano_sel}?**")
            st.caption("ℹ️ *Selecione a opção, preencha as evidências e clique no botão 'Salvar Quesito 14.2.2' para registrar.*")

            opts_14_2_2 = {
                "Selecione...": 0.0,
                "Sim – 00": 0.0,
                "Não – -02": -2.0
            }

            # Recupera os dados atuais salvos no banco
            d14_2_2 = res_data.get("14.2.2") or {
                "valor": "Selecione...",
                "pontos": 0.0,
                "link": "",
                "comentarios": [],
                "comentario": ""
            }
            v_salvo_14_2_2 = d14_2_2.get("valor", "Selecione...")
            l_salvo_14_2_2 = d14_2_2.get("link", "")

            c43, c44 = st.columns([1, 1])

            with c43:
                idx_14_2_2 = list(opts_14_2_2.keys()).index(v_salvo_14_2_2) if v_salvo_14_2_2 in opts_14_2_2 else 0
                sel_14_2_2 = st.radio(
                    "Alternativas para o quesito 14.2.2:",
                    options=list(opts_14_2_2.keys()),
                    index=idx_14_2_2,
                    key=f"rb_saude_14_2_2_{ano_sel}",
                    label_visibility="collapsed"
                )

            with c44:
                link_14_2_2_input = st.text_area(
                    "Link/Evidência (Planos de ação, campanhas de conscientização, normativas de remanejamento de vagas ou relatórios das ações efetuadas):",
                    value=l_salvo_14_2_2,
                    key=f"txt_saude_14_2_2_{ano_sel}",
                    height=90
                )

                links_14_2_2_visuais = re.findall(REGEX_PURE_URL, link_14_2_2_input or "")
                if links_14_2_2_visuais:
                    st.markdown(
                        "**🔗 Links ativos:** "
                        + " | ".join(
                            [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_14_2_2_visuais]
                        )
                    )

            # Chat de comentários
            bloco_comentarios_isaude("14.2.2", res_data)

            # Botão de salvamento dedicado
            if st.button("💾 Salvar Quesito 14.2.2", key=f"btn_salvar_14_2_2_{ano_sel}", type="primary"):
                val_sel_14_2_2 = sel_14_2_2 if sel_14_2_2 is not None else "Selecione..."
                val_lk_14_2_2 = link_14_2_2_input.strip()
                pts_14_2_2 = opts_14_2_2.get(val_sel_14_2_2, 0.0)
                comentarios_14_2_2 = d14_2_2.get("comentarios", [])

                save_resp_isaude(
                    qid="14.2.2",
                    valor=val_sel_14_2_2,
                    pontos=pts_14_2_2,
                    link=val_lk_14_2_2,
                    comentarios=comentarios_14_2_2
                )

                # Modal de aviso para links pendentes
                links_atuais_14_2_2 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_14_2_2_input or "")]
                links_antigos_14_2_2 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_14_2_2 or "")]

                if (val_sel_14_2_2 != v_salvo_14_2_2 or val_lk_14_2_2 != l_salvo_14_2_2) and links_atuais_14_2_2 and links_atuais_14_2_2 != links_antigos_14_2_2:
                    st.session_state[f"links_pendentes_14_2_2_{ano_sel}"] = links_atuais_14_2_2
                    st.session_state[f"gatilho_modal_14_2_2_{ano_sel}"] = True

                st.cache_data.clear()
                st.toast("Resposta e histórico do Quesito 14.2.2 salvos com sucesso!", icon="✅")
                st.rerun()

            # Impacto de pontuação
            pts_atuais_14_2_2 = d14_2_2.get("pontos", 0.0)
            cor_txt_14_2_2 = "#dc3545" if pts_atuais_14_2_2 < 0.0 else "#28a745"

            st.markdown(
                f"<span style='color:{cor_txt_14_2_2}; font-weight:bold;'>"
                f"📊 Pontuação Obtida no Quesito 14.2.2 (Penalidade): {pts_atuais_14_2_2:.1f} pontos</span>",
                unsafe_allow_html=True,
            )

        # GATILHO DO MODAL 14.2.2 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_14_2_2_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("14.2.2", st.session_state.get(f"links_pendentes_14_2_2_{ano_sel}", []), ano_sel)

        # =============================================================================
        # QUESITO 14.2.2.1 • SELEÇÃO DE MEDIDAS APLICADAS (MÚLTIPLA ESCOLHA)
        # =============================================================================
        with st.container(key=f"container_sub_filho_14_2_2_1_{ano_sel}", border=True):
            st.subheader(f"14.2.2.1 • Medidas Aplicadas para Redução ({ano_sel})")
            st.write(f"**Assinale as medidas utilizadas para a redução da taxa de absenteísmo de consultas médicas na Atenção Básica em {ano_sel}:**")
            st.caption("ℹ️ *Selecione as opções desejadas, preencha as evidências e clique no botão 'Salvar Quesito 14.2.2.1' para registrar.*")

            # Recupera dados salvos no banco (espera um JSON em string)
            d14_2_2_1 = res_data.get("14.2.2.1") or {
                "valor": "[]",
                "pontos": 0.0,
                "link": "",
                "comentarios": [],
                "comentario": ""
            }
            try:
                salvos_14_2_2_1 = json.loads(d14_2_2_1.get("valor", "[]"))
            except Exception:
                salvos_14_2_2_1 = []

            l_salvo_14_2_2_1 = d14_2_2_1.get("link", "")

            c45, c46 = st.columns([1, 1])

            with c45:
                chk_m1 = st.checkbox(
                    "Informar e sensibilizar as equipes/profissionais a respeito do absenteísmo e promover capacitações",
                    value="m1" in salvos_14_2_2_1,
                    key=f"chk_14_221_m1_{ano_sel}"
                )
                chk_m2 = st.checkbox(
                    "Criação de Central de relacionamento para usuário SUS, com disponibilização de canal direto de comunicação",
                    value="m2" in salvos_14_2_2_1,
                    key=f"chk_14_221_m2_{ano_sel}"
                )
                chk_m3 = st.checkbox(
                    "Ligação telefônica ou outro meio de comunicação para confirmação da consulta e presença do paciente",
                    value="m3" in salvos_14_2_2_1,
                    key=f"chk_14_221_m3_{ano_sel}"
                )
                chk_m4 = st.checkbox(
                    "Orientação das famílias e busca ativa dos faltosos pelos Agentes Comunitários de Saúde (ACS)",
                    value="m4" in salvos_14_2_2_1,
                    key=f"chk_14_221_m4_{ano_sel}"
                )
                chk_m5 = st.checkbox(
                    "Promoção de campanhas de conscientização",
                    value="m5" in salvos_14_2_2_1,
                    key=f"chk_14_221_m5_{ano_sel}"
                )
                chk_m6 = st.checkbox(
                    "Outros",
                    value="m6" in salvos_14_2_2_1,
                    key=f"chk_14_221_m6_{ano_sel}"
                )

                # Monta a lista de medidas selecionadas
                medidas_selecionadas = []
                if chk_m1: medidas_selecionadas.append("m1")
                if chk_m2: medidas_selecionadas.append("m2")
                if chk_m3: medidas_selecionadas.append("m3")
                if chk_m4: medidas_selecionadas.append("m4")
                if chk_m5: medidas_selecionadas.append("m5")
                if chk_m6: medidas_selecionadas.append("m6")

            with c46:
                link_14_2_2_1_input = st.text_area(
                    "Link/Evidência (Cópias de portarias das rotinas, materiais de campanhas, relatórios de ligações da Central ou registros de busca ativa dos ACS):",
                    value=l_salvo_14_2_2_1,
                    key=f"txt_saude_14_2_2_1_{ano_sel}",
                    height=210
                )

                links_14_2_2_1_visuais = re.findall(REGEX_PURE_URL, link_14_2_2_1_input or "")
                if links_14_2_2_1_visuais:
                    st.markdown(
                        "**🔗 Links ativos:** "
                        + " | ".join(
                            [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_14_2_2_1_visuais]
                        )
                    )

            # Chat de comentários
            bloco_comentarios_isaude("14.2.2.1", res_data)

            # Botão de salvamento dedicado
            if st.button("💾 Salvar Quesito 14.2.2.1", key=f"btn_salvar_14_2_2_1_{ano_sel}", type="primary"):
                str_14_2_2_1_val = json.dumps(medidas_selecionadas)
                val_lk_14_2_2_1 = link_14_2_2_1_input.strip()
                comentarios_14_2_2_1 = d14_2_2_1.get("comentarios", [])

                save_resp_isaude(
                    qid="14.2.2.1",
                    valor=str_14_2_2_1_val,
                    pontos=0.0,
                    link=val_lk_14_2_2_1,
                    comentarios=comentarios_14_2_2_1
                )

                # Modal de aviso para links pendentes
                links_atuais_14_2_2_1 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_14_2_2_1_input or "")]
                links_antigos_14_2_2_1 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_14_2_2_1 or "")]

                if (str_14_2_2_1_val != d14_2_2_1.get("valor", "[]") or val_lk_14_2_2_1 != l_salvo_14_2_2_1) and links_atuais_14_2_2_1 and links_atuais_14_2_2_1 != links_antigos_14_2_2_1:
                    st.session_state[f"links_pendentes_14_2_2_1_{ano_sel}"] = links_atuais_14_2_2_1
                    st.session_state[f"gatilho_modal_14_2_2_1_{ano_sel}"] = True

                st.cache_data.clear()
                st.toast("Resposta e histórico do Quesito 14.2.2.1 salvos com sucesso!", icon="✅")
                st.rerun()

        # GATILHO DO MODAL 14.2.2.1 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_14_2_2_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("14.2.2.1", st.session_state.get(f"links_pendentes_14_2_2_1_{ano_sel}", []), ano_sel)

        # =============================================================================
        # QUESITO 15.0 • CONTROLE DE ABSENTEÍSMO PARA EXAMES LABORATORIAIS
        # =============================================================================
        with st.container(key=f"card_absenteismo_exames_root_{ano_sel}", border=True):
            with st.expander(f"🧪 QUESITO 15.0 • Controle de Absenteísmo para Exames Laboratoriais em {ano_sel}", expanded=True):
                st.subheader(f"15.0 • Absenteísmo em Exames Laboratoriais ({ano_sel})")
                st.write(f"**A Prefeitura Municipal possui controle de absenteísmo para os exames laboratoriais realizados sob sua gestão em {ano_sel}?**")
                st.caption("ℹ️ *Exemplos de exames laboratoriais: triglicérides, colesterol total e frações, hemograma, glicemia em jejum, hemoglobina glicada e controle de eletrólitos.*")
                st.caption("ℹ️ *Selecione a opção, preencha as evidências e clique no botão 'Salvar Quesito 15.0' para registrar.*")

                opts_15_0 = {
                    "Selecione...": 0.0,
                    "Todos os exames laboratoriais são de pronto atendimento – 02": 2.0,
                    "Sim, para todos os exames – 02": 2.0,
                    "Sim, para a maior parte dos exames – 01": 1.0,
                    "Sim, para a menor parte dos exames – 0.5": 0.5,
                    "Não – 00": 0.0
                }

                # Recupera os dados atuais salvos no banco
                d15_0 = res_data.get("15.0") or {
                    "valor": "Selecione...",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_15_0 = d15_0.get("valor", "Selecione...")
                l_salvo_15_0 = d15_0.get("link", "")

                c47, c48 = st.columns([1, 1])

                with c47:
                    idx_15_0 = list(opts_15_0.keys()).index(v_salvo_15_0) if v_salvo_15_0 in opts_15_0 else 0
                    sel_15_0 = st.radio(
                        "Alternativas para o quesito 15.0:",
                        options=list(opts_15_0.keys()),
                        index=idx_15_0,
                        key=f"rb_saude_15_0_{ano_sel}",
                        label_visibility="collapsed"
                    )

                with c48:
                    link_15_0_input = st.text_area(
                        "Link/Evidência (Relatórios do sistema de regulação de exames ou mapas de faltas gerados pelo laboratório municipal/conveniado):",
                        value=l_salvo_15_0,
                        key=f"txt_saude_15_0_{ano_sel}",
                        height=110
                    )

                    links_15_0_visuais = re.findall(REGEX_PURE_URL, link_15_0_input or "")
                    if links_15_0_visuais:
                        st.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_15_0_visuais]
                            )
                        )

                # Chat de comentários
                bloco_comentarios_isaude("15.0", res_data)

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 15.0", key=f"btn_salvar_15_0_{ano_sel}", type="primary"):
                    val_sel_15_0 = sel_15_0 if sel_15_0 is not None else "Selecione..."
                    val_lk_15_0 = link_15_0_input.strip()
                    pts_15_0 = opts_15_0.get(val_sel_15_0, 0.0)
                    comentarios_15_0 = d15_0.get("comentarios", [])

                    save_resp_isaude(
                        qid="15.0",
                        valor=val_sel_15_0,
                        pontos=pts_15_0,
                        link=val_lk_15_0,
                        comentarios=comentarios_15_0
                    )

                    # Modal de aviso para links pendentes
                    links_atuais_15_0 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_15_0_input or "")]
                    links_antigos_15_0 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_15_0 or "")]

                    if (val_sel_15_0 != v_salvo_15_0 or val_lk_15_0 != l_salvo_15_0) and links_atuais_15_0 and links_atuais_15_0 != links_antigos_15_0:
                        st.session_state[f"links_pendentes_15_0_{ano_sel}"] = links_atuais_15_0
                        st.session_state[f"gatilho_modal_15_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 15.0 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                pts_atuais_15_0 = d15_0.get("pontos", 0.0)
                cor_txt_15_0 = "#28a745" if pts_atuais_15_0 > 0.0 else "#6c757d"

                st.markdown(
                    f"<span style='color:{cor_txt_15_0}; font-weight:bold;'>"
                    f"📊 Pontuação Obtida no Quesito 15.0: +{pts_atuais_15_0:.1f} pontos</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 15.0 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_15_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("15.0", st.session_state.get(f"links_pendentes_15_0_{ano_sel}", []), ano_sel)

        # =============================================================================
        # QUESITO 15.1 • TAXA HISTÓRICA DE ABSENTEÍSMO DE EXAMES
        # =============================================================================
        with st.container(key=f"card_absenteismo_exames_15_1_{ano_sel}", border=True):
            with st.expander(f"📊 QUESITO 15.1 • Taxa Histórica de Absenteísmo de Exames ({ano_sel})", expanded=True):
                st.subheader(f"15.1 • Indicadores de Faltas em Exames ({ano_sel})")
                st.write(f"**Informe a taxa de absenteísmo de exames laboratoriais na Atenção Básica (em %):**")
                st.caption("ℹ️ *Preencha os dados abaixo, adicione as evidências e clique no botão 'Salvar Quesito 15.1' para registrar.*")

                d15_1_ta2 = res_data.get("15.1_ta2", {"valor": "0.0", "pontos": 0.0, "link": "", "comentarios": []})
                d15_1_ta1 = res_data.get("15.1_ta1", {"valor": "0.0", "pontos": 0.0, "link": "", "comentarios": []})
                d15_1_ta  = res_data.get("15.1_ta",  {"valor": "0.0", "pontos": 0.0, "link": "", "comentarios": []})
                d15_1     = res_data.get("15.1",     {"valor": "", "pontos": 0.0, "link": "", "comentarios": []})

                v_ta2_salvo = float(d15_1_ta2.get("valor", 0.0))
                v_ta1_salvo = float(d15_1_ta1.get("valor", 0.0))
                v_ta_salvo  = float(d15_1_ta.get("valor", 0.0))
                l_salvo_15_1 = d15_1.get("link", "")

                c49, c50 = st.columns([1, 1])
                with c49:
                    val_ex_ta2 = st.number_input(
                        f"Taxa de absenteísmo em exames em {ano_sel - 2} (TA-2):",
                        min_value=0.0, max_value=100.0, step=0.1,
                        value=v_ta2_salvo,
                        key=f"num_15_1_ta2_{ano_sel}"
                    )
                    val_ex_ta1 = st.number_input(
                        f"Taxa de absenteísmo em exames em {ano_sel - 1} (TA-1):",
                        min_value=0.0, max_value=100.0, step=0.1,
                        value=v_ta1_salvo,
                        key=f"num_15_1_ta1_{ano_sel}"
                    )
                    val_ex_ta = st.number_input(
                        f"Taxa de absenteísmo em exames em {ano_sel} (TA):",
                        min_value=0.0, max_value=100.0, step=0.1,
                        value=v_ta_salvo,
                        key=f"num_15_1_ta_{ano_sel}"
                    )

                media_ex_dois_anos = (val_ex_ta2 + val_ex_ta1) / 2.0

                with c50:
                    link_15_1_input = st.text_area(
                        "Link/Evidência (Séries estatísticas históricas, consolidados de agendamentos solicitados x não comparecidos):",
                        value=l_salvo_15_1,
                        key=f"txt_saude_15_1_{ano_sel}",
                        height=150
                    )

                    links_15_1_visuais = re.findall(REGEX_PURE_URL, link_15_1_input or "")
                    if links_15_1_visuais:
                        st.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_15_1_visuais]
                            )
                        )

                    if val_ex_ta2 > 0 or val_ex_ta1 > 0:
                        st.markdown(f"**Média dos 2 anos anteriores ({ano_sel-2}/{ano_sel-1}):** `{media_ex_dois_anos:.2f}%`")

                # Chat de comentários
                bloco_comentarios_isaude("15.1", res_data)

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 15.1", key=f"btn_salvar_15_1_{ano_sel}", type="primary"):
                    if val_ex_ta <= media_ex_dois_anos and (val_ex_ta2 > 0 or val_ex_ta1 > 0):
                        pts_15_1 = 7.0
                    else:
                        pts_15_1 = 0.0

                    str_mestre = f"TA Exames {val_ex_ta}% (Média: {media_ex_dois_anos:.2f}%)"
                    val_lk_15_1 = link_15_1_input.strip()
                    comentarios_15_1 = d15_1.get("comentarios", [])

                    # Grava sub-chaves e quesito principal
                    save_resp_isaude("15.1_ta2", str(val_ex_ta2), pts_15_1, "")
                    save_resp_isaude("15.1_ta1", str(val_ex_ta1), 0.0, "")
                    save_resp_isaude("15.1_ta", str(val_ex_ta), 0.0, "")
                    save_resp_isaude("15.1", str_mestre, pts_15_1, val_lk_15_1, comentarios=comentarios_15_1)

                    # Modal de aviso para links pendentes
                    links_atuais_15_1 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_15_1_input or "")]
                    links_antigos_15_1 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_15_1 or "")]

                    mudou_valores = (val_ex_ta2 != v_ta2_salvo or val_ex_ta1 != v_ta1_salvo or val_ex_ta != v_ta_salvo)
                    if (mudou_valores or val_lk_15_1 != l_salvo_15_1) and links_atuais_15_1 and links_atuais_15_1 != links_antigos_15_1:
                        st.session_state[f"links_pendentes_15_1_{ano_sel}"] = links_atuais_15_1
                        st.session_state[f"gatilho_modal_15_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 15.1 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                pts_atuais_15_1 = d15_1.get("pontos", 0.0)
                cor_txt_15_1 = "#28a745" if pts_atuais_15_1 > 0.0 else "#6c757d"

                st.markdown(
                    f"<span style='color:{cor_txt_15_1}; font-weight:bold;'>"
                    f"📊 Pontuação Obtida no Quesito 15.1: {pts_atuais_15_1:.1f} / 7.0 pontos</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 15.1 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_15_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("15.1", st.session_state.get(f"links_pendentes_15_1_{ano_sel}", []), ano_sel)

        # =============================================================================
        # QUESITO 15.2 • MEDIDAS PARA REDUÇÃO DO ABSENTEÍSMO DE EXAMES
        # =============================================================================
        with st.container(key=f"card_medidas_exames_15_2_{ano_sel}", border=True):
            with st.expander(f"🛡️ QUESITO 15.2 • Medidas Institucionais para Exames ({ano_sel})", expanded=True):
                st.subheader(f"15.2 • Enfrentamento do Absenteísmo em Exames ({ano_sel})")
                st.write(f"**O município realiza medidas para a redução desta taxa de absenteísmo de exames laboratoriais em {ano_sel}?**")
                st.caption("ℹ️ *Selecione a opção, preencha as evidências e clique no botão 'Salvar Quesito 15.2' para registrar.*")

                opts_15_2 = {
                    "Selecione...": 0.0,
                    "Sim – 00": 0.0,
                    "Não – -02": -2.0
                }

                # Recupera dados atuais salvos na base
                d15_2 = res_data.get("15.2") or {
                    "valor": "Selecione...",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_15_2 = d15_2.get("valor", "Selecione...")
                l_salvo_15_2 = d15_2.get("link", "")

                c51, c52 = st.columns([1, 1])

                with c51:
                    idx_15_2 = list(opts_15_2.keys()).index(v_salvo_15_2) if v_salvo_15_2 in opts_15_2 else 0
                    sel_15_2 = st.radio(
                        "Alternativas para o quesito 15.2:",
                        options=list(opts_15_2.keys()),
                        index=idx_15_2,
                        key=f"rb_saude_15_2_exames_{ano_sel}",
                        label_visibility="collapsed"
                    )

                with c52:
                    link_15_2_input = st.text_area(
                        "Link/Evidência (Planos de ação ou diretrizes para redução do absenteísmo de exames):",
                        value=l_salvo_15_2,
                        key=f"txt_saude_15_2_exames_{ano_sel}",
                        height=90
                    )

                    links_15_2_visuais = re.findall(REGEX_PURE_URL, link_15_2_input or "")
                    if links_15_2_visuais:
                        st.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_15_2_visuais]
                            )
                        )

                # Chat de comentários
                bloco_comentarios_isaude("15.2", res_data)

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 15.2", key=f"btn_salvar_15_2_{ano_sel}", type="primary"):
                    val_sel_15_2 = sel_15_2 if sel_15_2 is not None else "Selecione..."
                    val_lk_15_2 = link_15_2_input.strip()
                    pts_15_2 = opts_15_2.get(val_sel_15_2, 0.0)
                    comentarios_15_2 = d15_2.get("comentarios", [])

                    save_resp_isaude(
                        qid="15.2",
                        valor=val_sel_15_2,
                        pontos=pts_15_2,
                        link=val_lk_15_2,
                        comentarios=comentarios_15_2
                    )

                    # Modal de aviso para links pendentes
                    links_atuais_15_2 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_15_2_input or "")]
                    links_antigos_15_2 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_15_2 or "")]

                    if (val_sel_15_2 != v_salvo_15_2 or val_lk_15_2 != l_salvo_15_2) and links_atuais_15_2 and links_atuais_15_2 != links_antigos_15_2:
                        st.session_state[f"links_pendentes_15_2_{ano_sel}"] = links_atuais_15_2
                        st.session_state[f"gatilho_modal_15_2_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 15.2 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                pts_atuais_15_2 = d15_2.get("pontos", 0.0)
                cor_txt_15_2 = "#dc3545" if pts_atuais_15_2 < 0.0 else "#6c757d"

                st.markdown(
                    f"<span style='color:{cor_txt_15_2}; font-weight:bold;'>"
                    f"📊 Pontuação Obtida no Quesito 15.2 (Penalidade): {pts_atuais_15_2:.1f} pontos</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 15.2 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_15_2_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("15.2", st.session_state.get(f"links_pendentes_15_2_{ano_sel}", []), ano_sel)

        # =============================================================================
        # QUESITO 15.2.1 • SELEÇÃO DE MEDIDAS APLICADAS PARA EXAMES
        # =============================================================================
        with st.container(key=f"card_medidas_aplicadas_exames_15_2_1_{ano_sel}", border=True):
            with st.expander(f"📋 QUESITO 15.2.1 • Rol de Medidas em Exames Laboratoriais em {ano_sel}", expanded=True):
                st.subheader(f"15.2.1 • Ações Preventivas e de Confirmação ({ano_sel})")
                st.write(f"**Assinale as medidas utilizadas para a redução da taxa de absenteísmo de exames médicos na Atenção Básica em {ano_sel}:**")
                st.caption("ℹ️ *Selecione as opções desejadas, preencha as evidências e clique no botão 'Salvar Quesito 15.2.1' para registrar.*")

                d15_2_1 = res_data.get("15.2.1") or {
                    "valor": "[]",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                try:
                    salvos_15_2_1 = json.loads(d15_2_1.get("valor", "[]"))
                except Exception:
                    salvos_15_2_1 = []

                l_salvo_15_2_1 = d15_2_1.get("link", "")

                c53, c54 = st.columns([1, 1])
                with c53:
                    chk_ex_m1 = st.checkbox(
                        "Informar e sensibilizar as equipes/profissionais a respeito do absenteísmo e promover capacitações",
                        value="ex_m1" in salvos_15_2_1,
                        key=f"chk_15_2_1_m1_ex_{ano_sel}"
                    )
                    chk_ex_m2 = st.checkbox(
                        "Criação de Central de relacionamento para usuário SUS, com disponibilização de canal direto de comunicação",
                        value="ex_m2" in salvos_15_2_1,
                        key=f"chk_15_2_1_m2_ex_{ano_sel}"
                    )
                    chk_ex_m3 = st.checkbox(
                        "Ligação telefônica ou outro meio de comunicação para confirmação do exame e presença do paciente",
                        value="ex_m3" in salvos_15_2_1,
                        key=f"chk_15_2_1_m3_ex_{ano_sel}"
                    )
                    chk_ex_m4 = st.checkbox(
                        "Orientação das famílias e busca ativa dos faltosos pelos Agentes Comunitários de Saúde (ACS)",
                        value="ex_m4" in salvos_15_2_1,
                        key=f"chk_15_2_1_m4_ex_{ano_sel}"
                    )
                    chk_ex_m5 = st.checkbox(
                        "Promoção de campanhas de conscientização",
                        value="ex_m5" in salvos_15_2_1,
                        key=f"chk_15_2_1_m5_ex_{ano_sel}"
                    )
                    chk_ex_m6 = st.checkbox(
                        "Outros",
                        value="ex_m6" in salvos_15_2_1,
                        key=f"chk_15_2_1_m6_ex_{ano_sel}"
                    )

                    medidas_ex_selecionadas = []
                    if chk_ex_m1: medidas_ex_selecionadas.append("ex_m1")
                    if chk_ex_m2: medidas_ex_selecionadas.append("ex_m2")
                    if chk_ex_m3: medidas_ex_selecionadas.append("ex_m3")
                    if chk_ex_m4: medidas_ex_selecionadas.append("ex_m4")
                    if chk_ex_m5: medidas_ex_selecionadas.append("ex_m5")
                    if chk_ex_m6: medidas_ex_selecionadas.append("ex_m6")

                with c54:
                    link_15_2_1_input = st.text_area(
                        "Link/Evidência (Comprovantes de rotinas de confirmação, campanhas, prints de sistemas de comunicação ou relatórios das centrais de exames):",
                        value=l_salvo_15_2_1,
                        key=f"txt_saude_15_2_1_exames_{ano_sel}",
                        height=210
                    )

                    links_15_2_1_visuais = re.findall(REGEX_PURE_URL, link_15_2_1_input or "")
                    if links_15_2_1_visuais:
                        st.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_15_2_1_visuais]
                            )
                        )

                # Chat de comentários
                bloco_comentarios_isaude("15.2.1", res_data)

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 15.2.1", key=f"btn_salvar_15_2_1_{ano_sel}", type="primary"):
                    str_15_2_1_val = json.dumps(medidas_ex_selecionadas)
                    val_lk_15_2_1 = link_15_2_1_input.strip()
                    comentarios_15_2_1 = d15_2_1.get("comentarios", [])

                    save_resp_isaude(
                        qid="15.2.1",
                        valor=str_15_2_1_val,
                        pontos=0.0,
                        link=val_lk_15_2_1,
                        comentarios=comentarios_15_2_1
                    )

                    # Modal de aviso para links pendentes
                    links_atuais_15_2_1 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_15_2_1_input or "")]
                    links_antigos_15_2_1 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_15_2_1 or "")]

                    if (str_15_2_1_val != d15_2_1.get("valor", "[]") or val_lk_15_2_1 != l_salvo_15_2_1) and links_atuais_15_2_1 and links_atuais_15_2_1 != links_antigos_15_2_1:
                        st.session_state[f"links_pendentes_15_2_1_{ano_sel}"] = links_atuais_15_2_1
                        st.session_state[f"gatilho_modal_15_2_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 15.2.1 salvos com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 15.2.1 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_15_2_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("15.2.1", st.session_state.get(f"links_pendentes_15_2_1_{ano_sel}", []), ano_sel)

        # =============================================================================
        # QUESITO 16.0 • PRONTUÁRIO ELETRÔNICO NA ATENÇÃO BÁSICA
        # =============================================================================
        with st.container(key=f"container_bloco_pep_atencao_basica_16_0_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 16.0 - Prontuário Eletrônico na Atenção Básica ({ano_sel})", expanded=True):
                st.subheader(f"16.0 • Prontuário Eletrônico na Atenção Básica ({ano_sel})")
                st.write(f"**O município implantou o Prontuário Eletrônico do Paciente na Atenção Básica em {ano_sel}?**")
                st.caption("ℹ️ *Selecione a opção, preencha as evidências e clique no botão 'Salvar Quesito 16.0' para registrar.*")

                opts_16_0 = {
                    "Selecione...": 0.0,
                    "Sim, para todos os procedimentos da saúde – 10": 10.0,
                    "Sim, para a maior parte dos procedimentos da saúde – 07": 7.0,
                    "Sim, para a menor parte dos procedimentos da saúde – 03": 3.0,
                    "Não – 00": 0.0
                }

                d16_0 = res_data.get("16.0") or {
                    "valor": "Selecione...",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_16_0 = d16_0.get("valor", "Selecione...")
                l_salvo_16_0 = d16_0.get("link", "")

                c160_1, c160_2 = st.columns([1, 1])
                with c160_1:
                    lista_opcoes_16_0 = list(opts_16_0.keys())
                    idx_salvo_16_0 = lista_opcoes_16_0.index(v_salvo_16_0) if v_salvo_16_0 in opts_16_0 else 0

                    sel_16_0 = st.radio(
                        "Implantação do PEP:",
                        options=lista_opcoes_16_0,
                        index=idx_salvo_16_0,
                        key=f"r_16_0_{ano_sel}",
                        label_visibility="collapsed"
                    )

                with c160_2:
                    link_16_0_input = st.text_area(
                        "Link/Evidência (Contrato de software, relatórios de implantação do PEP ou telas do sistema em funcionamento):",
                        value=l_salvo_16_0,
                        key=f"t_16_0_{ano_sel}",
                        height=130
                    )

                    links_16_0_visuais = re.findall(REGEX_PURE_URL, link_16_0_input or "")
                    if links_16_0_visuais:
                        st.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_16_0_visuais]
                            )
                        )

                # Chat de comentários
                bloco_comentarios_isaude("16.0", res_data)

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 16.0", key=f"btn_salvar_16_0_{ano_sel}", type="primary"):
                    val_sel_16_0 = sel_16_0 if sel_16_0 is not None else "Selecione..."
                    val_lk_16_0 = link_16_0_input.strip()
                    pts_16_0 = opts_16_0.get(val_sel_16_0, 0.0)
                    comentarios_16_0 = d16_0.get("comentarios", [])

                    save_resp_isaude(
                        qid="16.0",
                        valor=val_sel_16_0,
                        pontos=pts_16_0,
                        link=val_lk_16_0,
                        comentarios=comentarios_16_0
                    )

                    # Modal de aviso para links pendentes
                    links_atuais_16_0 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_16_0_input or "")]
                    links_antigos_16_0 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_16_0 or "")]

                    if (val_sel_16_0 != v_salvo_16_0 or val_lk_16_0 != l_salvo_16_0) and links_atuais_16_0 and links_atuais_16_0 != links_antigos_16_0:
                        st.session_state[f"links_pendentes_16_0_{ano_sel}"] = links_atuais_16_0
                        st.session_state[f"gatilho_modal_16_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 16.0 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                pts_atuais_16_0 = d16_0.get("pontos", 0.0)
                cor_txt_16_0 = "#28a745" if pts_atuais_16_0 > 0.0 else "#6c757d"

                st.markdown(
                    f"<span style='color:{cor_txt_16_0}; font-weight:bold;'>"
                    f"📊 Pontuação Obtida no Quesito 16.0: +{pts_atuais_16_0:.1f} pontos</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 16.0 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_16_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("16.0", st.session_state.get(f"links_pendentes_16_0_{ano_sel}", []), ano_sel)

        # =============================================================================
        # QUESITO 16.1 • SERVIÇOS INSERIDOS NO PRONTUÁRIO ELETRÔNICO
        # =============================================================================
        with st.container(key=f"container_bloco_servicos_pep_16_1_{ano_sel}", border=True):
            with st.expander(f"📋 QUESITO 16.1 • Serviços Integrados ao Prontuário Eletrônico em {ano_sel}", expanded=True):
                st.subheader(f"16.1 • Escopo Funcional do PEP ({ano_sel})")
                st.write(f"**Assinale os serviços da Atenção Básica inseridos no Prontuário Eletrônico do Paciente em {ano_sel}:**")
                st.caption("ℹ️ *A pontuação deste quesito é cumulativa (1 ponto por serviço assinalado, exceto 'Outros').*")
                st.caption("ℹ️ *Selecione as opções desejadas, preencha as evidências e clique no botão 'Salvar Quesito 16.1' para registrar.*")

                d16_1 = res_data.get("16.1") or {
                    "valor": "[]",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                try:
                    salvos_16_1 = json.loads(d16_1.get("valor", "[]"))
                except Exception:
                    salvos_16_1 = []

                l_salvo_16_1 = d16_1.get("link", "")

                c57, c58 = st.columns([1, 1])
                with c57:
                    chk_pep1 = st.checkbox("Atendimento pela ESF – 01", value="pep1" in salvos_16_1, key=f"chk_16_1_pep1_{ano_sel}")
                    chk_pep2 = st.checkbox("Consultas médicas em Atenção Primária – 01", value="pep2" in salvos_16_1, key=f"chk_16_1_pep2_{ano_sel}")
                    chk_pep3 = st.checkbox("Exames laboratoriais – 01", value="pep3" in salvos_16_1, key=f"chk_16_1_pep3_{ano_sel}")
                    chk_pep4 = st.checkbox("Terapias / tratamentos – 01", value="pep4" in salvos_16_1, key=f"chk_16_1_pep4_{ano_sel}")
                    chk_pep5 = st.checkbox("Medicamentos – 01", value="pep5" in salvos_16_1, key=f"chk_16_1_pep5_{ano_sel}")
                    chk_pep6 = st.checkbox("Outros – 00", value="pep6" in salvos_16_1, key=f"chk_16_1_pep6_{ano_sel}")

                    # Cálculo dinâmico e cumulativo da pontuação
                    servicos_selecionados = []
                    pts_calculados_16_1 = 0.0

                    if chk_pep1:
                        servicos_selecionados.append("pep1")
                        pts_calculados_16_1 += 1.0
                    if chk_pep2:
                        servicos_selecionados.append("pep2")
                        pts_calculados_16_1 += 1.0
                    if chk_pep3:
                        servicos_selecionados.append("pep3")
                        pts_calculados_16_1 += 1.0
                    if chk_pep4:
                        servicos_selecionados.append("pep4")
                        pts_calculados_16_1 += 1.0
                    if chk_pep5:
                        servicos_selecionados.append("pep5")
                        pts_calculados_16_1 += 1.0
                    if chk_pep6:
                        servicos_selecionados.append("pep6")

                with c58:
                    link_16_1_input = st.text_area(
                        "Link/Evidência (Telas exemplares do PEP mostrando os módulos ativos de ESF, exames, receitas ou terapias):",
                        value=l_salvo_16_1,
                        key=f"txt_saude_16_1_pep_{ano_sel}",
                        height=210
                    )

                    links_16_1_visuais = re.findall(REGEX_PURE_URL, link_16_1_input or "")
                    if links_16_1_visuais:
                        st.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_16_1_visuais]
                            )
                        )

                # Chat de comentários
                bloco_comentarios_isaude("16.1", res_data)

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 16.1", key=f"btn_salvar_16_1_{ano_sel}", type="primary"):
                    str_16_1_val = json.dumps(servicos_selecionados)
                    val_lk_16_1 = link_16_1_input.strip()
                    comentarios_16_1 = d16_1.get("comentarios", [])

                    save_resp_isaude(
                        qid="16.1",
                        valor=str_16_1_val,
                        pontos=pts_calculados_16_1,
                        link=val_lk_16_1,
                        comentarios=comentarios_16_1
                    )

                    # Modal de aviso para links pendentes
                    links_atuais_16_1 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_16_1_input or "")]
                    links_antigos_16_1 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_16_1 or "")]

                    if (str_16_1_val != d16_1.get("valor", "[]") or val_lk_16_1 != l_salvo_16_1) and links_atuais_16_1 and links_atuais_16_1 != links_antigos_16_1:
                        st.session_state[f"links_pendentes_16_1_{ano_sel}"] = links_atuais_16_1
                        st.session_state[f"gatilho_modal_16_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 16.1 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                pts_atuais_16_1 = d16_1.get("pontos", 0.0)
                cor_txt_16_1 = "#28a745" if pts_atuais_16_1 > 0.0 else "#6c757d"

                st.markdown(
                    f"<span style='color:{cor_txt_16_1}; font-weight:bold;'>"
                    f"📊 Pontuação Obtida no Quesito 16.1: +{pts_atuais_16_1:.1f} pontos</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 16.1 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_16_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("16.1", st.session_state.get(f"links_pendentes_16_1_{ano_sel}", []), ano_sel)

        # =============================================================================
        # QUESITO 17.0 • ATENÇÃO ESPECIALIZADA
        # =============================================================================
        with st.container(key=f"container_bloco_especializada_17_0_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 17.0 - Atendimento de Atenção Especializada ({ano_sel})", expanded=True):
                st.subheader(f"17.0 • Atenção Especializada ({ano_sel})")
                st.write(f"**O município possui atendimento de Atenção Especializada (média e/ou alta complexidade) em {ano_sel}?**")
                st.caption("ℹ️ *Selecione a opção, preencha as evidências e clique no botão 'Salvar Quesito 17.0' para registrar.*")

                opts_17_0 = {
                    "Selecione...": 0.0,
                    "Sim, sob gestão municipal": 0.0,
                    "Sim, sob gestão estadual": 0.0,
                    "Sim, sob gestão municipal e sob gestão estadual": 0.0,
                    "Não, somente encaminhamento para outro município": 0.0
                }

                d17_0 = res_data.get("17.0") or {
                    "valor": "Selecione...",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_17_0 = d17_0.get("valor", "Selecione...")
                l_salvo_17_0 = d17_0.get("link", "")

                c170_1, c170_2 = st.columns([1, 1])
                with c170_1:
                    lista_opcoes_17_0 = list(opts_17_0.keys())
                    idx_salvo_17_0 = lista_opcoes_17_0.index(v_salvo_17_0) if v_salvo_17_0 in opts_17_0 else 0

                    sel_17_0 = st.radio(
                        "Gestão da Atenção Especializada:",
                        options=lista_opcoes_17_0,
                        index=idx_salvo_17_0,
                        key=f"r_17_0_{ano_sel}",
                        label_visibility="collapsed"
                    )

                with c170_2:
                    link_17_0_input = st.text_area(
                        "Link/Evidência Geral (17.0):",
                        value=l_salvo_17_0,
                        key=f"t_17_0_{ano_sel}",
                        height=130
                    )

                    links_17_0_visuais = re.findall(REGEX_PURE_URL, link_17_0_input or "")
                    if links_17_0_visuais:
                        st.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_17_0_visuais]
                            )
                        )

                # Chat de comentários
                bloco_comentarios_isaude("17.0", res_data)

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 17.0", key=f"btn_salvar_17_0_{ano_sel}", type="primary"):
                    val_sel_17_0 = sel_17_0 if sel_17_0 is not None else "Selecione..."
                    val_lk_17_0 = link_17_0_input.strip()
                    pts_17_0 = opts_17_0.get(val_sel_17_0, 0.0)
                    comentarios_17_0 = d17_0.get("comentarios", [])

                    save_resp_isaude(
                        qid="17.0",
                        valor=val_sel_17_0,
                        pontos=pts_17_0,
                        link=val_lk_17_0,
                        comentarios=comentarios_17_0
                    )

                    # Modal de aviso para links pendentes
                    links_atuais_17_0 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_17_0_input or "")]
                    links_antigos_17_0 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_17_0 or "")]

                    if (val_sel_17_0 != v_salvo_17_0 or val_lk_17_0 != l_salvo_17_0) and links_atuais_17_0 and links_atuais_17_0 != links_antigos_17_0:
                        st.session_state[f"links_pendentes_17_0_{ano_sel}"] = links_atuais_17_0
                        st.session_state[f"gatilho_modal_17_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 17.0 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                pts_atuais_17_0 = d17_0.get("pontos", 0.0)
                cor_txt_17_0 = "#28a745" if pts_atuais_17_0 >= 0.0 else "#dc3545"

                st.markdown(
                    f"<span style='color:{cor_txt_17_0}; font-weight:bold;'>"
                    f"📊 Pontuação Obtida no Quesito 17.0: {pts_atuais_17_0:+.1f} pontos</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 17.0
        if st.session_state.get(f"gatilho_modal_17_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("17.0", st.session_state.get(f"links_pendentes_17_0_{ano_sel}", []), ano_sel)


        # =============================================================================
        # QUESITO 17.1 • FREQUÊNCIA ELETRÔNICA NA ATENÇÃO ESPECIALIZADA
        # =============================================================================
        with st.container(key=f"container_bloco_frequencia_17_1_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 17.1 - Frequência Eletrônica na Atenção Especializada ({ano_sel})", expanded=True):
                st.subheader(f"17.1 • Controle de Frequência Eletrônica ({ano_sel})")
                st.write(f"**Os profissionais de saúde da Atenção Especializada sob gestão municipal registram sua frequência de forma eletrônica em {ano_sel}?**")
                st.caption("⚠️ *Obs. O encaminhamento de planilhas de ponto não será considerado como modalidade de registro eletrônico.*")
                st.caption("ℹ️ *Selecione a opção, preencha as evidências e clique no botão 'Salvar Quesito 17.1' para registrar.*")

                opts_17_1 = {
                    "Selecione...": 0.0,
                    "Sim, para todos os profissionais da saúde – 00": 0.0,
                    "Sim, para a maior parte dos profissionais da saúde – -01 (perde 01 ponto)": -1.0,
                    "Sim, para a menor parte dos profissionais da saúde – -02 (perde 02 pontos)": -2.0,
                    "Não houve registro eletrônico de nenhum profissional de saúde – -03 (perde 03 pontos)": -3.0
                }

                d17_1 = res_data.get("17.1") or {
                    "valor": "Selecione...",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_17_1 = d17_1.get("valor", "Selecione...")
                l_salvo_17_1 = d17_1.get("link", "")

                c171_1, c171_2 = st.columns([1, 1])
                with c171_1:
                    lista_opcoes_17_1 = list(opts_17_1.keys())
                    idx_salvo_17_1 = lista_opcoes_17_1.index(v_salvo_17_1) if v_salvo_17_1 in opts_17_1 else 0

                    sel_17_1 = st.radio(
                        "Frequência eletrônica:",
                        options=lista_opcoes_17_1,
                        index=idx_salvo_17_1,
                        key=f"r_17_1_{ano_sel}",
                        label_visibility="collapsed"
                    )

                with c171_2:
                    link_17_1_input = st.text_area(
                        "Link/Evidência do Sistema de Ponto (17.1):",
                        value=l_salvo_17_1,
                        key=f"t_17_1_{ano_sel}",
                        height=130
                    )

                    links_17_1_visuais = re.findall(REGEX_PURE_URL, link_17_1_input or "")
                    if links_17_1_visuais:
                        st.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_17_1_visuais]
                            )
                        )

                # Chat de comentários
                bloco_comentarios_isaude("17.1", res_data)

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 17.1", key=f"btn_salvar_17_1_{ano_sel}", type="primary"):
                    val_sel_17_1 = sel_17_1 if sel_17_1 is not None else "Selecione..."
                    val_lk_17_1 = link_17_1_input.strip()
                    pts_17_1 = opts_17_1.get(val_sel_17_1, 0.0)
                    comentarios_17_1 = d17_1.get("comentarios", [])

                    save_resp_isaude(
                        qid="17.1",
                        valor=val_sel_17_1,
                        pontos=pts_17_1,
                        link=val_lk_17_1,
                        comentarios=comentarios_17_1
                    )

                    # Modal de aviso para links pendentes
                    links_atuais_17_1 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_17_1_input or "")]
                    links_antigos_17_1 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_17_1 or "")]

                    if (val_sel_17_1 != v_salvo_17_1 or val_lk_17_1 != l_salvo_17_1) and links_atuais_17_1 and links_atuais_17_1 != links_antigos_17_1:
                        st.session_state[f"links_pendentes_17_1_{ano_sel}"] = links_atuais_17_1
                        st.session_state[f"gatilho_modal_17_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 17.1 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                pts_atuais_17_1 = d17_1.get("pontos", 0.0)
                cor_txt_17_1 = "#28a745" if pts_atuais_17_1 >= 0.0 else "#dc3545"

                st.markdown(
                    f"<span style='color:{cor_txt_17_1}; font-weight:bold;'>"
                    f"📊 Pontuação Aplicada no Quesito 17.1: {pts_atuais_17_1:+.1f} pontos</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 17.1
        if st.session_state.get(f"gatilho_modal_17_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("17.1", st.session_state.get(f"links_pendentes_17_1_{ano_sel}", []), ano_sel)


        # =============================================================================
        # QUESITO 17.1.1 • JORNADA DE TRABALHO DOS MÉDICOS AMBULATORIAIS
        # =============================================================================
        with st.container(key=f"container_bloco_jornada_medica_17_1_1_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 17.1.1 - Jornada de Trabalho dos Médicos Ambulatoriais ({ano_sel})", expanded=True):
                st.subheader(f"17.1.1 • Jornada de Trabalho dos Médicos Ambulatoriais ({ano_sel})")
                st.write(f"**Os médicos ambulatoriais da Atenção Especializada sob gestão municipal cumprem integralmente sua jornada de trabalho em {ano_sel}?**")
                st.caption("ℹ️ *Selecione a opção, preencha as evidências e clique no botão 'Salvar Quesito 17.1.1' para registrar.*")

                opts_17_1_1 = {
                    "Selecione...": 0.0,
                    "Sim, todos cumprem integralmente a jornada de trabalho – 00": 0.0,
                    "Sim, a maior parte cumpre integralmente a jornada de trabalho – -01 (perde 01 ponto)": -1.0,
                    "Sim, todos permanecem apenas nas consultas agendadas – -04 (perde 04 pontos)": -4.0,
                    "Sim, a maior parte permanece apenas nas consultas agendadas – -03 (perde 03 pontos)": -3.0,
                    "Não – -05 (perde 05 pontos)": -5.0
                }

                d17_1_1 = res_data.get("17.1.1") or {
                    "valor": "Selecione...",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_17_1_1 = d17_1_1.get("valor", "Selecione...")
                l_salvo_17_1_1 = d17_1_1.get("link", "")

                c1711_1, c1711_2 = st.columns([1, 1])
                with c1711_1:
                    lista_opcoes_17_1_1 = list(opts_17_1_1.keys())
                    idx_salvo_17_1_1 = lista_opcoes_17_1_1.index(v_salvo_17_1_1) if v_salvo_17_1_1 in opts_17_1_1 else 0

                    sel_17_1_1 = st.radio(
                        "Jornada de trabalho médica:",
                        options=lista_opcoes_17_1_1,
                        index=idx_salvo_17_1_1,
                        key=f"r_17_1_1_{ano_sel}",
                        label_visibility="collapsed"
                    )

                with c1711_2:
                    link_17_1_1_input = st.text_area(
                        "Link/Evidência (Relatórios, espelho de ponto, etc.):",
                        value=l_salvo_17_1_1,
                        key=f"t_17_1_1_{ano_sel}",
                        height=130
                    )

                    links_17_1_1_visuais = re.findall(REGEX_PURE_URL, link_17_1_1_input or "")
                    if links_17_1_1_visuais:
                        st.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_17_1_1_visuais]
                            )
                        )

                # Chat de comentários
                bloco_comentarios_isaude("17.1.1", res_data)

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 17.1.1", key=f"btn_salvar_17_1_1_{ano_sel}", type="primary"):
                    val_sel_17_1_1 = sel_17_1_1 if sel_17_1_1 is not None else "Selecione..."
                    val_lk_17_1_1 = link_17_1_1_input.strip()
                    pts_17_1_1 = opts_17_1_1.get(val_sel_17_1_1, 0.0)
                    comentarios_17_1_1 = d17_1_1.get("comentarios", [])

                    save_resp_isaude(
                        qid="17.1.1",
                        valor=val_sel_17_1_1,
                        pontos=pts_17_1_1,
                        link=val_lk_17_1_1,
                        comentarios=comentarios_17_1_1
                    )

                    # Modal de aviso para links pendentes
                    links_atuais_17_1_1 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_17_1_1_input or "")]
                    links_antigos_17_1_1 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_17_1_1 or "")]

                    if (val_sel_17_1_1 != v_salvo_17_1_1 or val_lk_17_1_1 != l_salvo_17_1_1) and links_atuais_17_1_1 and links_atuais_17_1_1 != links_antigos_17_1_1:
                        st.session_state[f"links_pendentes_17_1_1_{ano_sel}"] = links_atuais_17_1_1
                        st.session_state[f"gatilho_modal_17_1_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 17.1.1 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                pts_atuais_17_1_1 = d17_1_1.get("pontos", 0.0)
                cor_txt_17_1_1 = "#28a745" if pts_atuais_17_1_1 >= 0.0 else "#dc3545"

                st.markdown(
                    f"<span style='color:{cor_txt_17_1_1}; font-weight:bold;'>"
                    f"📊 Pontuação Obtida no Quesito 17.1.1: {pts_atuais_17_1_1:+.1f} pontos</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 17.1.1
        if st.session_state.get(f"gatilho_modal_17_1_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("17.1.1", st.session_state.get(f"links_pendentes_17_1_1_{ano_sel}", []), ano_sel)

        # =============================================================================
        # QUESITO 17.2 • INTERVALO DE AGENDAMENTO DE CONSULTAS MÉDICAS
        # =============================================================================
        with st.container(key=f"container_bloco_agendamento_17_2_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 17.2 - Intervalo de Agendamento na Atenção Especializada ({ano_sel})", expanded=True):
                st.subheader(f"17.2 • Intervalo de Agendamento de Consultas Médicas ({ano_sel})")
                st.write(f"**Assinale o intervalo de agendamento das consultas médicas da Atenção Especializada sob gestão municipal:**")
                st.caption("ℹ️ *Selecione a opção, preencha as evidências e clique no botão 'Salvar Quesito 17.2' para registrar.*")

                opts_17_2 = {
                    "Selecione...": 0.0,
                    "Não há agendamento de consultas da Atenção Especializada, pois todas são de pronto atendimento – 00": 0.0,
                    "Agendamento de cada paciente em horário único com, no mínimo, 15 minutes de atendimento – 00": 0.0,
                    "Agendamento de cada paciente em horário único com menos de 15 minutes de atendimento – -0,5 (perde 0,5 ponto)": -0.5,
                    "Agendamento de 2 ou mais pacientes no mesmo horário – -0,5 (perde 0,5 ponto)": -0.5
                }

                d17_2 = res_data.get("17.2") or {
                    "valor": "Selecione...",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_17_2 = d17_2.get("valor", "Selecione...")
                l_salvo_17_2 = d17_2.get("link", "")

                c172_1, c172_2 = st.columns([1, 1])
                with c172_1:
                    lista_opcoes_17_2 = list(opts_17_2.keys())
                    idx_salvo_17_2 = lista_opcoes_17_2.index(v_salvo_17_2) if v_salvo_17_2 in opts_17_2 else 0

                    sel_17_2 = st.radio(
                        "Intervalo de agendamento:",
                        options=lista_opcoes_17_2,
                        index=idx_salvo_17_2,
                        key=f"r_17_2_{ano_sel}",
                        label_visibility="collapsed"
                    )

                with c172_2:
                    link_17_2_input = st.text_area(
                        "Link/Evidência do Sistema de Agendamento (17.2):",
                        value=l_salvo_17_2,
                        key=f"t_17_2_{ano_sel}",
                        height=130
                    )

                    links_17_2_visuais = re.findall(REGEX_PURE_URL, link_17_2_input or "")
                    if links_17_2_visuais:
                        st.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_17_2_visuais]
                            )
                        )

                # Chat de comentários
                bloco_comentarios_isaude("17.2", res_data)

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 17.2", key=f"btn_salvar_17_2_{ano_sel}", type="primary"):
                    val_sel_17_2 = sel_17_2 if sel_17_2 is not None else "Selecione..."
                    val_lk_17_2 = link_17_2_input.strip()
                    pts_17_2 = opts_17_2.get(val_sel_17_2, 0.0)
                    comentarios_17_2 = d17_2.get("comentarios", [])

                    save_resp_isaude(
                        qid="17.2",
                        valor=val_sel_17_2,
                        pontos=pts_17_2,
                        link=val_lk_17_2,
                        comentarios=comentarios_17_2
                    )

                    # Modal de aviso para links pendentes
                    links_atuais_17_2 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_17_2_input or "")]
                    links_antigos_17_2 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_17_2 or "")]

                    if (val_sel_17_2 != v_salvo_17_2 or val_lk_17_2 != l_salvo_17_2) and links_atuais_17_2 and links_atuais_17_2 != links_antigos_17_2:
                        st.session_state[f"links_pendentes_17_2_{ano_sel}"] = links_atuais_17_2
                        st.session_state[f"gatilho_modal_17_2_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 17.2 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                pts_atuais_17_2 = d17_2.get("pontos", 0.0)
                cor_txt_17_2 = "#28a745" if pts_atuais_17_2 >= 0.0 else "#dc3545"

                st.markdown(
                    f"<span style='color:{cor_txt_17_2}; font-weight:bold;'>"
                    f"📊 Pontuação Obtida no Quesito 17.2: {pts_atuais_17_2:+.1f} pontos</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 17.2
        if st.session_state.get(f"gatilho_modal_17_2_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("17.2", st.session_state.get(f"links_pendentes_17_2_{ano_sel}", []), ano_sel)

        # =============================================================================
        # QUESITO 17.3 • CONTROLE DE ABSENTEÍSMO
        # =============================================================================
        with st.container(key=f"container_bloco_absenteismo_17_3_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 17.3 - Controle de Absenteísmo na Atenção Especializada ({ano_sel})", expanded=True):
                st.subheader(f"17.3 • Controle de Absenteísmo ({ano_sel})")
                st.write(f"**17.3 O município possui controle de absenteísmo de consultas médicas da Atenção Especializada sob gestão municipal em {ano_sel}?**")
                st.caption("ℹ️ *Selecione a opção, preencha as evidências e clique no botão 'Salvar Quesito 17.3' para registrar.*")

                opts_17_3 = {
                    "Selecione...": 0.0,
                    "Sim, para todas as consultas médicas – 00": 0.0,
                    "Sim, para a maior parte das consultas médicas – -01 (perde 01 ponto)": -1.0,
                    "Sim, para a menor parte das consultas médicas – -02 (perde 02 pontos)": -2.0,
                    "Não – -03 (perde 03 pontos)": -3.0
                }

                d17_3 = res_data.get("17.3") or {
                    "valor": "Selecione...",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_17_3 = d17_3.get("valor", "Selecione...")
                l_salvo_17_3 = d17_3.get("link", "")

                c173_1, c173_2 = st.columns([1, 1])
                with c173_1:
                    lista_opcoes_17_3 = list(opts_17_3.keys())
                    idx_salvo_17_3 = lista_opcoes_17_3.index(v_salvo_17_3) if v_salvo_17_3 in opts_17_3 else 0

                    sel_17_3 = st.radio(
                        "Controle de absenteísmo:",
                        options=lista_opcoes_17_3,
                        index=idx_salvo_17_3,
                        key=f"r_17_3_{ano_sel}",
                        label_visibility="collapsed"
                    )

                with c173_2:
                    link_17_3_input = st.text_area(
                        "Link/Evidência Geral (17.3):",
                        value=l_salvo_17_3,
                        key=f"t_17_3_{ano_sel}",
                        height=130
                    )

                    links_17_3_visuais = re.findall(REGEX_PURE_URL, link_17_3_input or "")
                    if links_17_3_visuais:
                        st.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_17_3_visuais]
                            )
                        )

                # Chat de comentários
                bloco_comentarios_isaude("17.3", res_data)

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 17.3", key=f"btn_salvar_17_3_{ano_sel}", type="primary"):
                    val_sel_17_3 = sel_17_3 if sel_17_3 is not None else "Selecione..."
                    val_lk_17_3 = link_17_3_input.strip()
                    pts_17_3 = opts_17_3.get(val_sel_17_3, 0.0)
                    comentarios_17_3 = d17_3.get("comentarios", [])

                    save_resp_isaude(
                        qid="17.3",
                        valor=val_sel_17_3,
                        pontos=pts_17_3,
                        link=val_lk_17_3,
                        comentarios=comentarios_17_3
                    )

                    # Modal de aviso para links pendentes
                    links_atuais_17_3 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_17_3_input or "")]
                    links_antigos_17_3 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_17_3 or "")]

                    if (val_sel_17_3 != v_salvo_17_3 or val_lk_17_3 != l_salvo_17_3) and links_atuais_17_3 and links_atuais_17_3 != links_antigos_17_3:
                        st.session_state[f"links_pendentes_17_3_{ano_sel}"] = links_atuais_17_3
                        st.session_state[f"gatilho_modal_17_3_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 17.3 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                pts_atuais_17_3 = d17_3.get("pontos", 0.0)
                cor_txt_17_3 = "#28a745" if pts_atuais_17_3 >= 0.0 else "#dc3545"

                st.markdown(
                    f"<span style='color:{cor_txt_17_3}; font-weight:bold;'>"
                    f"📊 Pontuação Obtida no Quesito 17.3: {pts_atuais_17_3:+.1f} pontos</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 17.3
        if st.session_state.get(f"gatilho_modal_17_3_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("17.3", st.session_state.get(f"links_pendentes_17_3_{ano_sel}", []), ano_sel)


        # =============================================================================
        # QUESITO 17.3.1 • TAXA DE ABSENTEÍSMO
        # =============================================================================
        with st.container(key=f"container_bloco_taxa_absenteismo_17_3_1_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 17.3.1 - Evolução da Taxa de Absenteísmo na Atenção Especializada ({ano_sel})", expanded=True):
                ano_atual = int(ano_sel)
                ano_menos_1 = ano_atual - 1
                ano_menos_2 = ano_atual - 2

                st.subheader(f"17.3.1 • Taxa de Absenteísmo ({ano_sel})")
                st.write(f"**Informe a taxa de absenteísmo de consulta médica da Atenção Especializada sob gestão municipal:**")
                st.caption(f"Fórmula: Se TA({ano_atual}) > média de TA({ano_menos_2}) e TA({ano_menos_1}) -> Perde 2 pontos.")
                st.caption("ℹ️ *Preencha os dados, insira os links de evidência e clique no botão 'Salvar Quesito 17.3.1' para registrar.*")

                d17_3_1 = res_data.get("17.3.1") or {
                    "valor": "0.0|0.0|0.0",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_17_3_1 = d17_3_1.get("valor", "0.0|0.0|0.0")
                l_salvo_17_3_1 = d17_3_1.get("link", "")

                partes_ta = v_salvo_17_3_1.split("|") if "|" in v_salvo_17_3_1 else ["0.0", "0.0", "0.0"]
                partes_ta += ["0.0"] * (3 - len(partes_ta))

                try:
                    v_a2 = float(partes_ta[0])
                    v_a1 = float(partes_ta[1])
                    v_atual = float(partes_ta[2])
                except ValueError:
                    v_a2 = v_a1 = v_atual = 0.0

                c1731_1, c1731_2 = st.columns([1, 1])

                with c1731_1:
                    st.markdown("**📊 Taxas de Absenteísmo (%)**")
                    ta_2 = st.number_input(
                        f"Taxa em {ano_menos_2} (TA-2):",
                        min_value=0.0, max_value=100.0, value=v_a2, step=0.1, format="%.1f",
                        key=f"num_ta_2_{ano_sel}"
                    )
                    ta_1 = st.number_input(
                        f"Taxa em {ano_menos_1} (TA-1):",
                        min_value=0.0, max_value=100.0, value=v_a1, step=0.1, format="%.1f",
                        key=f"num_ta_1_{ano_sel}"
                    )
                    ta_atual = st.number_input(
                        f"Taxa em {ano_atual} (TA):",
                        min_value=0.0, max_value=100.0, value=v_atual, step=0.1, format="%.1f",
                        key=f"num_ta_atual_{ano_sel}"
                    )

                    media_anteriores = (ta_2 + ta_1) / 2.0
                    st.info(f"💡 Média de {ano_menos_2} e {ano_menos_1}: **{media_anteriores:.1f}%**")

                with c1731_2:
                    link_17_3_1_input = st.text_area(
                        "Link/Evidência Geral (17.3.1):",
                        value=l_salvo_17_3_1,
                        key=f"t_17_3_1_{ano_sel}",
                        height=180
                    )

                    links_17_3_1_visuais = re.findall(REGEX_PURE_URL, link_17_3_1_input or "")
                    if links_17_3_1_visuais:
                        st.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_17_3_1_visuais]
                            )
                        )

                # Chat de comentários
                bloco_comentarios_isaude("17.3.1", res_data)

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 17.3.1", key=f"btn_salvar_17_3_1_{ano_sel}", type="primary"):
                    val_str_17_3_1 = f"{ta_2:.1f}|{ta_1:.1f}|{ta_atual:.1f}"
                    val_lk_17_3_1 = link_17_3_1_input.strip()
                    
                    # Regra do score: se TA atual for maior que a média dos dois anos anteriores, perde 2 pontos
                    pts_17_3_1 = -2.0 if ta_atual > media_anteriores else 0.0
                    comentarios_17_3_1 = d17_3_1.get("comentarios", [])

                    save_resp_isaude(
                        qid="17.3.1",
                        valor=val_str_17_3_1,
                        pontos=pts_17_3_1,
                        link=val_lk_17_3_1,
                        comentarios=comentarios_17_3_1
                    )

                    # Modal de aviso para links pendentes
                    links_atuais_17_3_1 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_17_3_1_input or "")]
                    links_antigos_17_3_1 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_17_3_1 or "")]

                    if (val_str_17_3_1 != v_salvo_17_3_1 or val_lk_17_3_1 != l_salvo_17_3_1) and links_atuais_17_3_1 and links_atuais_17_3_1 != links_antigos_17_3_1:
                        st.session_state[f"links_pendentes_17_3_1_{ano_sel}"] = links_atuais_17_3_1
                        st.session_state[f"gatilho_modal_17_3_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 17.3.1 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                pts_atuais_17_3_1 = d17_3_1.get("pontos", 0.0)
                cor_txt_17_3_1 = "#28a745" if pts_atuais_17_3_1 >= 0.0 else "#dc3545"

                st.markdown(
                    f"<span style='color:{cor_txt_17_3_1}; font-weight:bold;'>"
                    f"📊 Pontuação Obtida no Quesito 17.3.1: {pts_atuais_17_3_1:+.1f} pontos</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 17.3.1
        if st.session_state.get(f"gatilho_modal_17_3_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("17.3.1", st.session_state.get(f"links_pendentes_17_3_1_{ano_sel}", []), ano_sel)

        # =============================================================================
        # QUESITO 17.3.2 • MEDIDAS PARA REDUÇÃO DO ABSENTEÍSMO
        # =============================================================================
        with st.container(key=f"container_bloco_medidas_absenteismo_17_3_2_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 17.3.2 - Medidas para Redução de Absenteísmo na Atenção Especializada ({ano_sel})", expanded=True):
                st.subheader(f"17.3.2 • Medidas para Redução do Absenteísmo ({ano_sel})")
                st.write(f"**17.3.2 O município realiza medidas para a redução desta taxa de absenteísmo?**")
                st.caption("ℹ️ *Selecione a opção, preencha as evidências e clique no botão 'Salvar Quesito 17.3.2' para registrar.*")

                opts_17_3_2 = {
                    "Selecione...": 0.0,
                    "Sim – 00": 0.0,
                    "Não – -02 (perde 02 pontos)": -2.0
                }

                d17_3_2 = res_data.get("17.3.2") or {
                    "valor": "Selecione...",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_17_3_2 = d17_3_2.get("valor", "Selecione...")
                l_salvo_17_3_2 = d17_3_2.get("link", "")

                c1732_1, c1732_2 = st.columns([1, 1])
                with c1732_1:
                    lista_opcoes_17_3_2 = list(opts_17_3_2.keys())
                    idx_salvo_17_3_2 = lista_opcoes_17_3_2.index(v_salvo_17_3_2) if v_salvo_17_3_2 in opts_17_3_2 else 0

                    sel_17_3_2 = st.radio(
                        "Realiza medidas de redução:",
                        options=lista_opcoes_17_3_2,
                        index=idx_salvo_17_3_2,
                        key=f"reg_17_3_2_rad_{ano_sel}",
                        label_visibility="collapsed"
                    )

                with c1732_2:
                    link_17_3_2_input = st.text_area(
                        "Link/Evidência das Ações de Redução (17.3.2):",
                        value=l_salvo_17_3_2,
                        key=f"reg_17_3_2_txt_{ano_sel}",
                        height=130
                    )

                    links_17_3_2_visuais = re.findall(REGEX_PURE_URL, link_17_3_2_input or "")
                    if links_17_3_2_visuais:
                        st.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_17_3_2_visuais]
                            )
                        )

                # Chat de comentários
                bloco_comentarios_isaude("17.3.2", res_data)

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 17.3.2", key=f"btn_salvar_17_3_2_{ano_sel}", type="primary"):
                    val_sel_17_3_2 = sel_17_3_2 if sel_17_3_2 is not None else "Selecione..."
                    val_lk_17_3_2 = link_17_3_2_input.strip()
                    pts_17_3_2 = opts_17_3_2.get(val_sel_17_3_2, 0.0)
                    comentarios_17_3_2 = d17_3_2.get("comentarios", [])

                    save_resp_isaude(
                        qid="17.3.2",
                        valor=val_sel_17_3_2,
                        pontos=pts_17_3_2,
                        link=val_lk_17_3_2,
                        comentarios=comentarios_17_3_2
                    )

                    # Modal de aviso para links pendentes
                    links_atuais_17_3_2 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_17_3_2_input or "")]
                    links_antigos_17_3_2 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_17_3_2 or "")]

                    if (val_sel_17_3_2 != v_salvo_17_3_2 or val_lk_17_3_2 != l_salvo_17_3_2) and links_atuais_17_3_2 and links_atuais_17_3_2 != links_antigos_17_3_2:
                        st.session_state[f"links_pendentes_17_3_2_{ano_sel}"] = links_atuais_17_3_2
                        st.session_state[f"gatilho_modal_17_3_2_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 17.3.2 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                pts_atuais_17_3_2 = d17_3_2.get("pontos", 0.0)
                cor_txt_17_3_2 = "#28a745" if pts_atuais_17_3_2 >= 0.0 else "#dc3545"

                st.markdown(
                    f"<span style='color:{cor_txt_17_3_2}; font-weight:bold;'>"
                    f"📊 Pontuação Obtida no Quesito 17.3.2: {pts_atuais_17_3_2:+.1f} pontos</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 17.3.2
        if st.session_state.get(f"gatilho_modal_17_3_2_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("17.3.2", st.session_state.get(f"links_pendentes_17_3_2_{ano_sel}", []), ano_sel)


        # =============================================================================
        # QUESITO 17.3.2.1 • ROL DE MEDIDAS DE REDUÇÃO DO ABSENTEÍSMO
        # =============================================================================
        with st.container(key=f"container_bloco_rol_medidas_17_3_2_1_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 17.3.2.1 - Rol de Medidas de Redução do Absenteísmo ({ano_sel})", expanded=True):
                st.subheader(f"17.3.2.1 • Rol de Medidas de Redução do Absenteísmo ({ano_sel})")
                st.write(f"**17.3.2.1 Assinale as medidas utilizadas para a redução da taxa de absenteísmo:**")
                st.caption("ℹ️ *Selecione as opções desejadas, informe os links de evidência e clique no botão 'Salvar Quesito 17.3.2.1' para registrar.*")

                d17_3_2_1 = res_data.get("17.3.2.1") or {
                    "valor": "",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_17_3_2_1 = d17_3_2_1.get("valor", "")
                l_salvo_17_3_2_1 = d17_3_2_1.get("link", "")
                lista_salva_17_3_2_1 = [item.strip() for item in v_salvo_17_3_2_1.split(";")] if v_salvo_17_3_2_1 else []

                opc_1 = "Informar e sensibilizar as equipes/profissionais a respeito do absenteísmo and promover capacitações"
                opc_2 = "Criação de Central de relacionamento para usuário SUS, com disponibilização de canal direto de comunicação"
                opc_3 = "Orientação das famílias e busca ativa dos faltosos"
                opc_4 = "Promoção de campanhas de conscientização"
                opc_5 = "Outros"

                c17321_1, c17321_2 = st.columns([1, 1])

                with c17321_1:
                    st.write("📋 **Selecione todas as medidas aplicadas:**")
                    chk_1 = st.checkbox(opc_1, value=(opc_1 in lista_salva_17_3_2_1), key=f"chk_17321_1_{ano_sel}")
                    chk_2 = st.checkbox(opc_2, value=(opc_2 in lista_salva_17_3_2_1), key=f"chk_17321_2_{ano_sel}")
                    chk_3 = st.checkbox(opc_3, value=(opc_3 in lista_salva_17_3_2_1), key=f"chk_17321_3_{ano_sel}")
                    chk_4 = st.checkbox(opc_4, value=(opc_4 in lista_salva_17_3_2_1), key=f"chk_17321_4_{ano_sel}")
                    chk_5 = st.checkbox(opc_5, value=(opc_5 in lista_salva_17_3_2_1), key=f"chk_17321_5_{ano_sel}")

                    selecionados_17_3_2_1 = []
                    if chk_1: selecionados_17_3_2_1.append(opc_1)
                    if chk_2: selecionados_17_3_2_1.append(opc_2)
                    if chk_3: selecionados_17_3_2_1.append(opc_3)
                    if chk_4: selecionados_17_3_2_1.append(opc_4)
                    if chk_5: selecionados_17_3_2_1.append(opc_5)

                    string_selecionados_17_3_2_1 = "; ".join(selecionados_17_3_2_1) if selecionados_17_3_2_1 else "Nenhuma medida selecionada"

                with c17321_2:
                    link_17_3_2_1_input = st.text_area(
                        "Link/Evidência das Medidas Assinaladas (17.3.2.1):",
                        value=l_salvo_17_3_2_1,
                        key=f"reg_17_3_2_1_txt_{ano_sel}",
                        height=210
                    )

                    links_17_3_2_1_visuais = re.findall(REGEX_PURE_URL, link_17_3_2_1_input or "")
                    if links_17_3_2_1_visuais:
                        st.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_17_3_2_1_visuais]
                            )
                        )

                # Chat de comentários
                bloco_comentarios_isaude("17.3.2.1", res_data)

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 17.3.2.1", key=f"btn_salvar_17_3_2_1_{ano_sel}", type="primary"):
                    val_str_17_3_2_1 = string_selecionados_17_3_2_1
                    val_lk_17_3_2_1 = link_17_3_2_1_input.strip()
                    pts_17_3_2_1 = 0.0  # Quesito apenas informativo / rolled check
                    comentarios_17_3_2_1 = d17_3_2_1.get("comentarios", [])

                    save_resp_isaude(
                        qid="17.3.2.1",
                        valor=val_str_17_3_2_1,
                        pontos=pts_17_3_2_1,
                        link=val_lk_17_3_2_1,
                        comentarios=comentarios_17_3_2_1
                    )

                    # Modal de aviso para links pendentes
                    links_atuais_17_3_2_1 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_17_3_2_1_input or "")]
                    links_antigos_17_3_2_1 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_17_3_2_1 or "")]

                    if (val_str_17_3_2_1 != v_salvo_17_3_2_1 or val_lk_17_3_2_1 != l_salvo_17_3_2_1) and links_atuais_17_3_2_1 and links_atuais_17_3_2_1 != links_antigos_17_3_2_1:
                        st.session_state[f"links_pendentes_17_3_2_1_{ano_sel}"] = links_atuais_17_3_2_1
                        st.session_state[f"gatilho_modal_17_3_2_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 17.3.2.1 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                pts_atuais_17_3_2_1 = d17_3_2_1.get("pontos", 0.0)
                cor_txt_17_3_2_1 = "#28a745" if pts_atuais_17_3_2_1 >= 0.0 else "#dc3545"

                st.markdown(
                    f"<span style='color:{cor_txt_17_3_2_1}; font-weight:bold;'>"
                    f"📊 Pontuação Obtida no Quesito 17.3.2.1: {pts_atuais_17_3_2_1:+.1f} pontos</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 17.3.2.1
        if st.session_state.get(f"gatilho_modal_17_3_2_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("17.3.2.1", st.session_state.get(f"links_pendentes_17_3_2_1_{ano_sel}", []), ano_sel)

        # =============================================================================
        # QUESITO 17.4 • CONTROLE DE ABSENTEÍSMO DE EXAMES MÉDICOS
        # =============================================================================
        with st.container(key=f"container_bloco_absenteismo_exames_17_4_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 17.4 - Controle de Absenteísmo de Exames na Atenção Especializada ({ano_sel})", expanded=True):
                st.subheader(f"17.4 • Controle de Absenteísmo (Exames) ({ano_sel})")
                st.write(f"**17.4 A Prefeitura Municipal possui controle de absenteísmo para os exames médicos da Atenção Especializada sob sua gestão?**")
                st.caption("ℹ️ *Selecione a opção, preencha as evidências e clique no botão 'Salvar Quesito 17.4' para registrar.*")

                opts_17_4 = {
                    "Selecione...": 0.0,
                    "Sim, para todos os exames – 00": 0.0,
                    "Sim, para a maior parte dos exames – -01 (perde 01 ponto)": -1.0,
                    "Sim, para a menor parte dos exames – -02 (perde 02 pontos)": -2.0,
                    "Não – -03 (perde 03 pontos)": -3.0
                }

                d17_4 = res_data.get("17.4") or {
                    "valor": "Selecione...",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_17_4 = d17_4.get("valor", "Selecione...")
                l_salvo_17_4 = d17_4.get("link", "")

                c174_1, c174_2 = st.columns([1, 1])
                with c174_1:
                    lista_opcoes_17_4 = list(opts_17_4.keys())
                    idx_salvo_17_4 = lista_opcoes_17_4.index(v_salvo_17_4) if v_salvo_17_4 in opts_17_4 else 0

                    sel_17_4 = st.radio(
                        "Controle de absenteísmo (Exames):",
                        options=lista_opcoes_17_4,
                        index=idx_salvo_17_4,
                        key=f"reg_17_4_rad_{ano_sel}",
                        label_visibility="collapsed"
                    )

                with c174_2:
                    link_17_4_input = st.text_area(
                        "Link/Evidência do Controle de Absenteísmo de Exames (17.4):",
                        value=l_salvo_17_4,
                        key=f"reg_17_4_txt_{ano_sel}",
                        height=130
                    )

                    links_17_4_visuais = re.findall(REGEX_PURE_URL, link_17_4_input or "")
                    if links_17_4_visuais:
                        st.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_17_4_visuais]
                            )
                        )

                # Chat de comentários
                bloco_comentarios_isaude("17.4", res_data)

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 17.4", key=f"btn_salvar_17_4_{ano_sel}", type="primary"):
                    val_sel_17_4 = sel_17_4 if sel_17_4 is not None else "Selecione..."
                    val_lk_17_4 = link_17_4_input.strip()
                    pts_17_4 = opts_17_4.get(val_sel_17_4, 0.0)
                    comentarios_17_4 = d17_4.get("comentarios", [])

                    save_resp_isaude(
                        qid="17.4",
                        valor=val_sel_17_4,
                        pontos=pts_17_4,
                        link=val_lk_17_4,
                        comentarios=comentarios_17_4
                    )

                    # Modal de aviso para links pendentes
                    links_atuais_17_4 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_17_4_input or "")]
                    links_antigos_17_4 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_17_4 or "")]

                    if (val_sel_17_4 != v_salvo_17_4 or val_lk_17_4 != l_salvo_17_4) and links_atuais_17_4 and links_atuais_17_4 != links_antigos_17_4:
                        st.session_state[f"links_pendentes_17_4_{ano_sel}"] = links_atuais_17_4
                        st.session_state[f"gatilho_modal_17_4_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 17.4 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                pts_atuais_17_4 = d17_4.get("pontos", 0.0)
                cor_txt_17_4 = "#28a745" if pts_atuais_17_4 >= 0.0 else "#dc3545"

                st.markdown(
                    f"<span style='color:{cor_txt_17_4}; font-weight:bold;'>"
                    f"📊 Pontuação Obtida no Quesito 17.4: {pts_atuais_17_4:+.1f} pontos</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 17.4
        if st.session_state.get(f"gatilho_modal_17_4_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("17.4", st.session_state.get(f"links_pendentes_17_4_{ano_sel}", []), ano_sel)


        # =============================================================================
        # QUESITO 17.4.1 • TAXA DE ABSENTEÍSMO DE EXAMES MÉDICOS (DINÂMICO)
        # =============================================================================
        with st.container(key=f"container_bloco_taxa_absenteismo_exames_17_4_1_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 17.4.1 - Evolução da Taxa de Absenteísmo de Exames ({ano_sel})", expanded=True):
                ano_atual = int(ano_sel)
                ano_menos_1 = ano_atual - 1
                ano_menos_2 = ano_atual - 2

                st.subheader(f"17.4.1 • Taxa de Absenteísmo (Exames) ({ano_sel})")
                st.write(f"**Informe a taxa de absenteísmo de exame médico da Atenção Especializada sob gestão municipal:**")
                st.caption(f"ℹ️ *Fórmula: Se TA({ano_atual}) > média de TA({ano_menos_2}) e TA({ano_menos_1}) -> Perde 2 pontos.*")

                d17_4_1 = res_data.get("17.4.1") or {
                    "valor": "0.0|0.0|0.0",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_17_4_1 = d17_4_1.get("valor", "0.0|0.0|0.0")
                l_salvo_17_4_1 = d17_4_1.get("link", "")

                partes_ta = v_salvo_17_4_1.split("|") if "|" in v_salvo_17_4_1 else ["0.0", "0.0", "0.0"]
                partes_ta += ["0.0"] * (3 - len(partes_ta))

                try:
                    v_a2, v_a1, v_atual = float(partes_ta[0]), float(partes_ta[1]), float(partes_ta[2])
                except ValueError:
                    v_a2 = v_a1 = v_atual = 0.0

                c1741_1, c1741_2 = st.columns([1, 1])

                with c1741_1:
                    st.write("📊 **Taxas de Absenteísmo para Exames (%)**")
                    ta_2 = st.number_input(f"Taxa em {ano_menos_2} (TA-2):", min_value=0.0, max_value=100.0, value=v_a2, step=0.1, format="%.1f", key=f"ta_2_ex_{ano_sel}")
                    ta_1 = st.number_input(f"Taxa em {ano_menos_1} (TA-1):", min_value=0.0, max_value=100.0, value=v_a1, step=0.1, format="%.1f", key=f"ta_1_ex_{ano_sel}")
                    ta_atual = st.number_input(f"Taxa em {ano_atual} (TA):", min_value=0.0, max_value=100.0, value=v_atual, step=0.1, format="%.1f", key=f"ta_atual_ex_{ano_sel}")

                    string_valor_calculado = f"{ta_2:.1f}|{ta_1:.1f}|{ta_atual:.1f}"
                    media_anteriores = (ta_2 + ta_1) / 2.0
                    st.info(f"💡 Média de {ano_menos_2} e {ano_menos_1}: **{media_anteriores:.1f}%**")

                with c1741_2:
                    link_17_4_1_input = st.text_area(
                        "Link/Evidência dos Relatórios de Absenteísmo de Exames (17.4.1):",
                        value=l_salvo_17_4_1,
                        key=f"reg_17_4_1_txt_{ano_sel}",
                        height=210
                    )

                    links_17_4_1_visuais = re.findall(REGEX_PURE_URL, link_17_4_1_input or "")
                    if links_17_4_1_visuais:
                        st.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_17_4_1_visuais]
                            )
                        )

                # Chat de comentários
                bloco_comentarios_isaude("17.4.1", res_data)

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 17.4.1", key=f"btn_salvar_17_4_1_{ano_sel}", type="primary"):
                    val_str_17_4_1 = string_valor_calculado
                    val_lk_17_4_1 = link_17_4_1_input.strip()
                    pts_17_4_1 = -2.0 if ta_atual > media_anteriores else 0.0
                    comentarios_17_4_1 = d17_4_1.get("comentarios", [])

                    save_resp_isaude(
                        qid="17.4.1",
                        valor=val_str_17_4_1,
                        pontos=pts_17_4_1,
                        link=val_lk_17_4_1,
                        comentarios=comentarios_17_4_1
                    )

                    # Modal de aviso para links pendentes
                    links_atuais_17_4_1 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_17_4_1_input or "")]
                    links_antigos_17_4_1 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_17_4_1 or "")]

                    if (val_str_17_4_1 != v_salvo_17_4_1 or val_lk_17_4_1 != l_salvo_17_4_1) and links_atuais_17_4_1 and links_atuais_17_4_1 != links_antigos_17_4_1:
                        st.session_state[f"links_pendentes_17_4_1_{ano_sel}"] = links_atuais_17_4_1
                        st.session_state[f"gatilho_modal_17_4_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 17.4.1 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                pts_atuais_17_4_1 = d17_4_1.get("pontos", 0.0)
                cor_txt_17_4_1 = "#28a745" if pts_atuais_17_4_1 >= 0.0 else "#dc3545"

                st.markdown(
                    f"<span style='color:{cor_txt_17_4_1}; font-weight:bold;'>"
                    f"📊 Pontuação Obtida no Quesito 17.4.1: {pts_atuais_17_4_1:+.1f} pontos</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 17.4.1
        if st.session_state.get(f"gatilho_modal_17_4_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("17.4.1", st.session_state.get(f"links_pendentes_17_4_1_{ano_sel}", []), ano_sel)

        # =============================================================================
        # QUESITO 17.4.2 • MEDIDAS PARA REDUÇÃO DO ABSENTEÍSMO EM EXAMES
        # =============================================================================
        with st.container(key=f"container_bloco_medidas_exames_17_4_2_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 17.4.2 - Medidas para Redução de Absenteísmo de Exames ({ano_sel})", expanded=True):
                st.subheader(f"17.4.2 • Medidas para Redução do Absenteísmo em Exames ({ano_sel})")
                st.write(f"**17.4.2 O município realiza medidas para a redução desta taxa de absenteísmo?**")
                st.caption("ℹ️ *Selecione a opção, preencha as evidências e clique no botão 'Salvar Quesito 17.4.2' para registrar.*")

                opts_17_4_2 = {
                    "Selecione...": 0.0,
                    "Sim – 00": 0.0,
                    "Não – -02 (perde 02 pontos)": -2.0
                }

                d17_4_2 = res_data.get("17.4.2") or {
                    "valor": "Selecione...",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_17_4_2 = d17_4_2.get("valor", "Selecione...")
                l_salvo_17_4_2 = d17_4_2.get("link", "")

                c1742_1, c1742_2 = st.columns([1, 1])
                with c1742_1:
                    lista_opcoes_17_4_2 = list(opts_17_4_2.keys())
                    idx_salvo_17_4_2 = lista_opcoes_17_4_2.index(v_salvo_17_4_2) if v_salvo_17_4_2 in opts_17_4_2 else 0

                    sel_17_4_2 = st.radio(
                        "Realiza medidas de redução (Exames):",
                        options=lista_opcoes_17_4_2,
                        index=idx_salvo_17_4_2,
                        key=f"reg_17_4_2_rad_{ano_sel}",
                        label_visibility="collapsed"
                    )

                with c1742_2:
                    link_17_4_2_input = st.text_area(
                        "Link/Evidência das Ações de Redução em Exames (17.4.2):",
                        value=l_salvo_17_4_2,
                        key=f"reg_17_4_2_txt_{ano_sel}",
                        height=130
                    )

                    links_17_4_2_visuais = re.findall(REGEX_PURE_URL, link_17_4_2_input or "")
                    if links_17_4_2_visuais:
                        st.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_17_4_2_visuais]
                            )
                        )

                # Chat de comentários
                bloco_comentarios_isaude("17.4.2", res_data)

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 17.4.2", key=f"btn_salvar_17_4_2_{ano_sel}", type="primary"):
                    val_sel_17_4_2 = sel_17_4_2 if sel_17_4_2 is not None else "Selecione..."
                    val_lk_17_4_2 = link_17_4_2_input.strip()
                    pts_17_4_2 = opts_17_4_2.get(val_sel_17_4_2, 0.0)
                    comentarios_17_4_2 = d17_4_2.get("comentarios", [])

                    save_resp_isaude(
                        qid="17.4.2",
                        valor=val_sel_17_4_2,
                        pontos=pts_17_4_2,
                        link=val_lk_17_4_2,
                        comentarios=comentarios_17_4_2
                    )

                    # Modal de aviso para links pendentes
                    links_atuais_17_4_2 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_17_4_2_input or "")]
                    links_antigos_17_4_2 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_17_4_2 or "")]

                    if (val_sel_17_4_2 != v_salvo_17_4_2 or val_lk_17_4_2 != l_salvo_17_4_2) and links_atuais_17_4_2 and links_atuais_17_4_2 != links_antigos_17_4_2:
                        st.session_state[f"links_pendentes_17_4_2_{ano_sel}"] = links_atuais_17_4_2
                        st.session_state[f"gatilho_modal_17_4_2_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 17.4.2 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                pts_atuais_17_4_2 = d17_4_2.get("pontos", 0.0)
                cor_txt_17_4_2 = "#28a745" if pts_atuais_17_4_2 >= 0.0 else "#dc3545"

                st.markdown(
                    f"<span style='color:{cor_txt_17_4_2}; font-weight:bold;'>"
                    f"📊 Pontuação Obtida no Quesito 17.4.2: {pts_atuais_17_4_2:+.1f} pontos</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 17.4.2
        if st.session_state.get(f"gatilho_modal_17_4_2_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("17.4.2", st.session_state.get(f"links_pendentes_17_4_2_{ano_sel}", []), ano_sel)


        # =============================================================================
        # QUESITO 17.4.2.1 • ROL DE MEDIDAS DE REDUÇÃO EM EXAMES
        # =============================================================================
        with st.container(key=f"container_bloco_rol_medidas_exames_17_4_2_1_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 17.4.2.1 - Rol de Medidas de Redução em Exames ({ano_sel})", expanded=True):
                st.subheader(f"17.4.2.1 • Rol de Medidas de Redução em Exames ({ano_sel})")
                st.write(f"**17.4.2.1 Assinale as medidas utilizadas para a redução da taxa de absenteísmo:**")
                st.caption("ℹ️ *Marque as opções aplicadas, informe o link de evidência e clique no botão 'Salvar Quesito 17.4.2.1' para registrar.*")

                d17_4_2_1 = res_data.get("17.4.2.1") or {
                    "valor": "",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_17_4_2_1 = d17_4_2_1.get("valor", "")
                l_salvo_17_4_2_1 = d17_4_2_1.get("link", "")
                lista_salva_17_4_2_1 = [item.strip() for item in v_salvo_17_4_2_1.split(";")] if v_salvo_17_4_2_1 else []

                opc_1 = "Informar e sensibilizar as equipes/profissionais a respeito do absenteísmo e promover capacitações"
                opc_2 = "Criação de Central de relacionamento para usuário SUS, com disponibilização de canal direto de comunicação"
                opc_3 = "Ligação telefônica ou outro meio de comunicação para confirmation do exame e presença do paciente"
                opc_4 = "Orientação das famílias e busca ativa dos faltosos"
                opc_5 = "Promoção de campanhas de conscientização"
                opc_6 = "Outros"

                c17421_1, c17421_2 = st.columns([1, 1])

                with c17421_1:
                    st.write("📋 **Selecione todas as medidas aplicadas:**")
                    chk_1 = st.checkbox(opc_1, value=(opc_1 in lista_salva_17_4_2_1), key=f"chk_17421_1_{ano_sel}")
                    chk_2 = st.checkbox(opc_2, value=(opc_2 in lista_salva_17_4_2_1), key=f"chk_17421_2_{ano_sel}")
                    chk_3 = st.checkbox(opc_3, value=(opc_3 in lista_salva_17_4_2_1), key=f"chk_17421_3_{ano_sel}")
                    chk_4 = st.checkbox(opc_4, value=(opc_4 in lista_salva_17_4_2_1), key=f"chk_17421_4_{ano_sel}")
                    chk_5 = st.checkbox(opc_5, value=(opc_5 in lista_salva_17_4_2_1), key=f"chk_17421_5_{ano_sel}")
                    chk_6 = st.checkbox(opc_6, value=(opc_6 in lista_salva_17_4_2_1), key=f"chk_17421_6_{ano_sel}")

                    selecionados_17_4_2_1 = [
                        opc for chk, opc in zip(
                            [chk_1, chk_2, chk_3, chk_4, chk_5, chk_6],
                            [opc_1, opc_2, opc_3, opc_4, opc_5, opc_6]
                        ) if chk
                    ]
                    string_selecionados_17_4_2_1 = "; ".join(selecionados_17_4_2_1) if selecionados_17_4_2_1 else "Nenhuma medida selecionada"

                with c17421_2:
                    link_17_4_2_1_input = st.text_area(
                        "Link/Evidência das Medidas Assinaladas em Exames (17.4.2.1):",
                        value=l_salvo_17_4_2_1,
                        key=f"reg_17_4_2_1_txt_{ano_sel}",
                        height=250
                    )

                    links_17_4_2_1_visuais = re.findall(REGEX_PURE_URL, link_17_4_2_1_input or "")
                    if links_17_4_2_1_visuais:
                        st.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_17_4_2_1_visuais]
                            )
                        )

                # Chat de comentários
                bloco_comentarios_isaude("17.4.2.1", res_data)

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 17.4.2.1", key=f"btn_salvar_17_4_2_1_{ano_sel}", type="primary"):
                    val_str_17_4_2_1 = string_selecionados_17_4_2_1
                    val_lk_17_4_2_1 = link_17_4_2_1_input.strip()
                    pts_17_4_2_1 = 0.0
                    comentarios_17_4_2_1 = d17_4_2_1.get("comentarios", [])

                    save_resp_isaude(
                        qid="17.4.2.1",
                        valor=val_str_17_4_2_1,
                        pontos=pts_17_4_2_1,
                        link=val_lk_17_4_2_1,
                        comentarios=comentarios_17_4_2_1
                    )

                    # Modal de aviso para links pendentes
                    links_atuais_17_4_2_1 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_17_4_2_1_input or "")]
                    links_antigos_17_4_2_1 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_17_4_2_1 or "")]

                    if (val_str_17_4_2_1 != v_salvo_17_4_2_1 or val_lk_17_4_2_1 != l_salvo_17_4_2_1) and links_atuais_17_4_2_1 and links_atuais_17_4_2_1 != links_antigos_17_4_2_1:
                        st.session_state[f"links_pendentes_17_4_2_1_{ano_sel}"] = links_atuais_17_4_2_1
                        st.session_state[f"gatilho_modal_17_4_2_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 17.4.2.1 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                pts_atuais_17_4_2_1 = d17_4_2_1.get("pontos", 0.0)
                cor_txt_17_4_2_1 = "#28a745" if pts_atuais_17_4_2_1 >= 0.0 else "#dc3545"

                st.markdown(
                    f"<span style='color:{cor_txt_17_4_2_1}; font-weight:bold;'>"
                    f"📊 Pontuação Obtida no Quesito 17.4.2.1: {pts_atuais_17_4_2_1:+.1f} pontos</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 17.4.2.1
        if st.session_state.get(f"gatilho_modal_17_4_2_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("17.4.2.1", st.session_state.get(f"links_pendentes_17_4_2_1_{ano_sel}", []), ano_sel)

        # =============================================================================
        # QUESITO 17.5 • SISTEMA INFORMATIZADO DE REGULAÇÃO
        # =============================================================================
        with st.container(key=f"container_bloco_sistema_regulacao_17_5_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 17.5 - Sistema Informatizado de Regulação na Atenção Especializada ({ano_sel})", expanded=True):
                st.subheader(f"17.5 • Sistema Informatizado de Regulação ({ano_sel})")
                st.write(f"**17.5 O município utiliza sistema informatizado de regulação com oferta dos serviços da Atenção Especializada sob gestão municipal?**")
                st.caption("Nota: Refere-se ao Município como Unidade Demandada - Central de Regulação")
                st.caption("ℹ️ *Selecione a opção, preencha as evidências e clique no botão 'Salvar Quesito 17.5' para registrar.*")

                opts_17_5 = {
                    "Selecione...": 0.0,
                    "Sim, todos os serviços – 00": 0.0,
                    "Sim, a maior parte dos serviços – -01 (perde 01 ponto)": -1.0,
                    "Sim, a menor parte dos serviços – -03 (perde 03 pontos)": -3.0,
                    "Não – -05 (perde 05 pontos)": -5.0
                }

                d17_5 = res_data.get("17.5") or {
                    "valor": "Selecione...",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_17_5 = d17_5.get("valor", "Selecione...")
                l_salvo_17_5 = d17_5.get("link", "")

                c175_1, c175_2 = st.columns([1, 1])
                with c175_1:
                    lista_opcoes_17_5 = list(opts_17_5.keys())
                    idx_salvo_17_5 = lista_opcoes_17_5.index(v_salvo_17_5) if v_salvo_17_5 in opts_17_5 else 0

                    sel_17_5 = st.radio(
                        "Utilização do sistema informatizado:",
                        options=lista_opcoes_17_5,
                        index=idx_salvo_17_5,
                        key=f"reg_17_5_rad_{ano_sel}",
                        label_visibility="collapsed"
                    )

                with c175_2:
                    link_17_5_input = st.text_area(
                        "Link/Evidência do Sistema de Regulação (17.5):",
                        value=l_salvo_17_5,
                        key=f"reg_17_5_txt_{ano_sel}",
                        height=130
                    )

                    links_17_5_visuais = re.findall(REGEX_PURE_URL, link_17_5_input or "")
                    if links_17_5_visuais:
                        st.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_17_5_visuais]
                            )
                        )

                # Chat de comentários
                bloco_comentarios_isaude("17.5", res_data)

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 17.5", key=f"btn_salvar_17_5_{ano_sel}", type="primary"):
                    val_sel_17_5 = sel_17_5 if sel_17_5 is not None else "Selecione..."
                    val_lk_17_5 = link_17_5_input.strip()
                    pts_17_5 = opts_17_5.get(val_sel_17_5, 0.0)
                    comentarios_17_5 = d17_5.get("comentarios", [])

                    save_resp_isaude(
                        qid="17.5",
                        valor=val_sel_17_5,
                        pontos=pts_17_5,
                        link=val_lk_17_5,
                        comentarios=comentarios_17_5
                    )

                    # Modal de aviso para links pendentes
                    links_atuais_17_5 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_17_5_input or "")]
                    links_antigos_17_5 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_17_5 or "")]

                    if (val_sel_17_5 != v_salvo_17_5 or val_lk_17_5 != l_salvo_17_5) and links_atuais_17_5 and links_atuais_17_5 != links_antigos_17_5:
                        st.session_state[f"links_pendentes_17_5_{ano_sel}"] = links_atuais_17_5
                        st.session_state[f"gatilho_modal_17_5_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 17.5 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                pts_atuais_17_5 = d17_5.get("pontos", 0.0)
                cor_txt_17_5 = "#28a745" if pts_atuais_17_5 >= 0.0 else "#dc3545"

                st.markdown(
                    f"<span style='color:{cor_txt_17_5}; font-weight:bold;'>"
                    f"📊 Pontuação Obtida no Quesito 17.5: {pts_atuais_17_5:+.1f} pontos</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 17.5
        if st.session_state.get(f"gatilho_modal_17_5_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("17.5", st.session_state.get(f"links_pendentes_17_5_{ano_sel}", []), ano_sel)


        # =============================================================================
        # QUESITO 17.5.1 • SISTEMAS UTILIZADOS PELA REGULAÇÃO
        # =============================================================================
        with st.container(key=f"container_bloco_sistemas_regulacao_17_5_1_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 17.5.1 - Sistemas Utilizados pela Regulação ({ano_sel})", expanded=True):
                st.subheader(f"17.5.1 • Sistemas Utilizados pela Regulação ({ano_sel})")
                st.write(f"**17.5.1 Assinale os sistemas utilizados pela regulação:**")
                st.caption("ℹ️ *Marque as opções aplicadas, informe o link de evidência e clique no botão 'Salvar Quesito 17.5.1' para registrar.*")

                d17_5_1 = res_data.get("17.5.1") or {
                    "valor": "",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_17_5_1 = d17_5_1.get("valor", "")
                l_salvo_17_5_1 = d17_5_1.get("link", "")
                lista_salva_17_5_1 = [item.strip() for item in v_salvo_17_5_1.split(";")] if v_salvo_17_5_1 else []

                opc_1 = "Portal Cross/SIRESP"
                opc_2 = "SIGA"
                opc_3 = "SISREG"
                opc_4 = "Outros"

                c1751_1, c1751_2 = st.columns([1, 1])

                with c1751_1:
                    st.write("📋 **Selecione os sistemas em uso:**")
                    chk_1 = st.checkbox(opc_1, value=(opc_1 in lista_salva_17_5_1), key=f"chk_1751_1_{ano_sel}")
                    chk_2 = st.checkbox(opc_2, value=(opc_2 in lista_salva_17_5_1), key=f"chk_1751_2_{ano_sel}")
                    chk_3 = st.checkbox(opc_3, value=(opc_3 in lista_salva_17_5_1), key=f"chk_1751_3_{ano_sel}")
                    chk_4 = st.checkbox(opc_4, value=(opc_4 in lista_salva_17_5_1), key=f"chk_1751_4_{ano_sel}")

                    selecionados_17_5_1 = [
                        opc for chk, opc in zip(
                            [chk_1, chk_2, chk_3, chk_4],
                            [opc_1, opc_2, opc_3, opc_4]
                        ) if chk
                    ]
                    string_selecionados_17_5_1 = "; ".join(selecionados_17_5_1) if selecionados_17_5_1 else "Nenhum sistema selecionado"

                with c1751_2:
                    link_17_5_1_input = st.text_area(
                        "Link/Evidência ou especificação dos sistemas (17.5.1):",
                        value=l_salvo_17_5_1,
                        key=f"reg_17_5_1_txt_{ano_sel}",
                        height=180
                    )

                    links_17_5_1_visuais = re.findall(REGEX_PURE_URL, link_17_5_1_input or "")
                    if links_17_5_1_visuais:
                        st.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_17_5_1_visuais]
                            )
                        )

                # Chat de comentários
                bloco_comentarios_isaude("17.5.1", res_data)

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 17.5.1", key=f"btn_salvar_17_5_1_{ano_sel}", type="primary"):
                    val_str_17_5_1 = string_selecionados_17_5_1
                    val_lk_17_5_1 = link_17_5_1_input.strip()
                    pts_17_5_1 = 0.0
                    comentarios_17_5_1 = d17_5_1.get("comentarios", [])

                    save_resp_isaude(
                        qid="17.5.1",
                        valor=val_str_17_5_1,
                        pontos=pts_17_5_1,
                        link=val_lk_17_5_1,
                        comentarios=comentarios_17_5_1
                    )

                    # Modal de aviso para links pendentes
                    links_atuais_17_5_1 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_17_5_1_input or "")]
                    links_antigos_17_5_1 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_17_5_1 or "")]

                    if (val_str_17_5_1 != v_salvo_17_5_1 or val_lk_17_5_1 != l_salvo_17_5_1) and links_atuais_17_5_1 and links_atuais_17_5_1 != links_antigos_17_5_1:
                        st.session_state[f"links_pendentes_17_5_1_{ano_sel}"] = links_atuais_17_5_1
                        st.session_state[f"gatilho_modal_17_5_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 17.5.1 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                pts_atuais_17_5_1 = d17_5_1.get("pontos", 0.0)
                cor_txt_17_5_1 = "#28a745" if pts_atuais_17_5_1 >= 0.0 else "#dc3545"

                st.markdown(
                    f"<span style='color:{cor_txt_17_5_1}; font-weight:bold;'>"
                    f"📊 Pontuação Obtida no Quesito 17.5.1: {pts_atuais_17_5_1:+.1f} pontos</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 17.5.1
        if st.session_state.get(f"gatilho_modal_17_5_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("17.5.1", st.session_state.get(f"links_pendentes_17_5_1_{ano_sel}", []), ano_sel)

        # =============================================================================
        # QUESITO 17.5.2 • LISTA DE ESPERA NO SISTEMA DE REGULAÇÃO
        # =============================================================================
        with st.container(key=f"container_bloco_lista_espera_17_5_2_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 17.5.2 - Conhecimento da Lista de Espera na Atenção Especializada ({ano_sel})", expanded=True):
                st.subheader(f"17.5.2 • Lista de Espera na Regulação ({ano_sel})")
                st.write("**17.5.2 O sistema informatizado de regulação utilizado pelo município permite conhecer a lista de espera (relação nominal de pacientes com tempo de espera) dos serviços da Atenção Especializada sob gestão municipal?**")
                st.caption("ℹ️ *Selecione a opção, preencha as evidências e clique no botão 'Salvar Quesito 17.5.2' para registrar.*")

                opts_17_5_2 = {
                    "Selecione...": 0.0,
                    "Sim, todos os serviços – 00": 0.0,
                    "Sim, a maior parte dos serviços – -01 (perde 01 ponto)": -1.0,
                    "Sim, a menor parte dos serviços – -03 (perde 03 pontos)": -3.0,
                    "Não – -05 (perde 05 pontos)": -5.0
                }

                d17_5_2 = res_data.get("17.5.2") or {
                    "valor": "Selecione...",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_17_5_2 = d17_5_2.get("valor", "Selecione...")
                l_salvo_17_5_2 = d17_5_2.get("link", "")

                c1752_1, c1752_2 = st.columns([1, 1])
                with c1752_1:
                    lista_opcoes_17_5_2 = list(opts_17_5_2.keys())
                    idx_salvo_17_5_2 = lista_opcoes_17_5_2.index(v_salvo_17_5_2) if v_salvo_17_5_2 in opts_17_5_2 else 0

                    sel_17_5_2 = st.radio(
                        "Permite conhecer a lista de espera:",
                        options=lista_opcoes_17_5_2,
                        index=idx_salvo_17_5_2,
                        key=f"reg_17_5_2_rad_{ano_sel}",
                        label_visibility="collapsed"
                    )

                with c1752_2:
                    link_17_5_2_input = st.text_area(
                        "Link/Evidência ou Relatório da Lista de Espera (17.5.2):",
                        value=l_salvo_17_5_2,
                        key=f"reg_17_5_2_txt_{ano_sel}",
                        height=130
                    )

                    links_17_5_2_visuais = re.findall(REGEX_PURE_URL, link_17_5_2_input or "")
                    if links_17_5_2_visuais:
                        st.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_17_5_2_visuais]
                            )
                        )

                # Chat de comentários
                bloco_comentarios_isaude("17.5.2", res_data)

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 17.5.2", key=f"btn_salvar_17_5_2_{ano_sel}", type="primary"):
                    val_sel_17_5_2 = sel_17_5_2 if sel_17_5_2 is not None else "Selecione..."
                    val_lk_17_5_2 = link_17_5_2_input.strip()
                    pts_17_5_2 = opts_17_5_2.get(val_sel_17_5_2, 0.0)
                    comentarios_17_5_2 = d17_5_2.get("comentarios", [])

                    save_resp_isaude(
                        qid="17.5.2",
                        valor=val_sel_17_5_2,
                        pontos=pts_17_5_2,
                        link=val_lk_17_5_2,
                        comentarios=comentarios_17_5_2
                    )

                    # Limpeza automática do filho (17.5.2.1) caso a condição mude
                    if val_sel_17_5_2 != "Sim, todos os serviços – 00":
                        d17_5_2_1_atual = res_data.get("17.5.2.1") or {"valor": "", "pontos": 0.0, "link": "", "comentarios": []}
                        save_resp_isaude(
                            qid="17.5.2.1",
                            valor="",
                            pontos=0.0,
                            link=d17_5_2_1_atual.get("link", ""),
                            comentarios=d17_5_2_1_atual.get("comentarios", [])
                        )

                    # Modal de aviso para links pendentes
                    links_atuais_17_5_2 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_17_5_2_input or "")]
                    links_antigos_17_5_2 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_17_5_2 or "")]

                    if (val_sel_17_5_2 != v_salvo_17_5_2 or val_lk_17_5_2 != l_salvo_17_5_2) and links_atuais_17_5_2 and links_atuais_17_5_2 != links_antigos_17_5_2:
                        st.session_state[f"links_pendentes_17_5_2_{ano_sel}"] = links_atuais_17_5_2
                        st.session_state[f"gatilho_modal_17_5_2_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 17.5.2 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                pts_atuais_17_5_2 = d17_5_2.get("pontos", 0.0)
                cor_txt_17_5_2 = "#28a745" if pts_atuais_17_5_2 >= 0.0 else "#dc3545"

                st.markdown(
                    f"<span style='color:{cor_txt_17_5_2}; font-weight:bold;'>"
                    f"📊 Pontuação Obtida no Quesito 17.5.2: {pts_atuais_17_5_2:+.1f} pontos</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 17.5.2
        if st.session_state.get(f"gatilho_modal_17_5_2_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("17.5.2", st.session_state.get(f"links_pendentes_17_5_2_{ano_sel}", []), ano_sel)


        # =============================================================================
        # QUESITO 17.5.2.1 • ROL DE SERVIÇOS NO SISTEMA DE REGULAÇÃO
        # =============================================================================
        with st.container(key=f"container_bloco_rol_servicos_17_5_2_1_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 17.5.2.1 - Rol de Serviços no Sistema de Regulação ({ano_sel})", expanded=True):
                st.subheader(f"17.5.2.1 • Rol de Serviços no Sistema de Regulação ({ano_sel})")
                st.write(f"**17.5.2.1 Assinale os serviços da Atenção Especializada inseridos no sistema de regulação:**")
                st.caption("ℹ️ *Marque os serviços disponíveis, preencha as evidências e clique no botão 'Salvar Quesito 17.5.2.1' para registrar.*")

                d17_5_2_1 = res_data.get("17.5.2.1") or {
                    "valor": "",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_17_5_2_1 = d17_5_2_1.get("valor", "")
                l_salvo_17_5_2_1 = d17_5_2_1.get("link", "")
                lista_salva_17_5_2_1 = [item.strip() for item in v_salvo_17_5_2_1.split(";")] if v_salvo_17_5_2_1 else []

                opc_1 = "Consultas por especialidade"
                opc_2 = "Exames"
                opc_3 = "Terapias / tratamentos"
                opc_4 = "OPM"
                opc_5 = "Cirurgias eletivas"
                opc_6 = "Outros"

                c17521_1, c17521_2 = st.columns([1, 1])

                with c17521_1:
                    st.write("📋 **Selecione os serviços inseridos:**")
                    chk_1 = st.checkbox(opc_1, value=(opc_1 in lista_salva_17_5_2_1), key=f"chk_17521_1_{ano_sel}")
                    chk_2 = st.checkbox(opc_2, value=(opc_2 in lista_salva_17_5_2_1), key=f"chk_17521_2_{ano_sel}")
                    chk_3 = st.checkbox(opc_3, value=(opc_3 in lista_salva_17_5_2_1), key=f"chk_17521_3_{ano_sel}")
                    chk_4 = st.checkbox(opc_4, value=(opc_4 in lista_salva_17_5_2_1), key=f"chk_17521_4_{ano_sel}")
                    chk_5 = st.checkbox(opc_5, value=(opc_5 in lista_salva_17_5_2_1), key=f"chk_17521_5_{ano_sel}")
                    chk_6 = st.checkbox(opc_6, value=(opc_6 in lista_salva_17_5_2_1), key=f"chk_17521_6_{ano_sel}")

                    selecionados_17_5_2_1 = []
                    if chk_1: selecionados_17_5_2_1.append(opc_1)
                    if chk_2: selecionados_17_5_2_1.append(opc_2)
                    if chk_3: selecionados_17_5_2_1.append(opc_3)
                    if chk_4: selecionados_17_5_2_1.append(opc_4)
                    if chk_5: selecionados_17_5_2_1.append(opc_5)
                    if chk_6: selecionados_17_5_2_1.append(opc_6)

                    # Lógica de Pontuação baseada na resposta pai (17.5.2)
                    resposta_pai = res_data.get("17.5.2", {}).get("valor", "")
                    resposta_pai_todos_servicos = (resposta_pai == "Sim, todos os serviços – 00")

                    if resposta_pai_todos_servicos:
                        pontos_calc = -5.0
                        if chk_1: pontos_calc += 1.0
                        if chk_2: pontos_calc += 1.0
                        if chk_3: pontos_calc += 1.0
                        if chk_4: pontos_calc += 1.0
                        if chk_5: pontos_calc += 1.0
                        pts_17_5_2_1 = pontos_calc
                    else:
                        pts_17_5_2_1 = 0.0

                    string_selecionados_17_5_2_1 = "; ".join(selecionados_17_5_2_1) if selecionados_17_5_2_1 else ""

                with c17521_2:
                    link_17_5_2_1_input = st.text_area(
                        "Link/Evidência dos Serviços Regulados (17.5.2.1):",
                        value=l_salvo_17_5_2_1,
                        key=f"reg_17_5_2_1_txt_{ano_sel}",
                        height=250
                    )

                    links_17_5_2_1_visuais = re.findall(REGEX_PURE_URL, link_17_5_2_1_input or "")
                    if links_17_5_2_1_visuais:
                        st.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_17_5_2_1_visuais]
                            )
                        )

                # Chat de comentários
                bloco_comentarios_isaude("17.5.2.1", res_data)

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 17.5.2.1", key=f"btn_salvar_17_5_2_1_{ano_sel}", type="primary"):
                    val_str_17_5_2_1 = string_selecionados_17_5_2_1
                    val_lk_17_5_2_1 = link_17_5_2_1_input.strip()
                    comentarios_17_5_2_1 = d17_5_2_1.get("comentarios", [])

                    save_resp_isaude(
                        qid="17.5.2.1",
                        valor=val_str_17_5_2_1,
                        pontos=pts_17_5_2_1,
                        link=val_lk_17_5_2_1,
                        comentarios=comentarios_17_5_2_1
                    )

                    # Modal de aviso para links pendentes
                    links_atuais_17_5_2_1 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_17_5_2_1_input or "")]
                    links_antigos_17_5_2_1 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_17_5_2_1 or "")]

                    if (val_str_17_5_2_1 != v_salvo_17_5_2_1 or val_lk_17_5_2_1 != l_salvo_17_5_2_1) and links_atuais_17_5_2_1 and links_atuais_17_5_2_1 != links_antigos_17_5_2_1:
                        st.session_state[f"links_pendentes_17_5_2_1_{ano_sel}"] = links_atuais_17_5_2_1
                        st.session_state[f"gatilho_modal_17_5_2_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 17.5.2.1 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                pts_atuais_17_5_2_1 = d17_5_2_1.get("pontos", 0.0)
                cor_txt_17_5_2_1 = "#28a745" if pts_atuais_17_5_2_1 >= 0.0 else "#dc3545"

                st.markdown(
                    f"<span style='color:{cor_txt_17_5_2_1}; font-weight:bold;'>"
                    f"📊 Pontuação Obtida no Quesito 17.5.2.1: {pts_atuais_17_5_2_1:+.1f} pontos</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 17.5.2.1
        if st.session_state.get(f"gatilho_modal_17_5_2_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("17.5.2.1", st.session_state.get(f"links_pendentes_17_5_2_1_{ano_sel}", []), ano_sel)

        # =============================================================================
        # QUESITO 17.5.2.1.1 • 3 CONSULTAS COM MAIOR TEMPO DE ESPERA
        # =============================================================================
        with st.container(key=f"container_bloco_maior_espera_consultas_17_5_2_1_1_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 17.5.2.1.1 - Consultas com Maior Tempo de Espera ({ano_sel})", expanded=True):
                st.subheader(f"17.5.2.1.1 • Consultas com Maior Tempo de Espera ({ano_sel})")
                st.write(f"**17.5.2.1.1 Informe as 3 consultas médicas com maior tempo de espera na Atenção Especializada:**")
                st.caption("ℹ️ *Preencha os campos abaixo, informe o link de evidência e clique no botão 'Salvar Quesito 17.5.2.1.1' para registrar.*")

                d17_5_2_1_1 = res_data.get("17.5.2.1.1") or {
                    "valor": "",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_17_5_2_1_1 = d17_5_2_1_1.get("valor", "")
                l_salvo_17_5_2_1_1 = d17_5_2_1_1.get("link", "")

                partes_1_1 = v_salvo_17_5_2_1_1.split("||") if v_salvo_17_5_2_1_1 else []
                p1 = partes_1_1[0].split("|") if len(partes_1_1) > 0 else ["", ""]
                p2 = partes_1_1[1].split("|") if len(partes_1_1) > 1 else ["", ""]
                p3 = partes_1_1[2].split("|") if len(partes_1_1) > 2 else ["", ""]

                c175211_1, c175211_2 = st.columns([1, 1])

                with c175211_1:
                    st.write("🩺 **Especialidades Médicas e Prazos:**")
                    
                    esp_1 = st.text_input("1ª - Descrição da especialidade médica:", value=p1[0] if len(p1) > 0 else "", key=f"esp1_175211_{ano_sel}")
                    dias_1 = st.text_input("1ª - Tempo médio de espera (em dias):", value=p1[1] if len(p1) > 1 else "", key=f"dias1_175211_{ano_sel}")
                    
                    st.markdown("---")
                    
                    esp_2 = st.text_input("2ª - Descrição da especialidade médica:", value=p2[0] if len(p2) > 0 else "", key=f"esp2_175211_{ano_sel}")
                    dias_2 = st.text_input("2ª - Tempo médio de espera (em dias):", value=p2[1] if len(p2) > 1 else "", key=f"dias2_175211_{ano_sel}")
                    
                    st.markdown("---")
                    
                    esp_3 = st.text_input("3ª - Descrição da especialidade médica:", value=p3[0] if len(p3) > 0 else "", key=f"esp3_175211_{ano_sel}")
                    dias_3 = st.text_input("3ª - Tempo médio de espera (em dias):", value=p3[1] if len(p3) > 1 else "", key=f"dias3_175211_{ano_sel}")

                    string_estruturada_1_1 = f"{esp_1.strip()}|{dias_1.strip()}||{esp_2.strip()}|{dias_2.strip()}||{esp_3.strip()}|{dias_3.strip()}"
                    if string_estruturada_1_1 == "||||":
                        string_estruturada_1_1 = ""

                    pts_17_5_2_1_1 = 0.0

                with c175211_2:
                    link_17_5_2_1_1_input = st.text_area(
                        "Link/Evidência ou Relatório estatístico dos tempos de espera (17.5.2.1.1):",
                        value=l_salvo_17_5_2_1_1,
                        key=f"reg_17_5_2_1_1_txt_{ano_sel}",
                        height=280
                    )

                    links_17_5_2_1_1_visuais = re.findall(REGEX_PURE_URL, link_17_5_2_1_1_input or "")
                    if links_17_5_2_1_1_visuais:
                        st.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_17_5_2_1_1_visuais]
                            )
                        )

                # Chat de comentários
                bloco_comentarios_isaude("17.5.2.1.1", res_data)

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 17.5.2.1.1", key=f"btn_salvar_17_5_2_1_1_{ano_sel}", type="primary"):
                    val_str_17_5_2_1_1 = string_estruturada_1_1
                    val_lk_17_5_2_1_1 = link_17_5_2_1_1_input.strip()
                    comentarios_17_5_2_1_1 = d17_5_2_1_1.get("comentarios", [])

                    save_resp_isaude(
                        qid="17.5.2.1.1",
                        valor=val_str_17_5_2_1_1,
                        pontos=pts_17_5_2_1_1,
                        link=val_lk_17_5_2_1_1,
                        comentarios=comentarios_17_5_2_1_1
                    )

                    # Modal de aviso para links pendentes
                    links_atuais_17_5_2_1_1 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_17_5_2_1_1_input or "")]
                    links_antigos_17_5_2_1_1 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_17_5_2_1_1 or "")]

                    if (val_str_17_5_2_1_1 != v_salvo_17_5_2_1_1 or val_lk_17_5_2_1_1 != l_salvo_17_5_2_1_1) and links_atuais_17_5_2_1_1 and links_atuais_17_5_2_1_1 != links_antigos_17_5_2_1_1:
                        st.session_state[f"links_pendentes_17_5_2_1_1_{ano_sel}"] = links_atuais_17_5_2_1_1
                        st.session_state[f"gatilho_modal_17_5_2_1_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 17.5.2.1.1 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                pts_atuais_17_5_2_1_1 = d17_5_2_1_1.get("pontos", 0.0)
                cor_txt_17_5_2_1_1 = "#28a745" if pts_atuais_17_5_2_1_1 >= 0.0 else "#dc3545"

                st.markdown(
                    f"<span style='color:{cor_txt_17_5_2_1_1}; font-weight:bold;'>"
                    f"📊 Pontuação Obtida no Quesito 17.5.2.1.1: {pts_atuais_17_5_2_1_1:+.1f} pontos (Dados Informativos)</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 17.5.2.1.1
        if st.session_state.get(f"gatilho_modal_17_5_2_1_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("17.5.2.1.1", st.session_state.get(f"links_pendentes_17_5_2_1_1_{ano_sel}", []), ano_sel)

        # =============================================================================
        # QUESITO 17.5.2.1.2 • 3 EXAMES COM MAIOR TEMPO DE ESPERA
        # =============================================================================
        with st.container(key=f"container_bloco_maior_espera_exames_17_5_2_1_2_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 17.5.2.1.2 - Exames com Maior Tempo de Espera ({ano_sel})", expanded=True):
                st.subheader(f"17.5.2.1.2 • Exames com Maior Tempo de Espera ({ano_sel})")
                st.write(f"**17.5.2.1.2 Informe os 3 exames médicos com maior tempo de espera na Atenção Especializada:**")
                st.caption("ℹ️ *Preencha os campos abaixo, informe o link de evidência e clique no botão 'Salvar Quesito 17.5.2.1.2' para registrar.*")

                d17_5_2_1_2 = res_data.get("17.5.2.1.2") or {
                    "valor": "",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_17_5_2_1_2 = d17_5_2_1_2.get("valor", "")
                l_salvo_17_5_2_1_2 = d17_5_2_1_2.get("link", "")

                partes_1_2 = v_salvo_17_5_2_1_2.split("||") if v_salvo_17_5_2_1_2 else []
                e1 = partes_1_2[0].split("|") if len(partes_1_2) > 0 else ["", ""]
                e2 = partes_1_2[1].split("|") if len(partes_1_2) > 1 else ["", ""]
                e3 = partes_1_2[2].split("|") if len(partes_1_2) > 2 else ["", ""]

                c175212_1, c175212_2 = st.columns([1, 1])

                with c175212_1:
                    st.write("🔬 **Exames e Prazos:**")
                    
                    ex_1 = st.text_input("1º - Descrição do exame médico:", value=e1[0] if len(e1) > 0 else "", key=f"ex1_175212_{ano_sel}")
                    ex_dias_1 = st.text_input("1º - Tempo médio de espera (em dias):", value=e1[1] if len(e1) > 1 else "", key=f"ex_dias1_175212_{ano_sel}")
                    
                    st.markdown("---")
                    
                    ex_2 = st.text_input("2º - Descrição do exame médico:", value=e2[0] if len(e2) > 0 else "", key=f"ex2_175212_{ano_sel}")
                    ex_dias_2 = st.text_input("2º - Tempo médio de espera (em dias):", value=e2[1] if len(e2) > 1 else "", key=f"ex_dias2_175212_{ano_sel}")
                    
                    st.markdown("---")
                    
                    ex_3 = st.text_input("3º - Descrição do exame médico:", value=e3[0] if len(e3) > 0 else "", key=f"ex3_175212_{ano_sel}")
                    ex_dias_3 = st.text_input("3º - Tempo médio de espera (em dias):", value=e3[1] if len(e3) > 1 else "", key=f"ex_dias3_175212_{ano_sel}")

                    string_estruturada_1_2 = f"{ex_1.strip()}|{ex_dias_1.strip()}||{ex_2.strip()}|{ex_dias_2.strip()}||{ex_3.strip()}|{ex_dias_3.strip()}"
                    if string_estruturada_1_2 == "||||":
                        string_estruturada_1_2 = ""

                    pts_17_5_2_1_2 = 0.0

                with c175212_2:
                    link_17_5_2_1_2_input = st.text_area(
                        "Link/Evidência ou Relatório estatístico dos tempos de espera de exames (17.5.2.1.2):",
                        value=l_salvo_17_5_2_1_2,
                        key=f"reg_17_5_2_1_2_txt_{ano_sel}",
                        height=280
                    )

                    links_17_5_2_1_2_visuais = re.findall(REGEX_PURE_URL, link_17_5_2_1_2_input or "")
                    if links_17_5_2_1_2_visuais:
                        st.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_17_5_2_1_2_visuais]
                            )
                        )

                # Chat de comentários
                bloco_comentarios_isaude("17.5.2.1.2", res_data)

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 17.5.2.1.2", key=f"btn_salvar_17_5_2_1_2_{ano_sel}", type="primary"):
                    val_str_17_5_2_1_2 = string_estruturada_1_2
                    val_lk_17_5_2_1_2 = link_17_5_2_1_2_input.strip()
                    comentarios_17_5_2_1_2 = d17_5_2_1_2.get("comentarios", [])

                    save_resp_isaude(
                        qid="17.5.2.1.2",
                        valor=val_str_17_5_2_1_2,
                        pontos=pts_17_5_2_1_2,
                        link=val_lk_17_5_2_1_2,
                        comentarios=comentarios_17_5_2_1_2
                    )

                    # Modal de aviso para links pendentes
                    links_atuais_17_5_2_1_2 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_17_5_2_1_2_input or "")]
                    links_antigos_17_5_2_1_2 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_17_5_2_1_2 or "")]

                    if (val_str_17_5_2_1_2 != v_salvo_17_5_2_1_2 or val_lk_17_5_2_1_2 != l_salvo_17_5_2_1_2) and links_atuais_17_5_2_1_2 and links_atuais_17_5_2_1_2 != links_antigos_17_5_2_1_2:
                        st.session_state[f"links_pendentes_17_5_2_1_2_{ano_sel}"] = links_atuais_17_5_2_1_2
                        st.session_state[f"gatilho_modal_17_5_2_1_2_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 17.5.2.1.2 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                pts_atuais_17_5_2_1_2 = d17_5_2_1_2.get("pontos", 0.0)
                cor_txt_17_5_2_1_2 = "#28a745" if pts_atuais_17_5_2_1_2 >= 0.0 else "#dc3545"

                st.markdown(
                    f"<span style='color:{cor_txt_17_5_2_1_2}; font-weight:bold;'>"
                    f"📊 Pontuação Obtida no Quesito 17.5.2.1.2: {pts_atuais_17_5_2_1_2:+.1f} pontos (Dados Informativos)</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 17.5.2.1.2
        if st.session_state.get(f"gatilho_modal_17_5_2_1_2_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("17.5.2.1.2", st.session_state.get(f"links_pendentes_17_5_2_1_2_{ano_sel}", []), ano_sel)

        # =============================================================================
        # QUESITO 17.5.2.1.3 • 3 TERAPIAS/TRATAMENTOS COM MAIOR TEMPO DE ESPERA
        # =============================================================================
        with st.container(key=f"container_bloco_maior_espera_terapias_17_5_2_1_3_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 17.5.2.1.3 - Terapias/Tratamentos com Maior Tempo de Espera ({ano_sel})", expanded=True):
                st.subheader(f"17.5.2.1.3 • Terapias/Tratamentos com Maior Tempo de Espera ({ano_sel})")
                st.write(f"**17.5.2.1.3 Informe as 3 terapias/tratamentos médicos com maior tempo de espera na Atenção Especializada:**")
                st.caption("ℹ️ *Preencha os campos abaixo, informe o link de evidência e clique no botão 'Salvar Quesito 17.5.2.1.3' para registrar.*")

                d17_5_2_1_3 = res_data.get("17.5.2.1.3") or {
                    "valor": "",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_17_5_2_1_3 = d17_5_2_1_3.get("valor", "")
                l_salvo_17_5_2_1_3 = d17_5_2_1_3.get("link", "")

                partes_1_3 = v_salvo_17_5_2_1_3.split("||") if v_salvo_17_5_2_1_3 else []
                t1 = partes_1_3[0].split("|") if len(partes_1_3) > 0 else ["", ""]
                t2 = partes_1_3[1].split("|") if len(partes_1_3) > 1 else ["", ""]
                t3 = partes_1_3[2].split("|") if len(partes_1_3) > 2 else ["", ""]

                c175213_1, c175213_2 = st.columns([1, 1])

                with c175213_1:
                    st.write("💆‍♂️ **Terapias / Tratamentos e Prazos:**")
                    
                    ter_1 = st.text_input("1ª - Descrição da terapia/ tratamento médico:", value=t1[0] if len(t1) > 0 else "", key=f"ter1_175213_{ano_sel}")
                    ter_dias_1 = st.text_input("1ª - Tempo médio de espera (em dias):", value=t1[1] if len(t1) > 1 else "", key=f"ter_dias1_175213_{ano_sel}")
                    
                    st.markdown("---")
                    
                    ter_2 = st.text_input("2ª - Descrição da terapia/ tratamento médico:", value=t2[0] if len(t2) > 0 else "", key=f"ter2_175213_{ano_sel}")
                    ter_dias_2 = st.text_input("2ª - Tempo médio de espera (em dias):", value=t2[1] if len(t2) > 1 else "", key=f"ter_dias2_175213_{ano_sel}")
                    
                    st.markdown("---")
                    
                    ter_3 = st.text_input("3ª - Descrição da terapia/ tratamento médico:", value=t3[0] if len(t3) > 0 else "", key=f"ter3_175213_{ano_sel}")
                    ter_dias_3 = st.text_input("3ª - Tempo médio de espera (em dias):", value=t3[1] if len(t3) > 1 else "", key=f"ter_dias3_175213_{ano_sel}")

                    string_estruturada_1_3 = f"{ter_1.strip()}|{ter_dias_1.strip()}||{ter_2.strip()}|{ter_dias_2.strip()}||{ter_3.strip()}|{ter_dias_3.strip()}"
                    if string_estruturada_1_3 == "||||":
                        string_estruturada_1_3 = ""

                    pts_17_5_2_1_3 = 0.0

                with c175213_2:
                    link_17_5_2_1_3_input = st.text_area(
                        "Link/Evidência ou Relatório estatístico dos tempos de espera de terapias (17.5.2.1.3):",
                        value=l_salvo_17_5_2_1_3,
                        key=f"reg_17_5_2_1_3_txt_{ano_sel}",
                        height=280
                    )

                    links_17_5_2_1_3_visuais = re.findall(REGEX_PURE_URL, link_17_5_2_1_3_input or "")
                    if links_17_5_2_1_3_visuais:
                        st.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_17_5_2_1_3_visuais]
                            )
                        )

                # Chat de comentários
                bloco_comentarios_isaude("17.5.2.1.3", res_data)

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 17.5.2.1.3", key=f"btn_salvar_17_5_2_1_3_{ano_sel}", type="primary"):
                    val_str_17_5_2_1_3 = string_estruturada_1_3
                    val_lk_17_5_2_1_3 = link_17_5_2_1_3_input.strip()
                    comentarios_17_5_2_1_3 = d17_5_2_1_3.get("comentarios", [])

                    save_resp_isaude(
                        qid="17.5.2.1.3",
                        valor=val_str_17_5_2_1_3,
                        pontos=pts_17_5_2_1_3,
                        link=val_lk_17_5_2_1_3,
                        comentarios=comentarios_17_5_2_1_3
                    )

                    # Modal de aviso para links pendentes
                    links_atuais_17_5_2_1_3 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_17_5_2_1_3_input or "")]
                    links_antigos_17_5_2_1_3 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_17_5_2_1_3 or "")]

                    if (val_str_17_5_2_1_3 != v_salvo_17_5_2_1_3 or val_lk_17_5_2_1_3 != l_salvo_17_5_2_1_3) and links_atuais_17_5_2_1_3 and links_atuais_17_5_2_1_3 != links_antigos_17_5_2_1_3:
                        st.session_state[f"links_pendentes_17_5_2_1_3_{ano_sel}"] = links_atuais_17_5_2_1_3
                        st.session_state[f"gatilho_modal_17_5_2_1_3_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 17.5.2.1.3 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                pts_atuais_17_5_2_1_3 = d17_5_2_1_3.get("pontos", 0.0)
                cor_txt_17_5_2_1_3 = "#28a745" if pts_atuais_17_5_2_1_3 >= 0.0 else "#dc3545"

                st.markdown(
                    f"<span style='color:{cor_txt_17_5_2_1_3}; font-weight:bold;'>"
                    f"📊 Pontuação Obtida no Quesito 17.5.2.1.3: {pts_atuais_17_5_2_1_3:+.1f} pontos (Dados Informativos)</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 17.5.2.1.3
        if st.session_state.get(f"gatilho_modal_17_5_2_1_3_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("17.5.2.1.3", st.session_state.get(f"links_pendentes_17_5_2_1_3_{ano_sel}", []), ano_sel)

        # =============================================================================
        # QUESITO 17.5.2.1.4 • 3 OPM COM MAIOR TEMPO DE ESPERA
        # =============================================================================
        with st.container(key=f"container_bloco_maior_espera_opm_17_5_2_1_4_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 17.5.2.1.4 - OPM com Maior Tempo de Espera ({ano_sel})", expanded=True):
                st.subheader(f"17.5.2.1.4 • OPM com Maior Tempo de Espera ({ano_sel})")
                st.write(f"**17.5.2.1.4 Informe as 3 OPM (Órteses, Próteses e Materiais Especiais) com maior tempo de espera na Atenção Especializada:**")
                st.caption("ℹ️ *Preencha os campos abaixo, informe o link de evidência e clique no botão 'Salvar Quesito 17.5.2.1.4' para registrar.*")

                d17_5_2_1_4 = res_data.get("17.5.2.1.4") or {
                    "valor": "",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_17_5_2_1_4 = d17_5_2_1_4.get("valor", "")
                l_salvo_17_5_2_1_4 = d17_5_2_1_4.get("link", "")

                partes_opm = v_salvo_17_5_2_1_4.split("||") if v_salvo_17_5_2_1_4 else []
                o1 = partes_opm[0].split("|") if len(partes_opm) > 0 else ["", ""]
                o2 = partes_opm[1].split("|") if len(partes_opm) > 1 else ["", ""]
                o3 = partes_opm[2].split("|") if len(partes_opm) > 2 else ["", ""]

                c175214_1, c175214_2 = st.columns([1, 1])

                with c175214_1:
                    st.write("🦿 **OPM e Prazos:**")
                    
                    opm_1 = st.text_input("1ª - Descrição da OPM:", value=o1[0] if len(o1) > 0 else "", key=f"opm1_175214_{ano_sel}")
                    opm_dias_1 = st.text_input("1ª - Tempo médio de espera (em dias):", value=o1[1] if len(o1) > 1 else "", key=f"opm_dias1_175214_{ano_sel}")
                    
                    st.markdown("---")
                    
                    opm_2 = st.text_input("2ª - Descrição da OPM:", value=o2[0] if len(o2) > 0 else "", key=f"opm2_175214_{ano_sel}")
                    opm_dias_2 = st.text_input("2ª - Tempo médio de espera (em dias):", value=o2[1] if len(o2) > 1 else "", key=f"opm_dias2_175214_{ano_sel}")
                    
                    st.markdown("---")
                    
                    opm_3 = st.text_input("3ª - Descrição da OPM:", value=o3[0] if len(o3) > 0 else "", key=f"opm3_175214_{ano_sel}")
                    opm_dias_3 = st.text_input("3ª - Tempo médio de espera (em dias):", value=o3[1] if len(o3) > 1 else "", key=f"opm_dias3_175214_{ano_sel}")

                    string_estruturada_opm = f"{opm_1.strip()}|{opm_dias_1.strip()}||{opm_2.strip()}|{opm_dias_2.strip()}||{opm_3.strip()}|{opm_dias_3.strip()}"
                    if string_estruturada_opm == "||||":
                        string_estruturada_opm = ""

                    pts_17_5_2_1_4 = 0.0

                with c175214_2:
                    link_17_5_2_1_4_input = st.text_area(
                        "Link/Evidência ou Relatório estatístico dos tempos de espera de OPM (17.5.2.1.4):",
                        value=l_salvo_17_5_2_1_4,
                        key=f"reg_17_5_2_1_4_txt_{ano_sel}",
                        height=280
                    )

                    links_17_5_2_1_4_visuais = re.findall(REGEX_PURE_URL, link_17_5_2_1_4_input or "")
                    if links_17_5_2_1_4_visuais:
                        st.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_17_5_2_1_4_visuais]
                            )
                        )

                # Chat de comentários
                bloco_comentarios_isaude("17.5.2.1.4", res_data)

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 17.5.2.1.4", key=f"btn_salvar_17_5_2_1_4_{ano_sel}", type="primary"):
                    val_str_17_5_2_1_4 = string_estruturada_opm
                    val_lk_17_5_2_1_4 = link_17_5_2_1_4_input.strip()
                    comentarios_17_5_2_1_4 = d17_5_2_1_4.get("comentarios", [])

                    save_resp_isaude(
                        qid="17.5.2.1.4",
                        valor=val_str_17_5_2_1_4,
                        pontos=pts_17_5_2_1_4,
                        link=val_lk_17_5_2_1_4,
                        comentarios=comentarios_17_5_2_1_4
                    )

                    # Modal de aviso para links pendentes
                    links_atuais_17_5_2_1_4 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_17_5_2_1_4_input or "")]
                    links_antigos_17_5_2_1_4 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_17_5_2_1_4 or "")]

                    if (val_str_17_5_2_1_4 != v_salvo_17_5_2_1_4 or val_lk_17_5_2_1_4 != l_salvo_17_5_2_1_4) and links_atuais_17_5_2_1_4 and links_atuais_17_5_2_1_4 != links_antigos_17_5_2_1_4:
                        st.session_state[f"links_pendentes_17_5_2_1_4_{ano_sel}"] = links_atuais_17_5_2_1_4
                        st.session_state[f"gatilho_modal_17_5_2_1_4_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 17.5.2.1.4 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                pts_atuais_17_5_2_1_4 = d17_5_2_1_4.get("pontos", 0.0)
                cor_txt_17_5_2_1_4 = "#28a745" if pts_atuais_17_5_2_1_4 >= 0.0 else "#dc3545"

                st.markdown(
                    f"<span style='color:{cor_txt_17_5_2_1_4}; font-weight:bold;'>"
                    f"📊 Pontuação Obtida no Quesito 17.5.2.1.4: {pts_atuais_17_5_2_1_4:+.1f} pontos (Dados Informativos)</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 17.5.2.1.4
        if st.session_state.get(f"gatilho_modal_17_5_2_1_4_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("17.5.2.1.4", st.session_state.get(f"links_pendentes_17_5_2_1_4_{ano_sel}", []), ano_sel)

        # =============================================================================
        # QUESITO 17.5.2.1.5 • 3 CIRURGIAS ELETIVAS COM MAIOR TEMPO DE ESPERA
        # =============================================================================
        with st.container(key=f"container_bloco_maior_espera_cirurgias_17_5_2_1_5_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 17.5.2.1.5 - Cirurgias Eletivas com Maior Tempo de Espera ({ano_sel})", expanded=True):
                st.subheader(f"17.5.2.1.5 • Cirurgias Eletivas com Maior Tempo de Espera ({ano_sel})")
                st.write(f"**17.5.2.1.5 Informe as 3 cirurgias eletivas com maior tempo de espera na Atenção Especializada:**")
                st.caption("ℹ️ *Preencha os campos abaixo, informe o link de evidência e clique no botão 'Salvar Quesito 17.5.2.1.5' para registrar.*")

                d17_5_2_1_5 = res_data.get("17.5.2.1.5") or {
                    "valor": "",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_17_5_2_1_5 = d17_5_2_1_5.get("valor", "")
                l_salvo_17_5_2_1_5 = d17_5_2_1_5.get("link", "")

                partes_cir = v_salvo_17_5_2_1_5.split("||") if v_salvo_17_5_2_1_5 else []
                c1 = partes_cir[0].split("|") if len(partes_cir) > 0 else ["", ""]
                c2 = partes_cir[1].split("|") if len(partes_cir) > 1 else ["", ""]
                c3 = partes_cir[2].split("|") if len(partes_cir) > 2 else ["", ""]

                c175215_1, c175215_2 = st.columns([1, 1])

                with c175215_1:
                    st.write("🏥 **Cirurgias Eletivas e Prazos:**")
                    
                    cir_1 = st.text_input("1ª - Descrição da cirurgia eletiva:", value=c1[0] if len(c1) > 0 else "", key=f"cir1_175215_{ano_sel}")
                    cir_dias_1 = st.text_input("1ª - Tempo médio de espera (em dias):", value=c1[1] if len(c1) > 1 else "", key=f"cir_dias1_175215_{ano_sel}")
                    
                    st.markdown("---")
                    
                    cir_2 = st.text_input("2ª - Descrição da cirurgia eletiva:", value=c2[0] if len(c2) > 0 else "", key=f"cir2_175215_{ano_sel}")
                    cir_dias_2 = st.text_input("2ª - Tempo médio de espera (em dias):", value=c2[1] if len(c2) > 1 else "", key=f"cir_dias2_175215_{ano_sel}")
                    
                    st.markdown("---")
                    
                    cir_3 = st.text_input("3ª - Descrição da cirurgia eletiva:", value=c3[0] if len(c3) > 0 else "", key=f"cir3_175215_{ano_sel}")
                    cir_dias_3 = st.text_input("3ª - Tempo médio de espera (em dias):", value=c3[1] if len(c3) > 1 else "", key=f"cir_dias3_175215_{ano_sel}")

                    string_estruturada_cir = f"{cir_1.strip()}|{cir_dias_1.strip()}||{cir_2.strip()}|{cir_dias_2.strip()}||{cir_3.strip()}|{cir_dias_3.strip()}"
                    if string_estruturada_cir == "||||":
                        string_estruturada_cir = ""

                    pts_17_5_2_1_5 = 0.0

                with c175215_2:
                    link_17_5_2_1_5_input = st.text_area(
                        "Link/Evidência ou Relatório estatístico dos tempos de espera de cirurgias (17.5.2.1.5):",
                        value=l_salvo_17_5_2_1_5,
                        key=f"reg_17_5_2_1_5_txt_{ano_sel}",
                        height=280
                    )

                    links_17_5_2_1_5_visuais = re.findall(REGEX_PURE_URL, link_17_5_2_1_5_input or "")
                    if links_17_5_2_1_5_visuais:
                        st.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_17_5_2_1_5_visuais]
                            )
                        )

                # Chat de comentários
                bloco_comentarios_isaude("17.5.2.1.5", res_data)

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 17.5.2.1.5", key=f"btn_salvar_17_5_2_1_5_{ano_sel}", type="primary"):
                    val_str_17_5_2_1_5 = string_estruturada_cir
                    val_lk_17_5_2_1_5 = link_17_5_2_1_5_input.strip()
                    comentarios_17_5_2_1_5 = d17_5_2_1_5.get("comentarios", [])

                    save_resp_isaude(
                        qid="17.5.2.1.5",
                        valor=val_str_17_5_2_1_5,
                        pontos=pts_17_5_2_1_5,
                        link=val_lk_17_5_2_1_5,
                        comentarios=comentarios_17_5_2_1_5
                    )

                    # Modal de aviso para links pendentes
                    links_atuais_17_5_2_1_5 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_17_5_2_1_5_input or "")]
                    links_antigos_17_5_2_1_5 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_17_5_2_1_5 or "")]

                    if (val_str_17_5_2_1_5 != v_salvo_17_5_2_1_5 or val_lk_17_5_2_1_5 != l_salvo_17_5_2_1_5) and links_atuais_17_5_2_1_5 and links_atuais_17_5_2_1_5 != links_antigos_17_5_2_1_5:
                        st.session_state[f"links_pendentes_17_5_2_1_5_{ano_sel}"] = links_atuais_17_5_2_1_5
                        st.session_state[f"gatilho_modal_17_5_2_1_5_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 17.5.2.1.5 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                pts_atuais_17_5_2_1_5 = d17_5_2_1_5.get("pontos", 0.0)
                cor_txt_17_5_2_1_5 = "#28a745" if pts_atuais_17_5_2_1_5 >= 0.0 else "#dc3545"

                st.markdown(
                    f"<span style='color:{cor_txt_17_5_2_1_5}; font-weight:bold;'>"
                    f"📊 Pontuação Obtida no Quesito 17.5.2.1.5: {pts_atuais_17_5_2_1_5:+.1f} pontos (Dados Informativos)</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 17.5.2.1.5
        if st.session_state.get(f"gatilho_modal_17_5_2_1_5_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("17.5.2.1.5", st.session_state.get(f"links_pendentes_17_5_2_1_5_{ano_sel}", []), ano_sel)

        # =============================================================================
        # QUESITO 17.6.1.1 • PRONTUÁRIO ELETRÔNICO COMPARTILHADO (ATENÇÃO ESPECIALIZADA)
        # =============================================================================
        with st.container(key=f"container_bloco_pep_compartilhado_17_6_1_1_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 17.6.1.1 - Prontuário Eletrônico Compartilhado ({ano_sel})", expanded=True):
                st.subheader(f"17.6.1.1 • Prontuário Eletrônico Compartilhado ({ano_sel})")
                st.write(f"**Dentre os serviços assinalados acima, indique em quais deles o Prontuário Eletrônico é compartilhado com as demais Unidades de Saúde:**")
                st.caption("ℹ️ *Preencha os campos abaixo, informe o link de evidência e clique no botão 'Salvar Quesito 17.6.1.1' para registrar.*")

                d17_6_1_1 = res_data.get("17.6.1.1") or {
                    "valor": "",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_17_6_1_1 = d17_6_1_1.get("valor", "")
                l_salvo_17_6_1_1 = d17_6_1_1.get("link", "")

                lista_salva_17611 = [item.strip() for item in v_salvo_17_6_1_1.split(";")] if v_salvo_17_6_1_1 else []

                c17611_1, c17611_2 = st.columns([1, 1])

                with c17611_1:
                    st.write("📋 **Selecione as opções compartilhadas:**")
                    
                    op_pepc_1 = "Consultas médicas por especialidade"
                    op_pepc_2 = "Exames laboratoriais"
                    op_pepc_3 = "Exames radiológicos e por imagem"
                    op_pepc_4 = "Terapias / tratamentos"
                    op_pepc_5 = "Medicamentos"
                    op_pepc_6 = "OPM"
                    op_pepc_7 = "Cirurgias eletivas"
                    op_pepc_8 = "Outros"

                    chk_pepc_1 = st.checkbox(op_pepc_1, value=(op_pepc_1 in lista_salva_17611), key=f"chk_17611_1_{ano_sel}")
                    chk_pepc_2 = st.checkbox(op_pepc_2, value=(op_pepc_2 in lista_salva_17611), key=f"chk_17611_2_{ano_sel}")
                    chk_pepc_3 = st.checkbox(op_pepc_3, value=(op_pepc_3 in lista_salva_17611), key=f"chk_17611_3_{ano_sel}")
                    chk_pepc_4 = st.checkbox(op_pepc_4, value=(op_pepc_4 in lista_salva_17611), key=f"chk_17611_4_{ano_sel}")
                    chk_pepc_5 = st.checkbox(op_pepc_5, value=(op_pepc_5 in lista_salva_17611), key=f"chk_17611_5_{ano_sel}")
                    chk_pepc_6 = st.checkbox(op_pepc_6, value=(op_pepc_6 in lista_salva_17611), key=f"chk_17611_6_{ano_sel}")
                    chk_pepc_7 = st.checkbox(op_pepc_7, value=(op_pepc_7 in lista_salva_17611), key=f"chk_17611_7_{ano_sel}")
                    chk_pepc_8 = st.checkbox(op_pepc_8, value=(op_pepc_8 in lista_salva_17611), key=f"chk_17611_8_{ano_sel}")

                    selecionados_pepc = []
                    if chk_pepc_1: selecionados_pepc.append(op_pepc_1)
                    if chk_pepc_2: selecionados_pepc.append(op_pepc_2)
                    if chk_pepc_3: selecionados_pepc.append(op_pepc_3)
                    if chk_pepc_4: selecionados_pepc.append(op_pepc_4)
                    if chk_pepc_5: selecionados_pepc.append(op_pepc_5)
                    if chk_pepc_6: selecionados_pepc.append(op_pepc_6)
                    if chk_pepc_7: selecionados_pepc.append(op_pepc_7)
                    if chk_pepc_8: selecionados_pepc.append(op_pepc_8)

                    string_estruturada_17611 = "; ".join(selecionados_pepc) if selecionados_pepc else ""
                    pts_17_6_1_1 = 0.0

                with c17611_2:
                    link_17_6_1_1_input = st.text_area(
                        "Link/Evidência do compartilhamento do PEP (17.6.1.1):",
                        value=l_salvo_17_6_1_1,
                        key=f"reg_17_6_1_1_txt_{ano_sel}",
                        height=280
                    )

                    links_17_6_1_1_visuais = re.findall(REGEX_PURE_URL, link_17_6_1_1_input or "")
                    if links_17_6_1_1_visuais:
                        st.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_17_6_1_1_visuais]
                            )
                        )

                # Chat de comentários
                bloco_comentarios_isaude("17.6.1.1", res_data)

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 17.6.1.1", key=f"btn_salvar_17_6_1_1_{ano_sel}", type="primary"):
                    val_str_17_6_1_1 = string_estruturada_17611
                    val_lk_17_6_1_1 = link_17_6_1_1_input.strip()
                    comentarios_17_6_1_1 = d17_6_1_1.get("comentarios", [])

                    save_resp_isaude(
                        qid="17.6.1.1",
                        valor=val_str_17_6_1_1,
                        pontos=pts_17_6_1_1,
                        link=val_lk_17_6_1_1,
                        comentarios=comentarios_17_6_1_1
                    )

                    # Modal de aviso para links pendentes
                    links_atuais_17_6_1_1 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_17_6_1_1_input or "")]
                    links_antigos_17_6_1_1 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_17_6_1_1 or "")]

                    if (val_str_17_6_1_1 != v_salvo_17_6_1_1 or val_lk_17_6_1_1 != l_salvo_17_6_1_1) and links_atuais_17_6_1_1 and links_atuais_17_6_1_1 != links_antigos_17_6_1_1:
                        st.session_state[f"links_pendentes_17_6_1_1_{ano_sel}"] = links_atuais_17_6_1_1
                        st.session_state[f"gatilho_modal_17_6_1_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 17.6.1.1 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                pts_atuais_17_6_1_1 = d17_6_1_1.get("pontos", 0.0)
                cor_txt_17_6_1_1 = "#28a745" if pts_atuais_17_6_1_1 >= 0.0 else "#dc3545"

                st.markdown(
                    f"<span style='color:{cor_txt_17_6_1_1}; font-weight:bold;'>"
                    f"📊 Pontuação Obtida no Quesito 17.6.1.1: {pts_atuais_17_6_1_1:+.1f} pontos (Dados Informativos)</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 17.6.1.1
        if st.session_state.get(f"gatilho_modal_17_6_1_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("17.6.1.1", st.session_state.get(f"links_pendentes_17_6_1_1_{ano_sel}", []), ano_sel)

        # =============================================================================
        # QUESITO 17.7 • MAMÓGRAFOS NA REDE PRÓPRIA
        # =============================================================================
        with st.container(key=f"container_bloco_mamografos_17_7_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 17.7 - Mamógrafos na Rede Própria ({ano_sel})", expanded=True):
                st.subheader(f"17.7 • Mamógrafos na Rede Própria ({ano_sel})")
                st.write(f"**17.7 O município possui estabelecimentos de saúde da rede própria com mamógrafos?**")
                st.caption("ℹ️ *Selecione uma opção, informe o link de evidência e clique no botão 'Salvar Quesito 17.7' para registrar.*")

                d17_7 = res_data.get("17.7") or {
                    "valor": "Selecione...",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_17_7 = d17_7.get("valor", "Selecione...")
                l_salvo_17_7 = d17_7.get("link", "")

                opts_17_7 = [
                    "Selecione...",
                    "Sim",
                    "Não"
                ]
                if v_salvo_17_7 not in opts_17_7:
                    v_salvo_17_7 = "Selecione..."

                idx_17_7 = opts_17_7.index(v_salvo_17_7)

                c177_1, c177_2 = st.columns([1, 1])

                with c177_1:
                    st.write("🏥 **Selecione uma alternativa:**")
                    sel_17_7 = st.radio(
                        "Possui estabelecimentos com mamógrafos:",
                        options=opts_17_7,
                        index=idx_17_7,
                        key=f"rad_mamog_17_7_sel_{ano_sel}",
                        label_visibility="collapsed"
                    )

                    # Quesito apenas condicional/informativo (pontuação 0.0)
                    pts_17_7 = 0.0

                with c177_2:
                    link_17_7_input = st.text_area(
                        "Link/Evidência (17.7):",
                        value=l_salvo_17_7,
                        key=f"txt_link_17_7_mamog_{ano_sel}",  # CHAVE ÚNICA ATUALIZADA
                        height=180
                    )

                    links_17_7_visuais = re.findall(REGEX_PURE_URL, link_17_7_input or "")
                    if links_17_7_visuais:
                        st.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_17_7_visuais]
                            )
                        )

                # Chat de comentários
                bloco_comentarios_isaude("17.7", res_data)

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 17.7", key=f"btn_salvar_17_7_mamog_{ano_sel}", type="primary"):
                    val_str_17_7 = sel_17_7
                    val_lk_17_7 = link_17_7_input.strip()
                    comentarios_17_7 = d17_7.get("comentarios", [])

                    save_resp_isaude(
                        qid="17.7",
                        valor=val_str_17_7,
                        pontos=pts_17_7,
                        link=val_lk_17_7,
                        comentarios=comentarios_17_7
                    )

                    # Modal de aviso para links pendentes
                    links_atuais_17_7 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_17_7_input or "")]
                    links_antigos_17_7 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_17_7 or "")]

                    if (val_str_17_7 != v_salvo_17_7 or val_lk_17_7 != l_salvo_17_7) and links_atuais_17_7 and links_atuais_17_7 != links_antigos_17_7:
                        st.session_state[f"links_pendentes_17_7_{ano_sel}"] = links_atuais_17_7
                        st.session_state[f"gatilho_modal_17_7_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 17.7 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                pts_atuais_17_7 = d17_7.get("pontos", 0.0)
                cor_txt_17_7 = "#28a745" if pts_atuais_17_7 >= 0.0 else "#dc3545"

                st.markdown(
                    f"<span style='color:{cor_txt_17_7}; font-weight:bold;'>"
                    f"📊 Pontuação Obtida no Quesito 17.7: {pts_atuais_17_7:+.1f} pontos</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 17.7
        if st.session_state.get(f"gatilho_modal_17_7_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("17.7", st.session_state.get(f"links_pendentes_17_7_{ano_sel}", []), ano_sel)
        # =============================================================================
        # QUESITO 17.7.1 • SERVIÇOS INSERIDOS NO PEP (URGÊNCIA E EMERGÊNCIA)
        # =============================================================================
        with st.container(key=f"container_bloco_pep_urgencia_17_7_1_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 17.7.1 - Serviços no PEP de Urgência/Emergência ({ano_sel})", expanded=True):
                st.subheader(f"17.7.1 • Serviços no Prontuário Eletrônico (Urgência e Emergência) ({ano_sel})")
                st.write(f"**17.7.1 Assinale os serviços da Urgência e Emergência inseridos no Prontuário Eletrônico do Paciente:**")
                st.caption("ℹ️ *Regra IEGM: Perde -0.50 ponto para cada item não assinalado (exceto 'Outros'). Limite de -2.5 pontos.*")

                d17_7_1 = res_data.get("17.7.1") or {
                    "valor": "",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_17_7_1 = d17_7_1.get("valor", "")
                l_salvo_17_7_1 = d17_7_1.get("link", "")

                lista_salva_1771 = [item.strip() for item in v_salvo_17_7_1.split(";")] if v_salvo_17_7_1 else []

                c1771_1, c1771_2 = st.columns([1, 1])

                with c1771_1:
                    st.write("🏥 **Selecione as opções ativas no PEP:**")
                    
                    op_pepu_1 = "Acolhimento com classificação de risco"
                    op_pepu_2 = "Atendimentos médicos e de enfermagem"
                    op_pepu_3 = "Exames laboratoriais, radiológicos e por imagem"
                    op_pepu_4 = "Medicamentos administrados / prescritos"
                    op_pepu_5 = "Procedimentos cirúrgicos de urgência"
                    op_pepu_6 = "Outros"

                    chk_pepu_1 = st.checkbox(op_pepu_1, value=(op_pepu_1 in lista_salva_1771), key=f"chk_1771_1_{ano_sel}")
                    chk_pepu_2 = st.checkbox(op_pepu_2, value=(op_pepu_2 in lista_salva_1771), key=f"chk_1771_2_{ano_sel}")
                    chk_pepu_3 = st.checkbox(op_pepu_3, value=(op_pepu_3 in lista_salva_1771), key=f"chk_1771_3_{ano_sel}")
                    chk_pepu_4 = st.checkbox(op_pepu_4, value=(op_pepu_4 in lista_salva_1771), key=f"chk_1771_4_{ano_sel}")
                    chk_pepu_5 = st.checkbox(op_pepu_5, value=(op_pepu_5 in lista_salva_1771), key=f"chk_1771_5_{ano_sel}")
                    chk_pepu_6 = st.checkbox(op_pepu_6, value=(op_pepu_6 in lista_salva_1771), key=f"chk_1771_6_{ano_sel}")

                    selecionados_pepu = []
                    if chk_pepu_1: selecionados_pepu.append(op_pepu_1)
                    if chk_pepu_2: selecionados_pepu.append(op_pepu_2)
                    if chk_pepu_3: selecionados_pepu.append(op_pepu_3)
                    if chk_pepu_4: selecionados_pepu.append(op_pepu_4)
                    if chk_pepu_5: selecionados_pepu.append(op_pepu_5)
                    if chk_pepu_6: selecionados_pepu.append(op_pepu_6)

                    # Cálculo da pontuação IEGM (Penalidades)
                    penalidade_u = 0.0
                    if not chk_pepu_1: penalidade_u -= 0.50
                    if not chk_pepu_2: penalidade_u -= 0.50
                    if not chk_pepu_3: penalidade_u -= 0.50
                    if not chk_pepu_4: penalidade_u -= 0.50
                    if not chk_pepu_5: penalidade_u -= 0.50

                    pts_17_7_1 = max(penalidade_u, -2.5)
                    string_estruturada_1771 = "; ".join(selecionados_pepu) if selecionados_pepu else ""

                with c1771_2:
                    link_17_7_1_input = st.text_area(
                        "Link/Evidência das funcionalidades do PEP na Urgência (17.7.1):",
                        value=l_salvo_17_7_1,
                        key=f"txt_link_17_7_1_pepu_{ano_sel}",  # CHAVE ÚNICA ATUALIZADA
                        height=280
                    )

                    links_17_7_1_visuais = re.findall(REGEX_PURE_URL, link_17_7_1_input or "")
                    if links_17_7_1_visuais:
                        st.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_17_7_1_visuais]
                            )
                        )

                # Chat de comentários
                bloco_comentarios_isaude("17.7.1", res_data)

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 17.7.1", key=f"btn_salvar_17_7_1_pepu_{ano_sel}", type="primary"):
                    val_str_17_7_1 = string_estruturada_1771
                    val_lk_17_7_1 = link_17_7_1_input.strip()
                    comentarios_17_7_1 = d17_7_1.get("comentarios", [])

                    save_resp_isaude(
                        qid="17.7.1",
                        valor=val_str_17_7_1,
                        pontos=pts_17_7_1,
                        link=val_lk_17_7_1,
                        comentarios=comentarios_17_7_1
                    )

                    # Modal de aviso para links pendentes
                    links_atuais_17_7_1 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_17_7_1_input or "")]
                    links_antigos_17_7_1 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_17_7_1 or "")]

                    if (val_str_17_7_1 != v_salvo_17_7_1 or val_lk_17_7_1 != l_salvo_17_7_1) and links_atuais_17_7_1 and links_atuais_17_7_1 != links_antigos_17_7_1:
                        st.session_state[f"links_pendentes_17_7_1_{ano_sel}"] = links_atuais_17_7_1
                        st.session_state[f"gatilho_modal_17_7_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 17.7.1 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                pts_atuais_17_7_1 = d17_7_1.get("pontos", 0.0)
                cor_txt_17_7_1 = "#28a745" if pts_atuais_17_7_1 >= 0.0 else "#dc3545"

                st.markdown(
                    f"<span style='color:{cor_txt_17_7_1}; font-weight:bold;'>"
                    f"📊 Pontuação Obtida no Quesito 17.7.1: {pts_atuais_17_7_1:+.2f} pontos</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 17.7.1
        if st.session_state.get(f"gatilho_modal_17_7_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("17.7.1", st.session_state.get(f"links_pendentes_17_7_1_{ano_sel}", []), ano_sel)

        # =============================================================================
        # QUESITO 17.8 • EQUIPAMENTOS DE ULTRASSOM CONVENCIONAL (INFORMATIVO)
        # =============================================================================
        with st.container(key=f"container_bloco_ultrassom_17_8_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 17.8 - Equipamentos de Ultrassom Convencional ({ano_sel})", expanded=True):
                st.subheader(f"17.8 • Equipamentos de Ultrassom Convencional ({ano_sel})")
                st.write(f"**17.8 O município possui estabelecimentos de saúde da rede própria com equipamentos de ultrassom convencional?**")
                st.caption("ℹ️ *Selecione uma opção, informe o link de evidência/SCNES e clique no botão 'Salvar Quesito 17.8' para registrar.*")

                d17_8 = res_data.get("17.8") or {
                    "valor": "Selecione...",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_17_8 = d17_8.get("valor", "Selecione...")
                l_salvo_17_8 = d17_8.get("link", "")

                opts_17_8 = [
                    "Selecione...",
                    "Sim",
                    "Não"
                ]
                if v_salvo_17_8 not in opts_17_8:
                    v_salvo_17_8 = "Selecione..."

                idx_17_8 = opts_17_8.index(v_salvo_17_8)

                c178_1, c178_2 = st.columns([1, 1])

                with c178_1:
                    st.write("🏥 **Selecione uma alternativa:**")
                    sel_17_8 = st.radio(
                        "Possui ultrassom convencional:",
                        options=opts_17_8,
                        index=idx_17_8,
                        key=f"rad_ultra_17_8_sel_{ano_sel}",
                        label_visibility="collapsed"
                    )

                    # Quesito apenas informativo (pontuação 0.0)
                    pts_17_8 = 0.0

                with c178_2:
                    link_17_8_input = st.text_area(
                        "Link/Evidência ou Cadastro do SCNES (17.8):",
                        value=l_salvo_17_8,
                        key=f"txt_link_17_8_ultra_{ano_sel}",
                        height=180
                    )

                    links_17_8_visuais = re.findall(REGEX_PURE_URL, link_17_8_input or "")
                    if links_17_8_visuais:
                        st.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_17_8_visuais]
                            )
                        )

                # Chat de comentários
                bloco_comentarios_isaude("17.8", res_data)

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 17.8", key=f"btn_salvar_17_8_ultra_{ano_sel}", type="primary"):
                    val_str_17_8 = sel_17_8
                    val_lk_17_8 = link_17_8_input.strip()
                    comentarios_17_8 = d17_8.get("comentarios", [])

                    save_resp_isaude(
                        qid="17.8",
                        valor=val_str_17_8,
                        pontos=pts_17_8,
                        link=val_lk_17_8,
                        comentarios=comentarios_17_8
                    )

                    # Modal de aviso para links pendentes
                    links_atuais_17_8 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_17_8_input or "")]
                    links_antigos_17_8 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_17_8 or "")]

                    if (val_str_17_8 != v_salvo_17_8 or val_lk_17_8 != l_salvo_17_8) and links_atuais_17_8 and links_atuais_17_8 != links_antigos_17_8:
                        st.session_state[f"links_pendentes_17_8_{ano_sel}"] = links_atuais_17_8
                        st.session_state[f"gatilho_modal_17_8_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 17.8 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                pts_atuais_17_8 = d17_8.get("pontos", 0.0)
                st.markdown(
                    f"<span style='color:#28a745; font-weight:bold;'>"
                    f"📊 Pontuação Obtida no Quesito 17.8: {pts_atuais_17_8:+.1f} pontos (Dados Informativos)</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 17.8
        if st.session_state.get(f"gatilho_modal_17_8_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("17.8", st.session_state.get(f"links_pendentes_17_8_{ano_sel}", []), ano_sel)

        # =============================================================================
        # QUESITO 17.9 - HOSPITAL OU SANTA CASA SOB GESTÃO MUNICIPAL (INFORMATIVO)
        # =============================================================================
        with st.container(key=f"container_bloco_hospital_santa_casa_17_9_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 17.9 - Hospital ou Santa Casa sob Gestão Municipal ({ano_sel})", expanded=True):
                st.subheader(f"17.9 • Hospital ou Santa Casa sob Gestão Municipal ({ano_sel})")
                st.write(f"**17.9 O município possui hospital ou Santa Casa sob sua gestão?**")
                st.caption("ℹ️ *Selecione uma opção, informe o link de evidência/SCNES e clique no botão 'Salvar Quesito 17.9' para registrar.*")

                d17_9 = res_data.get("17.9") or {
                    "valor": "Selecione...",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_17_9 = d17_9.get("valor", "Selecione...")
                l_salvo_17_9 = d17_9.get("link", "")

                opts_17_9 = [
                    "Selecione...",
                    "Sim",
                    "Não"
                ]
                if v_salvo_17_9 not in opts_17_9:
                    v_salvo_17_9 = "Selecione..."

                idx_17_9 = opts_17_9.index(v_salvo_17_9)

                c179_1, c179_2 = st.columns([1, 1])

                with c179_1:
                    st.write("🏥 **Selecione uma alternativa:**")
                    sel_17_9 = st.radio(
                        "Possui hospital/Santa Casa sob gestão:",
                        options=opts_17_9,
                        index=idx_17_9,
                        key=f"rad_hosp_17_9_sel_{ano_sel}",
                        label_visibility="collapsed"
                    )

                    # Quesito apenas informativo (pontuação 0.0)
                    pts_17_9 = 0.0

                with c179_2:
                    link_17_9_input = st.text_area(
                        "Link/Evidência ou Cadastro do SCNES do Hospital/Santa Casa (17.9):",
                        value=l_salvo_17_9,
                        key=f"txt_link_17_9_hosp_{ano_sel}",
                        height=180
                    )

                    links_17_9_visuais = re.findall(REGEX_PURE_URL, link_17_9_input or "")
                    if links_17_9_visuais:
                        st.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_17_9_visuais]
                            )
                        )

                # Chat de comentários
                bloco_comentarios_isaude("17.9", res_data)

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 17.9", key=f"btn_salvar_17_9_hosp_{ano_sel}", type="primary"):
                    val_str_17_9 = sel_17_9
                    val_lk_17_9 = link_17_9_input.strip()
                    comentarios_17_9 = d17_9.get("comentarios", [])

                    save_resp_isaude(
                        qid="17.9",
                        valor=val_str_17_9,
                        pontos=pts_17_9,
                        link=val_lk_17_9,
                        comentarios=comentarios_17_9
                    )

                    # Modal de aviso para links pendentes
                    links_atuais_17_9 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_17_9_input or "")]
                    links_antigos_17_9 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_17_9 or "")]

                    if (val_str_17_9 != v_salvo_17_9 or val_lk_17_9 != l_salvo_17_9) and links_atuais_17_9 and links_atuais_17_9 != links_antigos_17_9:
                        st.session_state[f"links_pendentes_17_9_{ano_sel}"] = links_atuais_17_9
                        st.session_state[f"gatilho_modal_17_9_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 17.9 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                pts_atuais_17_9 = d17_9.get("pontos", 0.0)
                st.markdown(
                    f"<span style='color:#28a745; font-weight:bold;'>"
                    f"📊 Pontuação Obtida no Quesito 17.9: {pts_atuais_17_9:+.1f} pontos (Dados Informativos)</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 17.9
        if st.session_state.get(f"gatilho_modal_17_9_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("17.9", st.session_state.get(f"links_pendentes_17_9_{ano_sel}", []), ano_sel)

        # =============================================================================
        # QUESITO 17.9.1 - TAXA DE OCUPAÇÃO HOSPITALAR DA REDE PRÓPRIA
        # =============================================================================
        with st.container(key=f"container_bloco_taxa_ocupacao_hospitalar_17_9_1_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 17.9.1 - Taxa de Ocupação Hospitalar da Rede Própria ({ano_sel})", expanded=True):
                st.subheader(f"17.9.1 • Taxa de Ocupação Hospitalar da Rede Própria ({ano_sel})")
                st.write(f"**17.9.1 Informe o total de pacientes-dia e leitos-dia para fins de cálculo da Taxa de Ocupação (TO):**")
                st.caption("ℹ️ *Preencha os dados operacionais e clique no botão 'Salvar Quesito 17.9.1' para registrar os pontos.*")

                d17_9_1 = res_data.get("17.9.1") or {
                    "valor": "0|0",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_17_9_1 = d17_9_1.get("valor", "0|0")
                l_salvo_17_9_1 = d17_9_1.get("link", "")

                partes_leitos = v_salvo_17_9_1.split("|") if v_salvo_17_9_1 else ["0", "0"]
                val_pa_salvo = partes_leitos[0] if len(partes_leitos) > 0 else "0"
                val_le_salvo = partes_leitos[1] if len(partes_leitos) > 1 else "0"

                c1791_1, c1791_2 = st.columns([1, 1])

                with c1791_1:
                    st.write(f"📊 **Dados Operacionais ({ano_sel}):**")

                    inp_pa = st.text_input(
                        f"Total de pacientes-dia atendidos em {ano_sel} (PA):",
                        value=val_pa_salvo,
                        key=f"txt_1791_pa_hosp_{ano_sel}"
                    )

                    inp_le = st.text_input(
                        f"Número total de leitos-dia disponíveis em {ano_sel} (LE):",
                        value=val_le_salvo,
                        key=f"txt_1791_le_hosp_{ano_sel}"
                    )

                    def converter_campo_leitos(val):
                        try:
                            return float(str(val).replace(".", "").replace(",", ".").strip()) if val else 0.0
                        except Exception:
                            return 0.0

                    pa_float = converter_campo_leitos(inp_pa)
                    le_float = converter_campo_leitos(inp_le)

                    # Cálculo da Taxa de Ocupação
                    if pa_float == 0.0 and le_float == 0.0:
                        st.info("💡 Aguardando o preenchimento dos dados operacionais.")
                        pts_17_9_1 = 0.0
                    elif le_float > 0:
                        taxa_to = (pa_float / le_float) * 100.0
                        st.markdown(f"📈 **Taxa de Ocupação Calculada (TO):** `{taxa_to:.2f}%`")

                        if 75.0 <= taxa_to <= 90.0:
                            pts_17_9_1 = 0.0
                        else:
                            pts_17_9_1 = -5.0
                    else:
                        st.markdown("⚠️ **Aviso:** O número de leitos-dia deve ser maior que zero para o cálculo.")
                        pts_17_9_1 = -5.0

                    string_estruturada_leitos = f"{inp_pa}|{inp_le}"

                with c1791_2:
                    link_17_9_1_input = st.text_area(
                        f"Link/Evidência ou Relatório do SIH/SUS (Movimentação de Leitos) em {ano_sel}:",
                        value=l_salvo_17_9_1,
                        key=f"txt_link_17_9_1_ocupacao_{ano_sel}",
                        height=240
                    )

                    links_17_9_1_visuais = re.findall(REGEX_PURE_URL, link_17_9_1_input or "")
                    if links_17_9_1_visuais:
                        st.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_17_9_1_visuais]
                            )
                        )

                # Chat de comentários
                bloco_comentarios_isaude("17.9.1", res_data)

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 17.9.1", key=f"btn_salvar_17_9_1_to_{ano_sel}", type="primary"):
                    val_str_17_9_1 = string_estruturada_leitos
                    val_lk_17_9_1 = link_17_9_1_input.strip()
                    comentarios_17_9_1 = d17_9_1.get("comentarios", [])

                    save_resp_isaude(
                        qid="17.9.1",
                        valor=val_str_17_9_1,
                        pontos=pts_17_9_1,
                        link=val_lk_17_9_1,
                        comentarios=comentarios_17_9_1
                    )

                    # Modal de aviso para links pendentes
                    links_atuais_17_9_1 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_17_9_1_input or "")]
                    links_antigos_17_9_1 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_17_9_1 or "")]

                    if (val_str_17_9_1 != v_salvo_17_9_1 or val_lk_17_9_1 != l_salvo_17_9_1) and links_atuais_17_9_1 and links_atuais_17_9_1 != links_antigos_17_9_1:
                        st.session_state[f"links_pendentes_17_9_1_{ano_sel}"] = links_atuais_17_9_1
                        st.session_state[f"gatilho_modal_17_9_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 17.9.1 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                pts_atuais_17_9_1 = d17_9_1.get("pontos", 0.0)
                cor_txt_17_9_1 = "#28a745" if pts_atuais_17_9_1 >= 0.0 else "#dc3545"

                st.markdown(
                    f"<span style='color:{cor_txt_17_9_1}; font-weight:bold;'>"
                    f"📊 Pontuação Obtida no Quesito 17.9.1: {pts_atuais_17_9_1:+.1f} pontos</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 17.9.1
        if st.session_state.get(f"gatilho_modal_17_9_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("17.9.1", st.session_state.get(f"links_pendentes_17_9_1_{ano_sel}", []), ano_sel)

        # =============================================================================
        # QUESITO 17.9.2 - HOSPITAIS COM TAXA DE OCUPAÇÃO SUPERIOR A 100%
        # =============================================================================
        with st.container(key=f"container_bloco_hospitais_superlotados_17_9_2_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 17.9.2 - Hospitais com Ocupação Superior a 100% (Série Histórica - {ano_sel})", expanded=True):
                st.subheader(f"17.9.2 • Hospitais com Ocupação Superior a 100% ({ano_sel})")
                st.write(f"**17.9.2 Informe o número de hospitais da rede própria que apresentaram taxa de ocupação superior a 100%:**")
                st.caption("ℹ️ *Informe os valores da série histórica e clique no botão 'Salvar Quesito 17.9.2' para registrar os pontos.*")

                # Definição dinâmica da janela temporal
                try:
                    aa = int(ano_sel)
                except Exception:
                    aa = 2025

                aa_minus_1 = aa - 1
                aa_minus_2 = aa - 2

                d17_9_2 = res_data.get("17.9.2") or {
                    "valor": "0|0|0",
                    "pontos": -5.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_17_9_2 = d17_9_2.get("valor", "0|0|0")
                l_salvo_17_9_2 = d17_9_2.get("link", "")

                partes_to = v_salvo_17_9_2.split("|") if v_salvo_17_9_2 else ["0", "0", "0"]
                while len(partes_to) < 3:
                    partes_to.append("0")

                c1792_1, c1792_2 = st.columns([1, 1])

                with c1792_1:
                    st.write("📊 **Número de Estabelecimentos com Ocupação > 100%:**")
                    to_aa2 = st.text_input(f"Nº de hospitais em {aa_minus_2} (TO_{aa_minus_2}):", value=partes_to[0], key=f"txt_to_aa2_{ano_sel}")
                    to_aa1 = st.text_input(f"Nº de hospitais em {aa_minus_1} (TO_{aa_minus_1}):", value=partes_to[1], key=f"txt_to_aa1_{ano_sel}")
                    to_aa  = st.text_input(f"Nº de hospitais em {aa} (TO_{aa}):", value=partes_to[2], key=f"txt_to_aa_{ano_sel}")

                    def converter_to(val):
                        try:
                            return float(str(val).replace(".", "").replace(",", ".").strip()) if val else 0.0
                        except Exception:
                            return 0.0

                    f_to_aa2 = converter_to(to_aa2)
                    f_to_aa1 = converter_to(to_aa1)
                    f_to_aa  = converter_to(to_aa)

                    media_anterior = (f_to_aa2 + f_to_aa1) / 2.0
                    st.markdown(f"⏳ **Média Histórica Anterior ({aa_minus_2} e {aa_minus_1}):** `{media_anterior:.2f}` hospitais")
                    st.markdown(f"📈 **Valor Registrado no Ano Atual ({aa}):** `{f_to_aa:.2f}` hospitais")

                    # Regra de negócio: Se o ano atual for menor ou igual à média ganha 0; se maior, perde 5.
                    if f_to_aa <= media_anterior:
                        pts_17_9_2 = 0.0
                    else:
                        pts_17_9_2 = -5.0

                    string_estruturada_to = f"{to_aa2}|{to_aa1}|{to_aa}"

                with c1792_2:
                    link_17_9_2_input = st.text_area(
                        f"Link/Evidência ou Relatório de Movimentação de Leitos / AIH da série histórica ({aa_minus_2} a {aa}):",
                        value=l_salvo_17_9_2,
                        key=f"txt_link_17_9_2_superlotacao_{ano_sel}",
                        height=235
                    )

                    links_17_9_2_visuais = re.findall(REGEX_PURE_URL, link_17_9_2_input or "")
                    if links_17_9_2_visuais:
                        st.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_17_9_2_visuais]
                            )
                        )

                # Chat de comentários
                bloco_comentarios_isaude("17.9.2", res_data)

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 17.9.2", key=f"btn_salvar_17_9_2_superlotacao_{ano_sel}", type="primary"):
                    val_str_17_9_2 = string_estruturada_to
                    val_lk_17_9_2 = link_17_9_2_input.strip()
                    comentarios_17_9_2 = d17_9_2.get("comentarios", [])

                    save_resp_isaude(
                        qid="17.9.2",
                        valor=val_str_17_9_2,
                        pontos=pts_17_9_2,
                        link=val_lk_17_9_2,
                        comentarios=comentarios_17_9_2
                    )

                    # Modal de aviso para links novos/alterados
                    links_atuais_17_9_2 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_17_9_2_input or "")]
                    links_antigos_17_9_2 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_17_9_2 or "")]

                    if (val_str_17_9_2 != v_salvo_17_9_2 or val_lk_17_9_2 != l_salvo_17_9_2) and links_atuais_17_9_2 and links_atuais_17_9_2 != links_antigos_17_9_2:
                        st.session_state[f"links_pendentes_17_9_2_{ano_sel}"] = links_atuais_17_9_2
                        st.session_state[f"gatilho_modal_17_9_2_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 17.9.2 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                pts_atuais_17_9_2 = d17_9_2.get("pontos", -5.0)
                cor_txt_17_9_2 = "#28a745" if pts_atuais_17_9_2 >= 0.0 else "#dc3545"

                st.markdown(
                    f"<span style='color:{cor_txt_17_9_2}; font-weight:bold;'>"
                    f"📊 Pontuação Obtida no Quesito 17.9.2: {pts_atuais_17_9_2:+.1f} pontos</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 17.9.2
        if st.session_state.get(f"gatilho_modal_17_9_2_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("17.9.2", st.session_state.get(f"links_pendentes_17_9_2_{ano_sel}", []), ano_sel)

        # =============================================================================
        # QUESITO 18.0 - DEMANDA POR ASSISTÊNCIA EM SAÚDE MENTAL (INFORMATIVO)
        # =============================================================================
        with st.container(key=f"container_bloco_demanda_saude_mental_18_0_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 18.0 - Demanda por Assistência em Saúde Mental e Substâncias Psicoativas ({ano_sel})", expanded=True):
                st.subheader(f"18.0 • Demanda por Assistência em Saúde Mental ({ano_sel})")
                st.write(f"**18.0 No município, há demanda de ações e de serviços voltados para a assistência aos portadores de transtornos mentais, bem como para usuários de substâncias psicoativas?**")
                st.caption("ℹ️ *Selecione uma opção, informe o link de evidência e clique no botão 'Salvar Quesito 18.0' para registrar.*")

                d18_0 = res_data.get("18.0") or {
                    "valor": "Selecione...",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_18_0 = d18_0.get("valor", "Selecione...")
                l_salvo_18_0 = d18_0.get("link", "")

                opts_18_0 = [
                    "Selecione...",
                    "Sim",
                    "Não"
                ]
                if v_salvo_18_0 not in opts_18_0:
                    v_salvo_18_0 = "Selecione..."

                idx_18_0 = opts_18_0.index(v_salvo_18_0)

                c180_1, c180_2 = st.columns([1, 1])

                with c180_1:
                    st.write("🧠 **Selecione uma alternativa:**")
                    sel_18_0 = st.radio(
                        "Há demanda por ações/serviços:",
                        options=opts_18_0,
                        index=idx_18_0,
                        key=f"rad_mental_18_0_sel_{ano_sel}",
                        label_visibility="collapsed"
                    )

                    # Quesito meramente informativo (0.0 pontos)
                    pts_18_0 = 0.0

                with c180_2:
                    link_18_0_input = st.text_area(
                        "Link/Evidência, Plano Municipal de Saúde ou Relatório de Gestão (18.0):",
                        value=l_salvo_18_0,
                        key=f"txt_link_18_0_mental_{ano_sel}",
                        height=180
                    )

                    links_18_0_visuais = re.findall(REGEX_PURE_URL, link_18_0_input or "")
                    if links_18_0_visuais:
                        st.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_18_0_visuais]
                            )
                        )

                # Chat de comentários
                bloco_comentarios_isaude("18.0", res_data)

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 18.0", key=f"btn_salvar_18_0_mental_{ano_sel}", type="primary"):
                    val_str_18_0 = sel_18_0
                    val_lk_18_0 = link_18_0_input.strip()
                    comentarios_18_0 = d18_0.get("comentarios", [])

                    save_resp_isaude(
                        qid="18.0",
                        valor=val_str_18_0,
                        pontos=pts_18_0,
                        link=val_lk_18_0,
                        comentarios=comentarios_18_0
                    )

                    # Modal de aviso para links novos/alterados
                    links_atuais_18_0 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_18_0_input or "")]
                    links_antigos_18_0 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_18_0 or "")]

                    if (val_str_18_0 != v_salvo_18_0 or val_lk_18_0 != l_salvo_18_0) and links_atuais_18_0 and links_atuais_18_0 != links_antigos_18_0:
                        st.session_state[f"links_pendentes_18_0_{ano_sel}"] = links_atuais_18_0
                        st.session_state[f"gatilho_modal_18_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 18.0 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                pts_atuais_18_0 = d18_0.get("pontos", 0.0)
                st.markdown(
                    f"<span style='color:#28a745; font-weight:bold;'>"
                    f"📊 Pontuação Obtida no Quesito 18.0: {pts_atuais_18_0:+.1f} pontos (Dados Informativos)</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 18.0
        if st.session_state.get(f"gatilho_modal_18_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("18.0", st.session_state.get(f"links_pendentes_18_0_{ano_sel}", []), ano_sel)

       # =============================================================================
        # QUESITO 18.1 - PLANO DE AÇÃO MUNICIPAL DA RAPS
        # =============================================================================
        with st.container(key=f"container_bloco_plano_raps_18_1_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 18.1 - Plano de Ação para Inclusão na RAPS ({ano_sel})", expanded=True):
                st.subheader(f"18.1 • Plano de Ação para Inclusão na RAPS ({ano_sel})")
                st.write("**18.1 Realizou Plano de Ação municipal para inclusão do município à sua RAPS?**")
                st.caption("ℹ️ *Selecione uma alternativa, informe o link de evidência e clique no botão 'Salvar Quesito 18.1' para registrar os pontos.*")

                d18_1 = res_data.get("18.1") or {
                    "valor": "Selecione...",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_18_1 = d18_1.get("valor", "Selecione...")
                l_salvo_18_1 = d18_1.get("link", "")

                opts_18_1 = {
                    "Selecione...": 0.0,
                    "Sim – 00": 0.0,
                    "Não – -10 (perde 10 pontos)": -10.0
                }

                labels_18_1 = list(opts_18_1.keys())
                if v_salvo_18_1 not in labels_18_1:
                    v_salvo_18_1 = "Selecione..."

                idx_18_1 = labels_18_1.index(v_salvo_18_1)

                c181_1, c181_2 = st.columns([1, 1])

                with c181_1:
                    st.write("📋 **Selecione uma alternativa:**")
                    sel_18_1 = st.radio(
                        "Plano de Ação RAPS:",
                        options=labels_18_1,
                        index=idx_18_1,
                        key=f"rad_plano_raps_18_1_sel_{ano_sel}",
                        label_visibility="collapsed"
                    )

                    pts_18_1 = opts_18_1.get(sel_18_1, 0.0)

                with c181_2:
                    link_18_1_input = st.text_area(
                        "Evidência / Resolução do Plano RAPS (18.1):",
                        value=l_salvo_18_1,
                        key=f"txt_link_18_1_plano_raps_{ano_sel}",
                        height=150
                    )

                    links_18_1_visuais = re.findall(REGEX_PURE_URL, link_18_1_input or "")
                    if links_18_1_visuais:
                        st.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_18_1_visuais]
                            )
                        )

                # Chat de comentários
                bloco_comentarios_isaude("18.1", res_data)

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 18.1", key=f"btn_salvar_18_1_plano_raps_{ano_sel}", type="primary"):
                    val_str_18_1 = sel_18_1
                    val_lk_18_1 = link_18_1_input.strip()
                    comentarios_18_1 = d18_1.get("comentarios", [])

                    save_resp_isaude(
                        qid="18.1",
                        valor=val_str_18_1,
                        pontos=pts_18_1,
                        link=val_lk_18_1,
                        comentarios=comentarios_18_1
                    )

                    # Modal de aviso para links novos/alterados
                    links_atuais_18_1 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_18_1_input or "")]
                    links_antigos_18_1 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_18_1 or "")]

                    if (val_str_18_1 != v_salvo_18_1 or val_lk_18_1 != l_salvo_18_1) and links_atuais_18_1 and links_atuais_18_1 != links_antigos_18_1:
                        st.session_state[f"links_pendentes_18_1_{ano_sel}"] = links_atuais_18_1
                        st.session_state[f"gatilho_modal_18_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 18.1 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                pts_atuais_18_1 = d18_1.get("pontos", 0.0)
                cor_txt_18_1 = "#28a745" if pts_atuais_18_1 >= 0.0 else "#dc3545"

                st.markdown(
                    f"<span style='color:{cor_txt_18_1}; font-weight:bold;'>"
                    f"📊 Pontuação Obtida no Quesito 18.1: {pts_atuais_18_1:+.1f} pontos</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 18.1
        if st.session_state.get(f"gatilho_modal_18_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("18.1", st.session_state.get(f"links_pendentes_18_1_{ano_sel}", []), ano_sel)

        # =============================================================================
        # QUESITO 18.2 - INTEGRAÇÃO ENTRE ÓRGÃOS MUNICIPAIS
        # =============================================================================
        with st.container(key=f"container_bloco_integracao_orgaos_18_2_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 18.2 - Integração de Órgãos para Assistência Mental ({ano_sel})", expanded=True):
                st.subheader(f"18.2 • Integração de Órgãos para Assistência Mental ({ano_sel})")
                st.write("**18.2 A Secretaria Municipal de Saúde (ou equivalente) está integrada com os outros órgãos municipais de forma a ampliar a oferta de ações e de serviços voltados para a assistência aos portadores de transtornos mentais?**")
                st.caption("ℹ️ *Selecione uma alternativa, informe o link de evidência e clique no botão 'Salvar Quesito 18.2' para registrar os pontos.*")

                d18_2 = res_data.get("18.2") or {
                    "valor": "Selecione...",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_18_2 = d18_2.get("valor", "Selecione...")
                l_salvo_18_2 = d18_2.get("link", "")

                opts_18_2 = {
                    "Selecione...": 0.0,
                    "Sim – 00": 0.0,
                    "Não – -05 (perde 05 pontos)": -5.0
                }

                labels_18_2 = list(opts_18_2.keys())
                if v_salvo_18_2 not in labels_18_2:
                    v_salvo_18_2 = "Selecione..."

                idx_18_2 = labels_18_2.index(v_salvo_18_2)

                c182_1, c182_2 = st.columns([1, 1])

                with c182_1:
                    st.write("📋 **Selecione uma alternativa:**")
                    sel_18_2 = st.radio(
                        "Integração de órgãos:",
                        options=labels_18_2,
                        index=idx_18_2,
                        key=f"rad_integracao_orgaos_18_2_sel_{ano_sel}",
                        label_visibility="collapsed"
                    )

                    pts_18_2 = opts_18_2.get(sel_18_2, 0.0)

                with c182_2:
                    link_18_2_input = st.text_area(
                        "Evidência de Integração Intersetorial (18.2):",
                        value=l_salvo_18_2,
                        key=f"txt_link_18_2_integracao_{ano_sel}",
                        height=150
                    )

                    links_18_2_visuais = re.findall(REGEX_PURE_URL, link_18_2_input or "")
                    if links_18_2_visuais:
                        st.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_18_2_visuais]
                            )
                        )

                # Chat de comentários
                bloco_comentarios_isaude("18.2", res_data)

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 18.2", key=f"btn_salvar_18_2_integracao_{ano_sel}", type="primary"):
                    val_str_18_2 = sel_18_2
                    val_lk_18_2 = link_18_2_input.strip()
                    comentarios_18_2 = d18_2.get("comentarios", [])

                    save_resp_isaude(
                        qid="18.2",
                        valor=val_str_18_2,
                        pontos=pts_18_2,
                        link=val_lk_18_2,
                        comentarios=comentarios_18_2
                    )

                    # Modal de aviso para links novos/alterados
                    links_atuais_18_2 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_18_2_input or "")]
                    links_antigos_18_2 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_18_2 or "")]

                    if (val_str_18_2 != v_salvo_18_2 or val_lk_18_2 != l_salvo_18_2) and links_atuais_18_2 and links_atuais_18_2 != links_antigos_18_2:
                        st.session_state[f"links_pendentes_18_2_{ano_sel}"] = links_atuais_18_2
                        st.session_state[f"gatilho_modal_18_2_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 18.2 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                pts_atuais_18_2 = d18_2.get("pontos", 0.0)
                cor_txt_18_2 = "#28a745" if pts_atuais_18_2 >= 0.0 else "#dc3545"

                st.markdown(
                    f"<span style='color:{cor_txt_18_2}; font-weight:bold;'>"
                    f"📊 Pontuação Obtida no Quesito 18.2: {pts_atuais_18_2:+.1f} pontos</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 18.2
        if st.session_state.get(f"gatilho_modal_18_2_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("18.2", st.session_state.get(f"links_pendentes_18_2_{ano_sel}", []), ano_sel)

        # =============================================================================
        # QUESITO 18.2.1 - FORMA DE INTEGRAÇÃO DOS ÓRGÃOS
        # =============================================================================
        with st.container(key=f"container_bloco_forma_integracao_18_2_1_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 18.2.1 • Forma de Integração dos Órgãos ({ano_sel})", expanded=True):
                st.subheader(f"18.2.1 • Forma de Integração dos Órgãos ({ano_sel})")
                st.write("**Assinale a forma de integração dos órgãos:**")
                st.caption("ℹ️ *Selecione as opções aplicáveis, informe o link de evidência e clique no botão 'Salvar Quesito 18.2.1' para registrar os dados.*")

                d18_2_1 = res_data.get("18.2.1") or {
                    "valor": "0|0|0|0|0|0",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_18_2_1 = d18_2_1.get("valor", "0|0|0|0|0|0")
                l_salvo_18_2_1 = d18_2_1.get("link", "")

                p_1821 = v_salvo_18_2_1.split("|")
                while len(p_1821) < 6:
                    p_1821.append("0")

                c1821_1, c1821_2 = st.columns([1, 1])

                with c1821_1:
                    st.write("☑️ **Formas de Integração:**")
                    ch1_1821 = st.checkbox("Ações estabelecidas", value=(p_1821[0] == "1"), key=f"ch_1821_1_{ano_sel}")
                    ch2_1821 = st.checkbox("Papéis definidos", value=(p_1821[1] == "1"), key=f"ch_1821_2_{ano_sel}")
                    ch3_1821 = st.checkbox("Metas estabelecidas", value=(p_1821[2] == "1"), key=f"ch_1821_3_{ano_sel}")
                    ch4_1821 = st.checkbox("Prazos", value=(p_1821[3] == "1"), key=f"ch_1821_4_{ano_sel}")
                    ch5_1821 = st.checkbox("Normas complementares firmadas entre órgãos", value=(p_1821[4] == "1"), key=f"ch_1821_5_{ano_sel}")
                    ch6_1821 = st.checkbox("Outros", value=(p_1821[5] == "1"), key=f"ch_1821_6_{ano_sel}")

                    string_estruturada_18_2_1 = f"{1 if ch1_1821 else 0}|{1 if ch2_1821 else 0}|{1 if ch3_1821 else 0}|{1 if ch4_1821 else 0}|{1 if ch5_1821 else 0}|{1 if ch6_1821 else 0}"

                with c1821_2:
                    link_18_2_1_input = st.text_area(
                        "Link/Evidência de Integração (18.2.1):",
                        value=l_salvo_18_2_1,
                        key=f"txt_link_18_2_1_forma_integracao_{ano_sel}",
                        height=180
                    )

                    links_18_2_1_visuais = re.findall(REGEX_PURE_URL, link_18_2_1_input or "")
                    if links_18_2_1_visuais:
                        st.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_18_2_1_visuais]
                            )
                        )

                # Chat de comentários
                bloco_comentarios_isaude("18.2.1", res_data)

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 18.2.1", key=f"btn_salvar_18_2_1_forma_integracao_{ano_sel}", type="primary"):
                    val_str_18_2_1 = string_estruturada_18_2_1
                    val_lk_18_2_1 = link_18_2_1_input.strip()
                    comentarios_18_2_1 = d18_2_1.get("comentarios", [])

                    save_resp_isaude(
                        qid="18.2.1",
                        valor=val_str_18_2_1,
                        pontos=0.0,
                        link=val_lk_18_2_1,
                        comentarios=comentarios_18_2_1
                    )

                    # Modal de aviso para links novos/alterados
                    links_atuais_18_2_1 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_18_2_1_input or "")]
                    links_antigos_18_2_1 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_18_2_1 or "")]

                    if (val_str_18_2_1 != v_salvo_18_2_1 or val_lk_18_2_1 != l_salvo_18_2_1) and links_atuais_18_2_1 and links_atuais_18_2_1 != links_antigos_18_2_1:
                        st.session_state[f"links_pendentes_18_2_1_{ano_sel}"] = links_atuais_18_2_1
                        st.session_state[f"gatilho_modal_18_2_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 18.2.1 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                st.markdown(
                    "<span style='color:#6c757d; font-weight:bold;'>"
                    "📊 Pontuação Aplicada no Quesito 18.2.1: +0.0 pontos (Dados Informativos)</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 18.2.1
        if st.session_state.get(f"gatilho_modal_18_2_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("18.2.1", st.session_state.get(f"links_pendentes_18_2_1_{ano_sel}", []), ano_sel)

        # =============================================================================
        # QUESITO 18.2.1.1 - METAS ATINGIDAS NO EXERCÍCIO ANTERIOR
        # =============================================================================
        with st.container(key=f"container_bloco_metas_18_2_1_1_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 18.2.1.1 • Metas Atingidas no Exercício Anterior ({ano_sel})", expanded=True):
                st.subheader(f"18.2.1.1 • Metas Atingidas no Exercício Anterior ({ano_sel})")
                st.write("**As metas estabelecidas para o exercício 2025 foram atingidas?**")
                st.caption("ℹ️ *Selecione uma alternativa, informe o link de evidência e clique no botão 'Salvar Quesito 18.2.1.1' para registrar os dados.*")

                d18_2_1_1 = res_data.get("18.2.1.1") or {
                    "valor": "Selecione...",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_18211 = d18_2_1_1.get("valor", "Selecione...")
                l_salvo_18211 = d18_2_1_1.get("link", "")

                opts_18_2_1_1 = {
                    "Selecione...": 0.0,
                    "Sim, todas as metas foram atingidas": 0.0,
                    "Sim, a maior parte das metas foram atingidas": 0.0,
                    "Sim, a menor parte das metas foram atingidas": 0.0,
                    "Não": 0.0
                }

                labels_18211 = list(opts_18_2_1_1.keys())
                if v_salvo_18211 not in labels_18211:
                    v_salvo_18211 = "Selecione..."

                idx_18211 = labels_18211.index(v_salvo_18211)

                c18211_1, c18211_2 = st.columns([1, 1])

                with c18211_1:
                    st.write("📋 **Selecione uma alternativa:**")
                    sel_18_2_1_1 = st.radio(
                        "Metas atingidas:",
                        options=labels_18211,
                        index=idx_18211,
                        key=f"rad_metas_18_2_1_1_sel_{ano_sel}",
                        label_visibility="collapsed"
                    )

                    pts_18_2_1_1 = opts_18_2_1_1.get(sel_18_2_1_1, 0.0)

                with c18211_2:
                    link_18_2_1_1_input = st.text_area(
                        "Link/Evidência do Relatório de Metas (18.2.1.1):",
                        value=l_salvo_18211,
                        key=f"txt_link_18_2_1_1_metas_{ano_sel}",
                        height=150
                    )

                    links_18211_visuais = re.findall(REGEX_PURE_URL, link_18_2_1_1_input or "")
                    if links_18211_visuais:
                        st.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_18211_visuais]
                            )
                        )

                # Chat de comentários
                bloco_comentarios_isaude("18.2.1.1", res_data)

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 18.2.1.1", key=f"btn_salvar_18_2_1_1_metas_{ano_sel}", type="primary"):
                    val_str_18211 = sel_18_2_1_1
                    val_lk_18211 = link_18_2_1_1_input.strip()
                    comentarios_18211 = d18_2_1_1.get("comentarios", [])

                    save_resp_isaude(
                        qid="18.2.1.1",
                        valor=val_str_18211,
                        pontos=pts_18_2_1_1,
                        link=val_lk_18211,
                        comentarios=comentarios_18211
                    )

                    # Modal de aviso para links novos/alterados
                    links_atuais_18211 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_18_2_1_1_input or "")]
                    links_antigos_18211 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_18211 or "")]

                    if (val_str_18211 != v_salvo_18211 or val_lk_18211 != l_salvo_18211) and links_atuais_18211 and links_atuais_18211 != links_antigos_18211:
                        st.session_state[f"links_pendentes_18_2_1_1_{ano_sel}"] = links_atuais_18211
                        st.session_state[f"gatilho_modal_18_2_1_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 18.2.1.1 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                st.markdown(
                    "<span style='color:#6c757d; font-weight:bold;'>"
                    "📊 Pontuação Aplicada no Quesito 18.2.1.1: +0.0 pontos (Dados Informativos)</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 18.2.1.1
        if st.session_state.get(f"gatilho_modal_18_2_1_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("18.2.1.1", st.session_state.get(f"links_pendentes_18_2_1_1_{ano_sel}", []), ano_sel)

        # =============================================================================
        # QUESITO 18.3 - TERMO DE ADESÃO AO PROGRAMA RECOMEÇO
        # =============================================================================
        with st.container(key=f"container_bloco_recomeco_18_3_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 18.3 • Adesão ao Programa Recomeço ({ano_sel})", expanded=True):
                st.subheader(f"18.3 • Adesão ao Programa Recomeço ({ano_sel})")
                st.write("**O Município formalizou termo de adesão com o Programa Recomeço (Art. 7º, Decreto nº 61.674/2015) ou outro programa que venha a substituí-lo?**")
                st.caption("ℹ️ *Selecione uma alternativa, informe o link de evidência e clique no botão 'Salvar Quesito 18.3' para registrar os dados.*")

                d18_3 = res_data.get("18.3") or {
                    "valor": "Selecione...",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_183 = d18_3.get("valor", "Selecione...")
                l_salvo_183 = d18_3.get("link", "")

                opts_18_3 = {
                    "Selecione...": 0.0,
                    "Sim": 0.0,
                    "Não": 0.0
                }

                labels_183 = list(opts_18_3.keys())
                if v_salvo_183 not in labels_183:
                    v_salvo_183 = "Selecione..."

                idx_183 = labels_183.index(v_salvo_183)

                c183_1, c183_2 = st.columns([1, 1])

                with c183_1:
                    st.write("📋 **Selecione uma alternativa:**")
                    sel_18_3 = st.radio(
                        "Formalizou adesão:",
                        options=labels_183,
                        index=idx_183,
                        key=f"rad_recomeco_18_3_sel_{ano_sel}",
                        label_visibility="collapsed"
                    )

                    pts_18_3 = opts_18_3.get(sel_18_3, 0.0)

                with c183_2:
                    link_18_3_input = st.text_area(
                        "Link/Evidência da Publicação do Termo de Adesão (18.3):",
                        value=l_salvo_183,
                        key=f"txt_link_18_3_recomeco_{ano_sel}",
                        height=150
                    )

                    links_183_visuais = re.findall(REGEX_PURE_URL, link_18_3_input or "")
                    if links_183_visuais:
                        st.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_183_visuais]
                            )
                        )

                # Chat de comentários
                bloco_comentarios_isaude("18.3", res_data)

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 18.3", key=f"btn_salvar_18_3_recomeco_{ano_sel}", type="primary"):
                    val_str_183 = sel_18_3
                    val_lk_183 = link_18_3_input.strip()
                    comentarios_183 = d18_3.get("comentarios", [])

                    save_resp_isaude(
                        qid="18.3",
                        valor=val_str_183,
                        pontos=pts_18_3,
                        link=val_lk_183,
                        comentarios=comentarios_183
                    )

                    # Modal de aviso para links novos/alterados
                    links_atuais_183 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_18_3_input or "")]
                    links_antigos_183 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_183 or "")]

                    if (val_str_183 != v_salvo_183 or val_lk_183 != l_salvo_183) and links_atuais_183 and links_atuais_183 != links_antigos_183:
                        st.session_state[f"links_pendentes_18_3_{ano_sel}"] = links_atuais_183
                        st.session_state[f"gatilho_modal_18_3_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 18.3 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                st.markdown(
                    "<span style='color:#6c757d; font-weight:bold;'>"
                    "📊 Pontuação Aplicada no Quesito 18.3: +0.0 pontos (Dados Informativos)</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 18.3
        if st.session_state.get(f"gatilho_modal_18_3_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("18.3", st.session_state.get(f"links_pendentes_18_3_{ano_sel}", []), ano_sel)

        # =============================================================================
        # QUESITO 18.4 - INDICADORES ESPECÍFICOS DA ATENÇÃO PSICOSSOCIAL
        # =============================================================================
        with st.container(key=f"container_bloco_indicadores_18_4_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 18.4 • Indicadores da Atenção Psicossocial ({ano_sel})", expanded=True):
                st.subheader(f"18.4 • Indicadores da Atenção Psicossocial ({ano_sel})")
                st.write("**O município possui indicadores específicos para a Atenção Psicossocial?**")
                st.caption("ℹ️ *Selecione uma alternativa, informe o link de evidência e clique no botão 'Salvar Quesito 18.4' para registrar os dados.*")

                d18_4 = res_data.get("18.4") or {
                    "valor": "Selecione...",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_184 = d18_4.get("valor", "Selecione...")
                l_salvo_184 = d18_4.get("link", "")

                opts_18_4 = {
                    "Selecione...": 0.0,
                    "Sim – 00": 0.0,
                    "Não – -05 (perde 05 pontos)": -5.0
                }

                labels_184 = list(opts_18_4.keys())
                if v_salvo_184 not in labels_184:
                    v_salvo_184 = "Selecione..."

                idx_184 = labels_184.index(v_salvo_184)

                c184_1, c184_2 = st.columns([1, 1])

                with c184_1:
                    st.write("📋 **Selecione uma alternativa:**")
                    sel_18_4 = st.radio(
                        "Possui indicadores específicos:",
                        options=labels_184,
                        index=idx_184,
                        key=f"rad_indicadores_18_4_sel_{ano_sel}",
                        label_visibility="collapsed"
                    )

                    pts_18_4 = opts_18_4.get(sel_18_4, 0.0)

                with c184_2:
                    link_18_4_input = st.text_area(
                        "Link/Evidência dos Indicadores (18.4):",
                        value=l_salvo_184,
                        key=f"txt_link_18_4_indicadores_{ano_sel}",
                        height=150
                    )

                    links_184_visuais = re.findall(REGEX_PURE_URL, link_18_4_input or "")
                    if links_184_visuais:
                        st.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_184_visuais]
                            )
                        )

                # Chat de comentários
                bloco_comentarios_isaude("18.4", res_data)

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 18.4", key=f"btn_salvar_18_4_indicadores_{ano_sel}", type="primary"):
                    val_str_184 = sel_18_4
                    val_lk_184 = link_18_4_input.strip()
                    comentarios_184 = d18_4.get("comentarios", [])

                    save_resp_isaude(
                        qid="18.4",
                        valor=val_str_184,
                        pontos=pts_18_4,
                        link=val_lk_184,
                        comentarios=comentarios_184
                    )

                    # Modal de aviso para links novos/alterados
                    links_atuais_184 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_18_4_input or "")]
                    links_antigos_184 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_184 or "")]

                    if (val_str_184 != v_salvo_184 or val_lk_184 != l_salvo_184) and links_atuais_184 and links_atuais_184 != links_antigos_184:
                        st.session_state[f"links_pendentes_18_4_{ano_sel}"] = links_atuais_184
                        st.session_state[f"gatilho_modal_18_4_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 18.4 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição dinâmica do impacto de pontuação
                if sel_18_4 == "Selecione...":
                    st.markdown("<span style='color:#6c757d; font-weight:bold;'>📊 Pontuação Aplicada no Quesito 18.4: Aguardando seleção...</span>", unsafe_allow_html=True)
                elif pts_18_4 < 0:
                    st.markdown(f"<span style='color:#dc3545; font-weight:bold;'>📊 Pontuação Aplicada no Quesito 18.4: {pts_18_4:.1f} pontos (Penalidade)</span>", unsafe_allow_html=True)
                else:
                    st.markdown(f"<span style='color:#28a745; font-weight:bold;'>📊 Pontuação Aplicada no Quesito 18.4: +{pts_18_4:.1f} pontos</span>", unsafe_allow_html=True)

        # GATILHO DO MODAL 18.4
        if st.session_state.get(f"gatilho_modal_18_4_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("18.4", st.session_state.get(f"links_pendentes_18_4_{ano_sel}", []), ano_sel)

        # =============================================================================
        # QUESITO 18.4.1 - TIPOS DE INDICADORES DA ATENÇÃO PSICOSSOCIAL
        # =============================================================================
        with st.container(key=f"container_bloco_tipos_indicadores_18_4_1_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 18.4.1 • Tipos de Indicadores da Atenção Psicossocial ({ano_sel})", expanded=True):
                st.subheader(f"18.4.1 • Tipos de Indicadores da Atenção Psicossocial ({ano_sel})")
                st.write("**Assinale os tipos de indicadores da Atenção Psicossocial:**")
                st.caption("ℹ️ *Marque os itens aplicáveis, informe o link de evidência e clique no botão 'Salvar Quesito 18.4.1' para registrar os dados.*")

                d18_4_1 = res_data.get("18.4.1") or {
                    "valor": "0|0|0|0|0",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_1841 = d18_4_1.get("valor", "0|0|0|0|0")
                l_salvo_1841 = d18_4_1.get("link", "")

                p_1841 = v_salvo_1841.split("|")
                while len(p_1841) < 5:
                    p_1841.append("0")

                c1841_1, c1841_2 = st.columns([1, 1])

                with c1841_1:
                    st.write("📋 **Selecione os tipos aplicáveis:**")
                    ch1_1841 = st.checkbox(
                        "Para Drogas (transtornos mentais incluindo aqueles relacionados ao uso de substâncias)",
                        value=(p_1841[0] == "1"),
                        key=f"ch_1841_1_{ano_sel}"
                    )
                    ch2_1841 = st.checkbox(
                        "Para Saúde Mental (transtornos mentais graves e persistentes)",
                        value=(p_1841[1] == "1"),
                        key=f"ch_1841_2_{ano_sel}"
                    )
                    ch3_1841 = st.checkbox(
                        "Para outras situações clínicas que impossibilitem estabelecer laços sociais e realizar projetos",
                        value=(p_1841[2] == "1"),
                        key=f"ch_1841_3_{ano_sel}"
                    )
                    ch4_1841 = st.checkbox(
                        "Para Drogas e/ou Saúde Mental para crianças em específico",
                        value=(p_1841[3] == "1"),
                        key=f"ch_1841_4_{ano_sel}"
                    )
                    ch5_1841 = st.checkbox(
                        "Outros",
                        value=(p_1841[4] == "1"),
                        key=f"ch_1841_5_{ano_sel}"
                    )

                    string_estruturada_18_4_1 = f"{1 if ch1_1841 else 0}|{1 if ch2_1841 else 0}|{1 if ch3_1841 else 0}|{1 if ch4_1841 else 0}|{1 if ch5_1841 else 0}"
                    pts_18_4_1 = 0.0

                with c1841_2:
                    link_18_4_1_input = st.text_area(
                        "Link/Evidência ou Ficha Técnica dos Indicadores (18.4.1):",
                        value=l_salvo_1841,
                        key=f"txt_link_18_4_1_tipos_{ano_sel}",
                        height=180
                    )

                    links_1841_visuais = re.findall(REGEX_PURE_URL, link_18_4_1_input or "")
                    if links_1841_visuais:
                        st.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_1841_visuais]
                            )
                        )

                # Chat de comentários
                bloco_comentarios_isaude("18.4.1", res_data)

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 18.4.1", key=f"btn_salvar_18_4_1_tipos_{ano_sel}", type="primary"):
                    val_str_1841 = string_estruturada_18_4_1
                    val_lk_1841 = link_18_4_1_input.strip()
                    comentarios_1841 = d18_4_1.get("comentarios", [])

                    save_resp_isaude(
                        qid="18.4.1",
                        valor=val_str_1841,
                        pontos=pts_18_4_1,
                        link=val_lk_1841,
                        comentarios=comentarios_1841
                    )

                    # Modal de aviso para links novos/alterados
                    links_atuais_1841 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_18_4_1_input or "")]
                    links_antigos_1841 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_1841 or "")]

                    if (val_str_1841 != v_salvo_1841 or val_lk_1841 != l_salvo_1841) and links_atuais_1841 and links_atuais_1841 != links_antigos_1841:
                        st.session_state[f"links_pendentes_18_4_1_{ano_sel}"] = links_atuais_1841
                        st.session_state[f"gatilho_modal_18_4_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 18.4.1 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                st.markdown(
                    "<span style='color:#6c757d; font-weight:bold;'>"
                    "📊 Pontuação Aplicada no Quesito 18.4.1: +0.0 pontos (Dados Informativos)</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 18.4.1
        if st.session_state.get(f"gatilho_modal_18_4_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("18.4.1", st.session_state.get(f"links_pendentes_18_4_1_{ano_sel}", []), ano_sel)

        # =============================================================================
        # QUESITO 18.5 - POPULAÇÃO SUPERIOR A 15 MIL HABITANTES
        # =============================================================================
        with st.container(key=f"container_bloco_populacao_18_5_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 18.5 • População Superior a 15 mil Habitantes ({ano_sel})", expanded=True):
                st.subheader(f"18.5 • População Superior a 15 mil Habitantes ({ano_sel})")
                st.write("**O município possui população superior a 15 mil habitantes? (Conforme Dados do IBGE 2025)**")
                st.caption("ℹ️ *Selecione uma alternativa, informe o link de evidência e clique no botão 'Salvar Quesito 18.5' para registrar os dados.*")

                d18_5 = res_data.get("18.5") or {
                    "valor": "Selecione...",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_185 = d18_5.get("valor", "Selecione...")
                l_salvo_185 = d18_5.get("link", "")

                opts_18_5 = {
                    "Selecione...": 0.0,
                    "Sim": 0.0,
                    "Não": 0.0
                }

                labels_185 = list(opts_18_5.keys())
                if v_salvo_185 not in labels_185:
                    v_salvo_185 = "Selecione..."

                idx_185 = labels_185.index(v_salvo_185)

                c185_1, c185_2 = st.columns([1, 1])

                with c185_1:
                    st.write("📋 **Selecione uma alternativa:**")
                    sel_18_5 = st.radio(
                        "População > 15k hab:",
                        options=labels_185,
                        index=idx_185,
                        key=f"rad_populacao_18_5_sel_{ano_sel}",
                        label_visibility="collapsed"
                    )

                    pts_18_5 = opts_18_5.get(sel_18_5, 0.0)

                with c185_2:
                    link_18_5_input = st.text_area(
                        "Link/Evidência ou Documento de Censo IBGE (18.5):",
                        value=l_salvo_185,
                        key=f"txt_link_18_5_populacao_{ano_sel}",
                        height=150
                    )

                    links_185_visuais = re.findall(REGEX_PURE_URL, link_18_5_input or "")
                    if links_185_visuais:
                        st.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_185_visuais]
                            )
                        )

                # Chat de comentários
                bloco_comentarios_isaude("18.5", res_data)

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 18.5", key=f"btn_salvar_18_5_populacao_{ano_sel}", type="primary"):
                    val_str_185 = sel_18_5
                    val_lk_185 = link_18_5_input.strip()
                    comentarios_185 = d18_5.get("comentarios", [])

                    save_resp_isaude(
                        qid="18.5",
                        valor=val_str_185,
                        pontos=pts_18_5,
                        link=val_lk_185,
                        comentarios=comentarios_185
                    )

                    # Modal de aviso para links novos/alterados
                    links_atuais_185 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_18_5_input or "")]
                    links_antigos_185 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_185 or "")]

                    if (val_str_185 != v_salvo_185 or val_lk_185 != l_salvo_185) and links_atuais_185 and links_atuais_185 != links_antigos_185:
                        st.session_state[f"links_pendentes_18_5_{ano_sel}"] = links_atuais_185
                        st.session_state[f"gatilho_modal_18_5_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 18.5 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                if sel_18_5 == "Selecione...":
                    st.markdown("<span style='color:#6c757d; font-weight:bold;'>📊 Pontuação Aplicada no Quesito 18.5: Aguardando seleção...</span>", unsafe_allow_html=True)
                else:
                    st.markdown(
                        f"<span style='color:#6c757d; font-weight:bold;'>📊 Pontuação Aplicada no Quesito 18.5: +{pts_18_5:.1f} pontos (Dados Informativos)</span>",
                        unsafe_allow_html=True
                    )

        # GATILHO DO MODAL 18.5
        if st.session_state.get(f"gatilho_modal_18_5_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("18.5", st.session_state.get(f"links_pendentes_18_5_{ano_sel}", []), ano_sel)


        # =============================================================================
        # QUESITO 18.5.1 - ADEQUAÇÃO DA QUANTIDADE DE CAPS E UNIDADES
        # =============================================================================
        with st.container(key=f"container_bloco_adequacao_caps_18_5_1_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 18.5.1 • Adequação da Rede CAPS e Acolhimento ({ano_sel})", expanded=True):
                st.subheader(f"18.5.1 • Adequação da Rede CAPS e Acolhimento ({ano_sel})")
                st.write("**A Quantidade de CAPS e Unidades de Acolhimento Adulto e Infanto-Juvenil segundo a totalidade de habitantes do município é adequada?**")
                st.caption("ℹ️ *Selecione uma alternativa, informe o link de evidência e clique no botão 'Salvar Quesito 18.5.1' para registrar os dados.*")

                d18_5_1 = res_data.get("18.5.1") or {
                    "valor": "Selecione...",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_1851 = d18_5_1.get("valor", "Selecione...")
                l_salvo_1851 = d18_5_1.get("link", "")

                opts_18_5_1 = {
                    "Selecione...": 0.0,
                    "Sim": 0.0,
                    "Não": 0.0
                }

                labels_1851 = list(opts_18_5_1.keys())
                if v_salvo_1851 not in labels_1851:
                    v_salvo_1851 = "Selecione..."

                idx_1851 = labels_1851.index(v_salvo_1851)

                c1851_1, c1851_2 = st.columns([1, 1])

                with c1851_1:
                    st.write("📋 **Selecione uma alternativa:**")
                    sel_18_5_1 = st.radio(
                        "Quantidade adequada:",
                        options=labels_1851,
                        index=idx_1851,
                        key=f"rad_adequacao_18_5_1_sel_{ano_sel}",
                        label_visibility="collapsed"
                    )

                    pts_18_5_1 = opts_18_5_1.get(sel_18_5_1, 0.0)

                with c1851_2:
                    link_18_5_1_input = st.text_area(
                        "Link/Evidência ou Justificativa de Cobertura (18.5.1):",
                        value=l_salvo_1851,
                        key=f"txt_link_18_5_1_adequacao_{ano_sel}",
                        height=150
                    )

                    links_1851_visuais = re.findall(REGEX_PURE_URL, link_18_5_1_input or "")
                    if links_1851_visuais:
                        st.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_1851_visuais]
                            )
                        )

                # Chat de comentários
                bloco_comentarios_isaude("18.5.1", res_data)

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 18.5.1", key=f"btn_salvar_18_5_1_adequacao_{ano_sel}", type="primary"):
                    val_str_1851 = sel_18_5_1
                    val_lk_1851 = link_18_5_1_input.strip()
                    comentarios_1851 = d18_5_1.get("comentarios", [])

                    save_resp_isaude(
                        qid="18.5.1",
                        valor=val_str_1851,
                        pontos=pts_18_5_1,
                        link=val_lk_1851,
                        comentarios=comentarios_1851
                    )

                    # Modal de aviso para links novos/alterados
                    links_atuais_1851 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_18_5_1_input or "")]
                    links_antigos_1851 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_1851 or "")]

                    if (val_str_1851 != v_salvo_1851 or val_lk_1851 != l_salvo_1851) and links_atuais_1851 and links_atuais_1851 != links_antigos_1851:
                        st.session_state[f"links_pendentes_18_5_1_{ano_sel}"] = links_atuais_1851
                        st.session_state[f"gatilho_modal_18_5_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 18.5.1 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                if sel_18_5_1 == "Selecione...":
                    st.markdown("<span style='color:#6c757d; font-weight:bold;'>📊 Pontuação Aplicada no Quesito 18.5.1: Aguardando seleção...</span>", unsafe_allow_html=True)
                else:
                    st.markdown(
                        f"<span style='color:#6c757d; font-weight:bold;'>📊 Pontuação Aplicada no Quesito 18.5.1: +{pts_18_5_1:.1f} pontos (Dados Informativos)</span>",
                        unsafe_allow_html=True
                    )

        # GATILHO DO MODAL 18.5.1
        if st.session_state.get(f"gatilho_modal_18_5_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("18.5.1", st.session_state.get(f"links_pendentes_18_5_1_{ano_sel}", []), ano_sel)


        # =============================================================================
        # QUESITO 18.5.2 - QUANTIDADE DE ESTABELECIMENTOS DA REDE
        # =============================================================================
        with st.container(key=f"container_bloco_quant_estab_18_5_2_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 18.5.2 • Quantidade de Estabelecimentos Cadastrados ({ano_sel})", expanded=True):
                st.subheader(f"18.5.2 • Quantidade de Estabelecimentos do Município ({ano_sel})")
                st.write("**Informe a quantidade de estabelecimentos do município por categoria:**")
                st.caption("ℹ️ *Preencha a quantidade dos estabelecimentos, informe o link de evidência e clique no botão 'Salvar Quesito 18.5.2' para registrar os dados.*")

                d18_5_2 = res_data.get("18.5.2") or {
                    "valor": "0|0|0|0|0|0|0|0|0|0|0",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_1852 = d18_5_2.get("valor", "0|0|0|0|0|0|0|0|0|0|0")
                l_salvo_1852 = d18_5_2.get("link", "")

                p_1852 = v_salvo_1852.split("|")
                while len(p_1852) < 11:
                    p_1852.append("0")

                c1852_1, c1852_2 = st.columns([1, 1])

                with c1852_1:
                    st.write("📋 **Informe os quantitativos por categoria:**")
                    v1 = st.text_input("I - CAPS I:", value=p_1852[0], key=f"q1852_v1_{ano_sel}")
                    v2 = st.text_input("II - CAPS II:", value=p_1852[1], key=f"q1852_v2_{ano_sel}")
                    v3 = st.text_input("III - CAPS III:", value=p_1852[2], key=f"q1852_v3_{ano_sel}")
                    v4 = st.text_input("IV - CAPS AD:", value=p_1852[3], key=f"q1852_v4_{ano_sel}")
                    v5 = st.text_input("V - CAPS AD II:", value=p_1852[4], key=f"q1852_v5_{ano_sel}")
                    v6 = st.text_input("VI - CAPS AD III:", value=p_1852[5], key=f"q1852_v6_{ano_sel}")
                    v7 = st.text_input("VII - CAPS i:", value=p_1852[6], key=f"q1852_v7_{ano_sel}")
                    v8 = st.text_input("VIII - CAPS i II:", value=p_1852[7], key=f"q1852_v8_{ano_sel}")
                    v9 = st.text_input("IX - CAPS AD IV:", value=p_1852[8], key=f"q1852_v9_{ano_sel}")
                    v10 = st.text_input("X - Unidade de Acolhimento Adulto:", value=p_1852[9], key=f"q1852_v10_{ano_sel}")
                    v11 = st.text_input("XI - Unidade de Acolhimento Infantil:", value=p_1852[10], key=f"q1852_v11_{ano_sel}")

                    string_estruturada_18_5_2 = f"{v1}|{v2}|{v3}|{v4}|{v5}|{v6}|{v7}|{v8}|{v9}|{v10}|{v11}"
                    pts_18_5_2 = 0.0

                with c1852_2:
                    link_18_5_2_input = st.text_area(
                        "Link/Evidência ou Certidão CNES dos estabelecimentos (18.5.2):",
                        value=l_salvo_1852,
                        key=f"txt_link_18_5_2_estab_{ano_sel}",
                        height=350
                    )

                    links_1852_visuais = re.findall(REGEX_PURE_URL, link_18_5_2_input or "")
                    if links_1852_visuais:
                        st.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_1852_visuais]
                            )
                        )

                # Chat de comentários
                bloco_comentarios_isaude("18.5.2", res_data)

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 18.5.2", key=f"btn_salvar_18_5_2_estab_{ano_sel}", type="primary"):
                    val_str_1852 = string_estruturada_18_5_2
                    val_lk_1852 = link_18_5_2_input.strip()
                    comentarios_1852 = d18_5_2.get("comentarios", [])

                    save_resp_isaude(
                        qid="18.5.2",
                        valor=val_str_1852,
                        pontos=pts_18_5_2,
                        link=val_lk_1852,
                        comentarios=comentarios_1852
                    )

                    # Modal de aviso para links novos/alterados
                    links_atuais_1852 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_18_5_2_input or "")]
                    links_antigos_1852 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_1852 or "")]

                    if (val_str_1852 != v_salvo_1852 or val_lk_1852 != l_salvo_1852) and links_atuais_1852 and links_atuais_1852 != links_antigos_1852:
                        st.session_state[f"links_pendentes_18_5_2_{ano_sel}"] = links_atuais_1852
                        st.session_state[f"gatilho_modal_18_5_2_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 18.5.2 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                st.markdown(
                    "<span style='color:#6c757d; font-weight:bold;'>"
                    "📊 Pontuação Aplicada no Quesito 18.5.2: +0.0 pontos (Dados Informativos)</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 18.5.2
        if st.session_state.get(f"gatilho_modal_18_5_2_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("18.5.2", st.session_state.get(f"links_pendentes_18_5_2_{ano_sel}", []), ano_sel)

        # =============================================================================
        # QUESITO 18.5.3 - REGULAÇÃO DO ACESSO / FILA DE ESPERA
        # =============================================================================
        with st.container(key=f"container_bloco_regulacao_18_5_3_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 18.5.3 • Regulação do Acesso / Fila de Espera ({ano_sel})", expanded=True):
                st.subheader(f"18.5.3 • Regulação do Acesso aos CAPS e UA ({ano_sel})")
                st.write("**O município possui sistema ou mecanismo de regulação do acesso e gerenciamento de fila de espera para os CAPS e Unidades de Acolhimento?**")
                st.caption("ℹ️ *Selecione uma opção, informe o link de evidência e clique no botão 'Salvar Quesito 18.5.3' para registrar os dados.*")

                d18_5_3 = res_data.get("18.5.3") or {
                    "valor": "",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_1853 = d18_5_3.get("valor", "")
                l_salvo_1853 = d18_5_3.get("link", "")

                c1853_1, c1853_2 = st.columns([1, 1])

                with c1853_1:
                    st.write("📋 **Selecione a opção correspondente:**")
                    opts_1853 = [
                        "Sim, com sistema informatizado e fila centralizada",
                        "Sim, com controle manual/planilhas centralizadas",
                        "Parcialmente, apenas para alguns serviços/unidades",
                        "Não possui sistema de regulação nem gerenciamento de fila"
                    ]
                    
                    idx_1853 = opts_1853.index(v_salvo_1853) if v_salvo_1853 in opts_1853 else 0
                    op_1853 = st.radio(
                        "Situação da Regulação:",
                        options=opts_1853,
                        index=idx_1853,
                        key=f"q1853_op_{ano_sel}"
                    )

                    # Atribuição de pontos (ajuste conforme a regra do seu manual)
                    if op_1853 == "Sim, com sistema informatizado e fila centralizada":
                        pts_18_5_3 = 1.0
                    elif op_1853 in ["Sim, com controle manual/planilhas centralizadas", "Parcialmente, apenas para alguns serviços/unidades"]:
                        pts_18_5_3 = 0.5
                    else:
                        pts_18_5_3 = 0.0

                with c1853_2:
                    link_18_5_3_input = st.text_area(
                        "Link/Evidência ou Protocolo de Regulação (18.5.3):",
                        value=l_salvo_1853,
                        key=f"txt_link_18_5_3_regulacao_{ano_sel}",
                        height=250
                    )

                    links_1853_visuais = re.findall(REGEX_PURE_URL, link_18_5_3_input or "")
                    if links_1853_visuais:
                        st.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_1853_visuais]
                            )
                        )

                # Chat de comentários
                bloco_comentarios_isaude("18.5.3", res_data)

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 18.5.3", key=f"btn_salvar_18_5_3_regulacao_{ano_sel}", type="primary"):
                    val_str_1853 = op_1853
                    val_lk_1853 = link_18_5_3_input.strip()
                    comentarios_1853 = d18_5_3.get("comentarios", [])

                    save_resp_isaude(
                        qid="18.5.3",
                        valor=val_str_1853,
                        pontos=pts_18_5_3,
                        link=val_lk_1853,
                        comentarios=comentarios_1853
                    )

                    # Modal de aviso para links novos/alterados
                    links_atuais_1853 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_18_5_3_input or "")]
                    links_antigos_1853 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_1853 or "")]

                    if (val_str_1853 != v_salvo_1853 or val_lk_1853 != l_salvo_1853) and links_atuais_1853 and links_atuais_1853 != links_antigos_1853:
                        st.session_state[f"links_pendentes_18_5_3_{ano_sel}"] = links_atuais_1853
                        st.session_state[f"gatilho_modal_18_5_3_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 18.5.3 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                st.markdown(
                    f"<span style='color:#198754; font-weight:bold;'>"
                    f"📊 Pontuação Aplicada no Quesito 18.5.3: +{pts_18_5_3:.1f} pontos</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 18.5.3
        if st.session_state.get(f"gatilho_modal_18_5_3_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("18.5.3", st.session_state.get(f"links_pendentes_18_5_3_{ano_sel}", []), ano_sel)


        # =============================================================================
        # QUESITO 18.5.3.1 - CAPACIDADE E VAGAS NAS UNIDADES DE ACOLHIMENTO
        # =============================================================================
        with st.container(key=f"container_bloco_vagas_ua_18_5_3_1_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 18.5.3.1 • Vagas em Unidades de Acolhimento ({ano_sel})", expanded=True):
                st.subheader(f"18.5.3.1 • Quantidade de Vagas em Unidades de Acolhimento ({ano_sel})")
                st.write("**Informe a capacidade total e vagas ocupadas nas Unidades de Acolhimento (Adulto e Infantil):**")
                st.caption("ℹ️ *Preencha a quantidade de vagas, informe o link de evidência e clique no botão 'Salvar Quesito 18.5.3.1' para registrar os dados.*")

                d18_5_3_1 = res_data.get("18.5.3.1") or {
                    "valor": "0|0|0|0",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_18531 = d18_5_3_1.get("valor", "0|0|0|0")
                l_salvo_18531 = d18_5_3_1.get("link", "")

                p_18531 = v_salvo_18531.split("|")
                while len(p_18531) < 4:
                    p_18531.append("0")

                c18531_1, c18531_2 = st.columns([1, 1])

                with c18531_1:
                    st.write("📋 **Informe os quantitativos de vagas:**")
                    v1_ua = st.text_input("I - Vagas Totais (UA Adulto):", value=p_18531[0], key=f"q18531_v1_{ano_sel}")
                    v2_ua = st.text_input("II - Vagas Ocupadas (UA Adulto):", value=p_18531[1], key=f"q18531_v2_{ano_sel}")
                    v3_ua = st.text_input("III - Vagas Totais (UA Infantil):", value=p_18531[2], key=f"q18531_v3_{ano_sel}")
                    v4_ua = st.text_input("IV - Vagas Ocupadas (UA Infantil):", value=p_18531[3], key=f"q18531_v4_{ano_sel}")

                    string_estruturada_18_5_3_1 = f"{v1_ua}|{v2_ua}|{v3_ua}|{v4_ua}"
                    pts_18_5_3_1 = 0.0

                with c18531_2:
                    link_18_5_3_1_input = st.text_area(
                        "Link/Evidência ou Relatório de Ocupação de Vagas (18.5.3.1):",
                        value=l_salvo_18531,
                        key=f"txt_link_18_5_3_1_vagas_{ano_sel}",
                        height=250
                    )

                    links_18531_visuais = re.findall(REGEX_PURE_URL, link_18_5_3_1_input or "")
                    if links_18531_visuais:
                        st.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_18531_visuais]
                            )
                        )

                # Chat de comentários
                bloco_comentarios_isaude("18.5.3.1", res_data)

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 18.5.3.1", key=f"btn_salvar_18_5_3_1_vagas_{ano_sel}", type="primary"):
                    val_str_18531 = string_estruturada_18_5_3_1
                    val_lk_18531 = link_18_5_3_1_input.strip()
                    comentarios_18531 = d18_5_3_1.get("comentarios", [])

                    save_resp_isaude(
                        qid="18.5.3.1",
                        valor=val_str_18531,
                        pontos=pts_18_5_3_1,
                        link=val_lk_18531,
                        comentarios=comentarios_18531
                    )

                    # Modal de aviso para links novos/alterados
                    links_atuais_18531 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_18_5_3_1_input or "")]
                    links_antigos_18531 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_18531 or "")]

                    if (val_str_18531 != v_salvo_18531 or val_lk_18531 != l_salvo_18531) and links_atuais_18531 and links_atuais_18531 != links_antigos_18531:
                        st.session_state[f"links_pendentes_18_5_3_1_{ano_sel}"] = links_atuais_18531
                        st.session_state[f"gatilho_modal_18_5_3_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 18.5.3.1 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                st.markdown(
                    "<span style='color:#6c757d; font-weight:bold;'>"
                    "📊 Pontuação Aplicada no Quesito 18.5.3.1: +0.0 pontos (Dados Informativos)</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 18.5.3.1
        if st.session_state.get(f"gatilho_modal_18_5_3_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("18.5.3.1", st.session_state.get(f"links_pendentes_18_5_3_1_{ano_sel}", []), ano_sel)


        # =============================================================================
        # QUESITO 18.5.4 - SUFICIÊNCIA DE VAGAS DOS CAPS
        # =============================================================================
        with st.container(key=f"container_bloco_suficiencia_caps_18_5_4_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 18.5.4 • Suficiência de Vagas dos CAPS ({ano_sel})", expanded=True):
                st.subheader(f"18.5.4 • Suficiência de Vagas dos CAPS ({ano_sel})")
                st.write("**A quantidade de vagas dos CAPS é suficiente para demanda da população que apresenta prioritariamente, intenso sofrimento psíquico decorrente de transtornos mentais graves e persistentes, incluindo aqueles relacionados ao uso de substâncias psicoativas, e outras situações clínicas?**")
                st.caption("ℹ️ *Selecione uma opção, informe o link de evidência e clique no botão 'Salvar Quesito 18.5.4' para registrar os dados.*")

                d18_5_4 = res_data.get("18.5.4") or {
                    "valor": "Selecione...",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_1854 = d18_5_4.get("valor", "Selecione...")
                l_salvo_1854 = d18_5_4.get("link", "")

                c1854_1, c1854_2 = st.columns([1, 1])

                with c1854_1:
                    st.write("📋 **Selecione a opção correspondente:**")
                    opts_18_5_4 = ["Selecione...", "Sim – 00", "Não – -10 (perde 10 pontos)"]
                    idx_1854 = opts_18_5_4.index(v_salvo_1854) if v_salvo_1854 in opts_18_5_4 else 0
                    
                    sel_18_5_4 = st.radio(
                        "Vagas suficientes:",
                        options=opts_18_5_4,
                        index=idx_1854,
                        key=f"q1854_rad_{ano_sel}"
                    )
                    
                    if "Não" in sel_18_5_4:
                        pts_18_5_4 = -10.0
                    else:
                        pts_18_5_4 = 0.0

                with c1854_2:
                    link_18_5_4_input = st.text_area(
                        "Justificativa técnica ou relatório de demanda reprimida/fila (18.5.4):",
                        value=l_salvo_1854,
                        key=f"txt_link_18_5_4_suficiencia_{ano_sel}",
                        height=200
                    )

                    links_1854_visuais = re.findall(REGEX_PURE_URL, link_18_5_4_input or "")
                    if links_1854_visuais:
                        st.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_1854_visuais]
                            )
                        )

                # Chat de comentários
                bloco_comentarios_isaude("18.5.4", res_data)

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 18.5.4", key=f"btn_salvar_18_5_4_suficiencia_{ano_sel}", type="primary"):
                    val_str_1854 = sel_18_5_4
                    val_lk_1854 = link_18_5_4_input.strip()
                    comentarios_1854 = d18_5_4.get("comentarios", [])

                    save_resp_isaude(
                        qid="18.5.4",
                        valor=val_str_1854,
                        pontos=pts_18_5_4,
                        link=val_lk_1854,
                        comentarios=comentarios_1854
                    )

                    # Modal de aviso para links novos/alterados
                    links_atuais_1854 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_18_5_4_input or "")]
                    links_antigos_1854 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_1854 or "")]

                    if (val_str_1854 != v_salvo_1854 or val_lk_1854 != l_salvo_1854) and links_atuais_1854 and links_atuais_1854 != links_antigos_1854:
                        st.session_state[f"links_pendentes_18_5_4_{ano_sel}"] = links_atuais_1854
                        st.session_state[f"gatilho_modal_18_5_4_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 18.5.4 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                if pts_18_5_4 < 0:
                    st.markdown(
                        f"<span style='color:#dc3545; font-weight:bold;'>"
                        f"📊 Pontuação Aplicada no Quesito 18.5.4: {pts_18_5_4:.1f} pontos (Penalidade)</span>",
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        f"<span style='color:#6c757d; font-weight:bold;'>"
                        f"📊 Pontuação Aplicada no Quesito 18.5.4: +{pts_18_5_4:.1f} pontos</span>",
                        unsafe_allow_html=True,
                    )

        # GATILHO DO MODAL 18.5.4
        if st.session_state.get(f"gatilho_modal_18_5_4_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("18.5.4", st.session_state.get(f"links_pendentes_18_5_4_{ano_sel}", []), ano_sel)

        # =============================================================================
        # QUESITO 18.5.5 - QUANTIDADE DE VAGAS OFERTADAS
        # =============================================================================
        with st.container(key=f"container_bloco_vagas_ofertadas_18_5_5_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 18.5.5 • Quantidade de Vagas Ofertadas pelo Município ({ano_sel})", expanded=True):
                st.subheader(f"18.5.5 • Quantidade de Vagas Ofertadas pelo Município ({ano_sel})")
                st.write("**Informe a quantidade de vagas ofertadas pelo município por categoria:**")
                st.caption("ℹ️ *Preencha a quantidade das vagas, informe o link de evidência e clique no botão 'Salvar Quesito 18.5.5' para registrar os dados.*")

                d18_5_5 = res_data.get("18.5.5") or {
                    "valor": "",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_1855 = d18_5_5.get("valor", "")
                l_salvo_1855 = d18_5_5.get("link", "")

                vals_1855 = v_salvo_1855.split("|") if v_salvo_1855 else []
                tipos_vagas_ofertadas = [
                    "I - CAPS I", "II - CAPS II", "III - CAPS III", "IV - CAPS AD",
                    "V - CAPS AD II", "VI - CAPS AD III", "VII - CAPS i", "VIII - CAPS i II",
                    "IX - CAPS AD IV", "X - Unidade de Acolhimento Adulto", "XI - Unidade de Acolhimento Infantil"
                ]

                dict_vals_1855 = {t: 0 for t in tipos_vagas_ofertadas}
                for v in vals_1855:
                    if ":" in v:
                        partes = v.split(":", 1)
                        if partes[0] in dict_vals_1855:
                            try:
                                dict_vals_1855[partes[0]] = int(partes[1])
                            except ValueError:
                                pass

                c1855_1, c1855_2 = st.columns([1, 1])

                with c1855_1:
                    st.write("📋 **Informe o quantitativo de vagas ofertadas:**")
                    novos_vals_1855 = []
                    for t in tipos_vagas_ofertadas:
                        qtd_vagas_of = st.number_input(
                            f"{t}:",
                            min_value=0,
                            step=1,
                            value=dict_vals_1855[t],
                            key=f"q1855_v_{t}_{ano_sel}"
                        )
                        novos_vals_1855.append(f"{t}:{qtd_vagas_of}")

                    string_estruturada_18_5_5 = "|".join(novos_vals_1855)
                    pts_18_5_5 = 0.0

                with c1855_2:
                    link_18_5_5_input = st.text_area(
                        "Documento ou portaria instrutiva com a capacidade operacional declarada (18.5.5):",
                        value=l_salvo_1855,
                        key=f"txt_link_18_5_5_vagas_{ano_sel}",
                        height=350
                    )

                    links_1855_visuais = re.findall(REGEX_PURE_URL, link_18_5_5_input or "")
                    if links_1855_visuais:
                        st.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_1855_visuais]
                            )
                        )

                # Chat de comentários
                bloco_comentarios_isaude("18.5.5", res_data)

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 18.5.5", key=f"btn_salvar_18_5_5_vagas_{ano_sel}", type="primary"):
                    val_str_1855 = string_estruturada_18_5_5
                    val_lk_1855 = link_18_5_5_input.strip()
                    comentarios_1855 = d18_5_5.get("comentarios", [])

                    save_resp_isaude(
                        qid="18.5.5",
                        valor=val_str_1855,
                        pontos=pts_18_5_5,
                        link=val_lk_1855,
                        comentarios=comentarios_1855
                    )

                    # Modal de aviso para links novos/alterados
                    links_atuais_1855 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_18_5_5_input or "")]
                    links_antigos_1855 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_1855 or "")]

                    if (val_str_1855 != v_salvo_1855 or val_lk_1855 != l_salvo_1855) and links_atuais_1855 and links_atuais_1855 != links_antigos_1855:
                        st.session_state[f"links_pendentes_18_5_5_{ano_sel}"] = links_atuais_1855
                        st.session_state[f"gatilho_modal_18_5_5_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 18.5.5 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                st.markdown(
                    "<span style='color:#6c757d; font-weight:bold;'>"
                    "📊 Pontuação Aplicada no Quesito 18.5.5: +0.0 pontos (Dados Informativos)</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 18.5.5
        if st.session_state.get(f"gatilho_modal_18_5_5_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("18.5.5", st.session_state.get(f"links_pendentes_18_5_5_{ano_sel}", []), ano_sel)


        # =============================================================================
        # QUESITO 18.6 - PROGRAMA DE VOLTA PARA CASA
        # =============================================================================
        with st.container(key=f"container_bloco_pvc_18_6_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 18.6 • Adesão ao Programa De Volta para Casa ({ano_sel})", expanded=True):
                st.subheader(f"18.6 • Adesão ao Programa De Volta para Casa ({ano_sel})")
                st.write("**O município aderiu formalmente ao programa “De Volta para Casa” (PVC)?**")
                st.caption("ℹ️ *Selecione uma opção, informe o link de evidência e clique no botão 'Salvar Quesito 18.6' para registrar os dados.*")

                d18_6 = res_data.get("18.6") or {
                    "valor": "Selecione...",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_186 = d18_6.get("valor", "Selecione...")
                l_salvo_186 = d18_6.get("link", "")

                c186_1, c186_2 = st.columns([1, 1])

                with c186_1:
                    st.write("📋 **Selecione a opção correspondente:**")
                    opts_18_6 = ["Selecione...", "Sim", "Não"]
                    idx_186 = opts_18_6.index(v_salvo_186) if v_salvo_186 in opts_18_6 else 0
                    
                    sel_18_6 = st.radio(
                        "Adesão PVC:",
                        options=opts_18_6,
                        index=idx_186,
                        key=f"q186_rad_{ano_sel}"
                    )
                    pts_18_6 = 0.0

                with c186_2:
                    link_18_6_input = st.text_area(
                        "Termo de adesão ao PVC ou termo de compromisso federal/estadual (18.6):",
                        value=l_salvo_186,
                        key=f"txt_link_18_6_pvc_{ano_sel}",
                        height=200
                    )

                    links_186_visuais = re.findall(REGEX_PURE_URL, link_18_6_input or "")
                    if links_186_visuais:
                        st.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_186_visuais]
                            )
                        )

                # Chat de comentários
                bloco_comentarios_isaude("18.6", res_data)

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 18.6", key=f"btn_salvar_18_6_pvc_{ano_sel}", type="primary"):
                    val_str_186 = sel_18_6
                    val_lk_186 = link_18_6_input.strip()
                    comentarios_186 = d18_6.get("comentarios", [])

                    save_resp_isaude(
                        qid="18.6",
                        valor=val_str_186,
                        pontos=pts_18_6,
                        link=val_lk_186,
                        comentarios=comentarios_186
                    )

                    # Modal de aviso para links novos/alterados
                    links_atuais_186 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_18_6_input or "")]
                    links_antigos_186 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_186 or "")]

                    if (val_str_186 != v_salvo_186 or val_lk_186 != l_salvo_186) and links_atuais_186 and links_atuais_186 != links_antigos_186:
                        st.session_state[f"links_pendentes_18_6_{ano_sel}"] = links_atuais_186
                        st.session_state[f"gatilho_modal_18_6_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 18.6 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                st.markdown(
                    "<span style='color:#6c757d; font-weight:bold;'>"
                    "📊 Pontuação Aplicada no Quesito 18.6: +0.0 pontos (Dados Informativos)</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 18.6
        if st.session_state.get(f"gatilho_modal_18_6_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("18.6", st.session_state.get(f"links_pendentes_18_6_{ano_sel}", []), ano_sel)

        # =============================================================================
        # QUESITO 19.0 - DEMANDA DE MORADIA (LONGA PERMANÊNCIA)
        # =============================================================================
        with st.container(key=f"container_bloco_demanda_moradia_19_0_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 19.0 • Demanda de Moradia para Transtornos Mentais Crônicos ({ano_sel})", expanded=True):
                st.subheader(f"19.0 • Demanda de Moradia para Transtornos Mentais Crônicos ({ano_sel})")
                st.write(
                    "**No município, há demanda de moradia para portadores de transtornos mentais crônicos com necessidade "
                    "de cuidados de longa permanência, prioritariamente egressos de internações psiquiátricas e de hospitais de "
                    "custódia, que não possuam suporte financeiro, social e/ou laços familiares que permitam outra forma de reinserção?**"
                )
                st.caption("ℹ️ *Selecione uma opção, informe o link de evidência e clique no botão 'Salvar Quesito 19.0' para registrar os dados.*")

                d19_0 = res_data.get("19.0") or {
                    "valor": "Selecione...",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_190 = d19_0.get("valor", "Selecione...")
                l_salvo_190 = d19_0.get("link", "")

                c190_1, c190_2 = st.columns([1, 1])

                with c190_1:
                    st.write("📋 **Selecione a opção correspondente:**")
                    opts_19_0 = ["Selecione...", "Sim", "Não"]
                    idx_190 = opts_19_0.index(v_salvo_190) if v_salvo_190 in opts_19_0 else 0
                    
                    sel_19_0 = st.radio(
                        "Existência de demanda:",
                        options=opts_19_0,
                        index=idx_190,
                        key=f"q190_rad_{ano_sel}"
                    )
                    pts_19_0 = 0.0

                with c190_2:
                    link_19_0_input = st.text_area(
                        "Relatório descritivo da assistência social ou saúde mental sobre a demanda identificada (19.0):",
                        value=l_salvo_190,
                        key=f"txt_link_19_0_demanda_{ano_sel}",
                        height=200
                    )

                    links_190_visuais = re.findall(REGEX_PURE_URL, link_19_0_input or "")
                    if links_190_visuais:
                        st.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_190_visuais]
                            )
                        )

                # Chat de comentários
                bloco_comentarios_isaude("19.0", res_data)

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 19.0", key=f"btn_salvar_19_0_demanda_{ano_sel}", type="primary"):
                    val_str_190 = sel_19_0
                    val_lk_190 = link_19_0_input.strip()
                    comentarios_190 = d19_0.get("comentarios", [])

                    save_resp_isaude(
                        qid="19.0",
                        valor=val_str_190,
                        pontos=pts_19_0,
                        link=val_lk_190,
                        comentarios=comentarios_190
                    )

                    # Modal de aviso para links novos/alterados
                    links_atuais_190 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_19_0_input or "")]
                    links_antigos_190 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_190 or "")]

                    if (val_str_190 != v_salvo_190 or val_lk_190 != l_salvo_190) and links_atuais_190 and links_atuais_190 != links_antigos_190:
                        st.session_state[f"links_pendentes_19_0_{ano_sel}"] = links_atuais_190
                        st.session_state[f"gatilho_modal_19_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 19.0 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                st.markdown(
                    "<span style='color:#6c757d; font-weight:bold;'>"
                    "📊 Pontuação Aplicada no Quesito 19.0: +0.0 pontos (Dados Informativos)</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 19.0
        if st.session_state.get(f"gatilho_modal_19_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("19.0", st.session_state.get(f"links_pendentes_19_0_{ano_sel}", []), ano_sel)

        # =============================================================================
        # QUESITO 19.1 - ADEQUAÇÃO DA QUANTIDADE DE SRTs
        # =============================================================================
        with st.container(key=f"container_bloco_adequacao_srt_19_1_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 19.1 • Adequação da Quantidade de SRTs Ofertadas ({ano_sel})", expanded=True):
                st.subheader(f"19.1 • Adequação da Quantidade de SRTs Ofertadas ({ano_sel})")
                st.write(
                    "**A Quantidade de SRTs ofertadas é adequada, inclusive quanto a distribuição geográfica, para a demanda "
                    "de moradia para portadores de transtornos mentais crônicos com necessidade de cuidados de longa permanência, "
                    "prioritariamente egressos de internações psiquiátricas e de hospitais de custódia, que não possuam suporte "
                    "financeiro, social e/ou laços familiares que permitam outra forma de reinserção?**"
                )
                st.caption("ℹ️ *Selecione uma opção, informe o link de evidência e clique no botão 'Salvar Quesito 19.1' para registrar os dados.*")

                d19_1 = res_data.get("19.1") or {
                    "valor": "Selecione...",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_191 = d19_1.get("valor", "Selecione...")
                l_salvo_191 = d19_1.get("link", "")

                c191_1, c191_2 = st.columns([1, 1])

                with c191_1:
                    st.write("📋 **Selecione a opção correspondente:**")
                    opts_19_1 = ["Selecione...", "Sim", "Não"]
                    idx_191 = opts_19_1.index(v_salvo_191) if v_salvo_191 in opts_19_1 else 0
                    
                    sel_19_1 = st.radio(
                        "Adequação das SRTs:",
                        options=opts_19_1,
                        index=idx_191,
                        key=f"q191_rad_{ano_sel}"
                    )
                    pts_19_1 = 0.0

                with c191_2:
                    link_19_1_input = st.text_area(
                        "Justificativa de cobertura ou mapeamento territorial da RAPS (19.1):",
                        value=l_salvo_191,
                        key=f"txt_link_19_1_adeq_{ano_sel}",
                        height=200
                    )

                    links_191_visuais = re.findall(REGEX_PURE_URL, link_19_1_input or "")
                    if links_191_visuais:
                        st.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_191_visuais]
                            )
                        )

                # Chat de comentários
                bloco_comentarios_isaude("19.1", res_data)

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 19.1", key=f"btn_salvar_19_1_adeq_{ano_sel}", type="primary"):
                    val_str_191 = sel_19_1
                    val_lk_191 = link_19_1_input.strip()
                    comentarios_191 = d19_1.get("comentarios", [])

                    save_resp_isaude(
                        qid="19.1",
                        valor=val_str_191,
                        pontos=pts_19_1,
                        link=val_lk_191,
                        comentarios=comentarios_191
                    )

                    # Modal de aviso para links novos/alterados
                    links_atuais_191 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_19_1_input or "")]
                    links_antigos_191 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_191 or "")]

                    if (val_str_191 != v_salvo_191 or val_lk_191 != l_salvo_191) and links_atuais_191 and links_atuais_191 != links_antigos_191:
                        st.session_state[f"links_pendentes_19_1_{ano_sel}"] = links_atuais_191
                        st.session_state[f"gatilho_modal_19_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 19.1 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                st.markdown(
                    "<span style='color:#6c757d; font-weight:bold;'>"
                    "📊 Pontuação Aplicada no Quesito 19.1: +0.0 pontos (Dados Informativos)</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 19.1
        if st.session_state.get(f"gatilho_modal_19_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("19.1", st.session_state.get(f"links_pendentes_19_1_{ano_sel}", []), ano_sel)

        # =============================================================================
        # QUESITO 19.2 - QUANTIDADE DE UNIDADES DE SRT
        # =============================================================================
        with st.container(key=f"container_bloco_quant_srt_19_2_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 19.2 • Quantidade de Unidades de SRT ({ano_sel})", expanded=True):
                st.subheader(f"19.2 • Quantidade de Unidades de SRT ({ano_sel})")
                st.write("**Informe a quantidade de unidades de Serviços Residenciais Terapêuticos (SRT):**")
                st.caption("ℹ️ *Preencha os campos numéricos, informe o link de evidência e clique no botão 'Salvar Quesito 19.2' para registrar os dados.*")

                d19_2 = res_data.get("19.2") or {
                    "valor": "",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_192 = d19_2.get("valor", "")
                l_salvo_192 = d19_2.get("link", "")

                # Parsing do valor concatenado salvo no banco de dados (ex: "Para SRT tipo I:2|Para SRT tipo II:1|Equivalente:0")
                tipos_srt = ["Para SRT tipo I", "Para SRT tipo II", "Equivalente"]
                dict_vals_192 = {t: 0 for t in tipos_srt}
                
                if v_salvo_192:
                    for item in v_salvo_192.split("|"):
                        if ":" in item:
                            chave, *resto = item.split(":")
                            if chave in dict_vals_192:
                                try:
                                    dict_vals_192[chave] = int(resto[0])
                                except ValueError:
                                    pass

                c192_1, c192_2 = st.columns([1, 1])

                dict_inputs_192 = {}
                with c192_1:
                    st.write("🔢 **Informe as quantidades:**")
                    for t in tipos_srt:
                        dict_inputs_192[t] = st.number_input(
                            f"Quantidade ({t}):",
                            min_value=0,
                            step=1,
                            value=dict_vals_192[t],
                            key=f"q192_num_{t}_{ano_sel}"
                        )
                    pts_19_2 = 0.0

                with c192_2:
                    link_19_2_input = st.text_area(
                        "Cadastro CNES ou ato normativo de criação/credenciamento das unidades SRT (19.2):",
                        value=l_salvo_192,
                        key=f"txt_link_19_2_quant_{ano_sel}",
                        height=200
                    )

                    links_192_visuais = re.findall(REGEX_PURE_URL, link_19_2_input or "")
                    if links_192_visuais:
                        st.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_192_visuais]
                            )
                        )

                # Chat de comentários
                bloco_comentarios_isaude("19.2", res_data)

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 19.2", key=f"btn_salvar_19_2_quant_{ano_sel}", type="primary"):
                    # Reconstrução da string serializada contendo as quantidades
                    val_str_192 = "|".join([f"{t}:{dict_inputs_192[t]}" for t in tipos_srt])
                    val_lk_192 = link_19_2_input.strip()
                    comentarios_192 = d19_2.get("comentarios", [])

                    save_resp_isaude(
                        qid="19.2",
                        valor=val_str_192,
                        pontos=pts_19_2,
                        link=val_lk_192,
                        comentarios=comentarios_192
                    )

                    # Modal de aviso para links novos/alterados
                    links_atuais_192 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_19_2_input or "")]
                    links_antigos_192 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_192 or "")]

                    if (val_str_192 != v_salvo_192 or val_lk_192 != l_salvo_192) and links_atuais_192 and links_atuais_192 != links_antigos_192:
                        st.session_state[f"links_pendentes_19_2_{ano_sel}"] = links_atuais_192
                        st.session_state[f"gatilho_modal_19_2_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 19.2 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                st.markdown(
                    "<span style='color:#6c757d; font-weight:bold;'>"
                    "📊 Pontuação Aplicada no Quesito 19.2: +0.0 pontos (Dados Informativos)</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 19.2
        if st.session_state.get(f"gatilho_modal_19_2_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("19.2", st.session_state.get(f"links_pendentes_19_2_{ano_sel}", []), ano_sel)

        # =============================================================================
        # QUESITO 19.3 - CADASTRO DE VAGAS SRT NA REGULAÇÃO
        # =============================================================================
        with st.container(key=f"container_bloco_vagas_srt_regulacao_19_3_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 19.3 • Cadastro de Vagas SRT no Sistema de Regulação ({ano_sel})", expanded=True):
                st.subheader(f"19.3 • Cadastro de Vagas SRT no Sistema de Regulação ({ano_sel})")
                st.write(
                    "**As vagas dos Serviços Residenciais Terapêuticos ou equivalente para os "
                    "residentes do município estão cadastradas no sistema de informação de regulação?**"
                )
                st.caption("ℹ️ *Selecione uma opção, informe o link de evidência e clique no botão 'Salvar Quesito 19.3' para registrar os dados.*")

                d19_3 = res_data.get("19.3") or {
                    "valor": "Selecione...",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_193 = d19_3.get("valor", "Selecione...")
                l_salvo_193 = d19_3.get("link", "")

                c193_1, c193_2 = st.columns([1, 1])

                with c193_1:
                    st.write("📋 **Selecione a opção correspondente:**")
                    opts_19_3 = ["Selecione...", "Sim – 00", "Não – -10 (perde 10 pontos)"]
                    idx_193 = opts_19_3.index(v_salvo_193) if v_salvo_193 in opts_19_3 else 0

                    sel_19_3 = st.radio(
                        "Vagas SRT na regulação:",
                        options=opts_19_3,
                        index=idx_193,
                        key=f"q193_rad_{ano_sel}"
                    )

                    if "Não" in sel_19_3:
                        pts_19_3 = -10.0
                    else:
                        pts_19_3 = 0.0

                with c193_2:
                    link_19_3_input = st.text_area(
                        "Evidência de cadastro ou espelho do sistema de regulação (19.3):",
                        value=l_salvo_193,
                        key=f"txt_link_19_3_vagas_{ano_sel}",
                        height=200
                    )

                    links_193_visuais = re.findall(REGEX_PURE_URL, link_19_3_input or "")
                    if links_193_visuais:
                        st.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_193_visuais]
                            )
                        )

                # Chat de comentários
                bloco_comentarios_isaude("19.3", res_data)

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 19.3", key=f"btn_salvar_19_3_vagas_{ano_sel}", type="primary"):
                    val_str_193 = sel_19_3
                    val_lk_193 = link_19_3_input.strip()
                    comentarios_193 = d19_3.get("comentarios", [])

                    save_resp_isaude(
                        qid="19.3",
                        valor=val_str_193,
                        pontos=pts_19_3,
                        link=val_lk_193,
                        comentarios=comentarios_193
                    )

                    # Modal de aviso para links novos/alterados
                    links_atuais_193 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_19_3_input or "")]
                    links_antigos_193 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_193 or "")]

                    if (val_str_193 != v_salvo_193 or val_lk_193 != l_salvo_193) and links_atuais_193 and links_atuais_193 != links_antigos_193:
                        st.session_state[f"links_pendentes_19_3_{ano_sel}"] = links_atuais_193
                        st.session_state[f"gatilho_modal_19_3_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 19.3 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                if pts_19_3 < 0:
                    st.markdown(
                        f"<span style='color:#dc3545; font-weight:bold;'>"
                        f"📊 Pontuação Aplicada no Quesito 19.3: {pts_19_3:.1f} pontos (Penalidade)</span>",
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        f"<span style='color:#6c757d; font-weight:bold;'>"
                        f"📊 Pontuação Aplicada no Quesito 19.3: +{pts_19_3:.1f} pontos</span>",
                        unsafe_allow_html=True,
                    )

        # GATILHO DO MODAL 19.3
        if st.session_state.get(f"gatilho_modal_19_3_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("19.3", st.session_state.get(f"links_pendentes_19_3_{ano_sel}", []), ano_sel)


        # =============================================================================
        # QUESITO 19.3.1 - QUANTIDADE DE VAGAS CADASTRADAS NA REGULAÇÃO
        # =============================================================================
        with st.container(key=f"container_bloco_quant_vagas_srt_19_3_1_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 19.3.1 • Quantidade de Vagas SRT Cadastradas na Regulação ({ano_sel})", expanded=True):
                st.subheader(f"19.3.1 • Quantidade de Vagas SRT Cadastradas na Regulação ({ano_sel})")
                st.write("**Informe a quantidade de vagas cadastradas no sistema de regulação:**")
                st.caption("ℹ️ *Preencha a quantidade de vagas, informe o link de evidência e clique no botão 'Salvar Quesito 19.3.1' para registrar os dados.*")

                d19_3_1 = res_data.get("19.3.1") or {
                    "valor": "",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_1931 = d19_3_1.get("valor", "")
                l_salvo_1931 = d19_3_1.get("link", "")

                # Desserialização dos valores salvos
                vals_1931 = v_salvo_1931.split("|") if v_salvo_1931 else []
                tipos_vagas_srt = ["Para SRT tipo I", "Para SRT tipo II", "Equivalente"]
                dict_vals_1931 = {t: 0 for t in tipos_vagas_srt}

                for v in vals_1931:
                    if ":" in v:
                        chave, *resto = v.split(":")
                        if chave in dict_vals_1931 and resto:
                            try:
                                dict_vals_1931[chave] = int(resto[0])
                            except ValueError:
                                dict_vals_1931[chave] = 0

                c1931_1, c1931_2 = st.columns([1, 1])

                with c1931_1:
                    st.write("📋 **Informe a quantidade por categoria:**")
                    novos_vals_1931 = []
                    for t in tipos_vagas_srt:
                        qtd_vagas_reg = st.number_input(
                            f"Vagas Reguladas {t}:",
                            min_value=0,
                            step=1,
                            value=dict_vals_1931[t],
                            key=f"num_1931_{t}_{ano_sel}"
                        )
                        novos_vals_1931.append(f"{t}:{qtd_vagas_reg}")
                    
                    string_estruturada_1931 = "|".join(novos_vals_1931)
                    pts_19_3_1 = 0.0

                with c1931_2:
                    link_19_3_1_input = st.text_area(
                        "Relatório extraído do sistema informático (CROSS/SISREG ou similar) (19.3.1):",
                        value=l_salvo_1931,
                        key=f"txt_link_19_3_1_quant_{ano_sel}",
                        height=200
                    )

                    links_1931_visuais = re.findall(REGEX_PURE_URL, link_19_3_1_input or "")
                    if links_1931_visuais:
                        st.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_1931_visuais]
                            )
                        )

                # Chat de comentários
                bloco_comentarios_isaude("19.3.1", res_data)

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 19.3.1", key=f"btn_salvar_19_3_1_quant_{ano_sel}", type="primary"):
                    val_str_1931 = string_estruturada_1931
                    val_lk_1931 = link_19_3_1_input.strip()
                    comentarios_1931 = d19_3_1.get("comentarios", [])

                    save_resp_isaude(
                        qid="19.3.1",
                        valor=val_str_1931,
                        pontos=pts_19_3_1,
                        link=val_lk_1931,
                        comentarios=comentarios_1931
                    )

                    # Modal de aviso para links novos/alterados
                    links_atuais_1931 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_19_3_1_input or "")]
                    links_antigos_1931 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_1931 or "")]

                    if (val_str_1931 != v_salvo_1931 or val_lk_1931 != l_salvo_1931) and links_atuais_1931 and links_atuais_1931 != links_antigos_1931:
                        st.session_state[f"links_pendentes_19_3_1_{ano_sel}"] = links_atuais_1931
                        st.session_state[f"gatilho_modal_19_3_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 19.3.1 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                st.markdown(
                    f"<span style='color:#6c757d; font-weight:bold;'>"
                    f"📊 Pontuação Aplicada no Quesito 19.3.1: +{pts_19_3_1:.1f} pontos (Dados Informativos)</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 19.3.1
        if st.session_state.get(f"gatilho_modal_19_3_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("19.3.1", st.session_state.get(f"links_pendentes_19_3_1_{ano_sel}", []), ano_sel)

        # =============================================================================
        # QUESITO 19.4 - ROTINAS DE ACOMPANHAMENTO E AVALIAÇÃO SRT
        # =============================================================================
        with st.container(key=f"container_bloco_rotinas_srt_19_4_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 19.4 • Rotinas de Acompanhamento e Avaliação das SRTs ({ano_sel})", expanded=True):
                st.subheader(f"19.4 • Rotinas de Acompanhamento e Avaliação das SRTs ({ano_sel})")
                st.write(
                    "**A Secretaria Municipal de Saúde (ou equivalente), com apoio técnico do Ministério da Saúde, "
                    "tem rotinas estabelecidas de acompanhamento, supervisão, controle e avaliação para a garantia do "
                    "funcionamento com qualidade dos Serviços Residenciais Terapêuticos em Saúde Mental?**"
                )
                st.caption("ℹ️ *Selecione uma opção, informe o link de evidência e clique no botão 'Salvar Quesito 19.4' para registrar os dados.*")

                d19_4 = res_data.get("19.4") or {
                    "valor": "Selecione...",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_194 = d19_4.get("valor", "Selecione...")
                l_salvo_194 = d19_4.get("link", "")

                c194_1, c194_2 = st.columns([1, 1])

                with c194_1:
                    st.write("📋 **Selecione a opção correspondente:**")
                    opts_19_4 = ["Selecione...", "Sim – 00", "Não – -05 (perde 05 pontos)"]
                    idx_194 = opts_19_4.index(v_salvo_194) if v_salvo_194 in opts_19_4 else 0

                    sel_19_4 = st.radio(
                        "Rotinas estabelecidas:",
                        options=opts_19_4,
                        index=idx_194,
                        key=f"q194_rad_{ano_sel}"
                    )

                    if "Não" in sel_19_4:
                        pts_19_4 = -5.0
                    else:
                        pts_19_4 = 0.0

                with c194_2:
                    link_19_4_input = st.text_area(
                        "Evidência de atas de supervisão, relatórios de monitoramento ou cronograma técnico (19.4):",
                        value=l_salvo_194,
                        key=f"txt_link_19_4_rotinas_{ano_sel}",
                        height=200
                    )

                    links_194_visuais = re.findall(REGEX_PURE_URL, link_19_4_input or "")
                    if links_194_visuais:
                        st.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_194_visuais]
                            )
                        )

                # Chat de comentários
                bloco_comentarios_isaude("19.4", res_data)

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 19.4", key=f"btn_salvar_19_4_rotinas_{ano_sel}", type="primary"):
                    val_str_194 = sel_19_4
                    val_lk_194 = link_19_4_input.strip()
                    comentarios_194 = d19_4.get("comentarios", [])

                    save_resp_isaude(
                        qid="19.4",
                        valor=val_str_194,
                        pontos=pts_19_4,
                        link=val_lk_194,
                        comentarios=comentarios_194
                    )

                    # Modal de aviso para links novos/alterados
                    links_atuais_194 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_19_4_input or "")]
                    links_antigos_194 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_194 or "")]

                    if (val_str_194 != v_salvo_194 or val_lk_194 != l_salvo_194) and links_atuais_194 and links_atuais_194 != links_antigos_194:
                        st.session_state[f"links_pendentes_19_4_{ano_sel}"] = links_atuais_194
                        st.session_state[f"gatilho_modal_19_4_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 19.4 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                if pts_19_4 < 0:
                    st.markdown(
                        f"<span style='color:#dc3545; font-weight:bold;'>"
                        f"📊 Pontuação Aplicada no Quesito 19.4: {pts_19_4:.1f} pontos (Penalidade)</span>",
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        f"<span style='color:#6c757d; font-weight:bold;'>"
                        f"📊 Pontuação Aplicada no Quesito 19.4: +{pts_19_4:.1f} pontos</span>",
                        unsafe_allow_html=True,
                    )

        # GATILHO DO MODAL 19.4
        if st.session_state.get(f"gatilho_modal_19_4_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("19.4", st.session_state.get(f"links_pendentes_19_4_{ano_sel}", []), ano_sel)


        # =============================================================================
        # QUESITO 19.5 - CÁLCULO DE EVOLUÇÃO LEITOS VS VAGAS SRT (DINÂMICO)
        # =============================================================================
        ano_atual_int = int(ano_sel)
        ano_anterior_int = ano_atual_int - 1

        with st.container(key=f"container_bloco_evolucao_srt_leitos_19_5_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 19.5 • Indicador de Desinstitucionalização (Leitos vs. Vagas SRT) ({ano_sel})", expanded=True):
                st.subheader(f"19.5 • Indicador de Desinstitucionalização (Leitos vs. Vagas SRT) ({ano_sel})")
                st.write(f"**Avaliação da série histórica (Data Base Mês Dezembro): Redução de Leitos de Internação Psiquiátrica Prolongada vs. Expansão de SRTs**")
                st.caption("ℹ️ *Preencha os valores numéricos, informe o link de evidência e clique no botão 'Salvar Quesito 19.5' para registrar os dados.*")

                d19_5 = res_data.get("19.5") or {
                    "valor": "0|0|0|0",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_195 = d19_5.get("valor", "0|0|0|0")
                l_salvo_195 = d19_5.get("link", "")

                vals_195 = v_salvo_195.split("|") if v_salvo_195 else []

                try:
                    la_minus_1 = int(vals_195[0])
                except (IndexError, ValueError):
                    la_minus_1 = 0

                try:
                    la_atual = int(vals_195[1])
                except (IndexError, ValueError):
                    la_atual = 0

                try:
                    va_minus_1 = int(vals_195[2])
                except (IndexError, ValueError):
                    va_minus_1 = 0

                try:
                    va_atual = int(vals_195[3])
                except (IndexError, ValueError):
                    va_atual = 0

                c195_1, c195_2 = st.columns([1, 1])

                with c195_1:
                    st.markdown("**Leitos de Internação Psiquiátrica Prolongada:**")
                    la_minus_1_input = st.number_input(
                        f"Nº de leitos sob gestão municipal - {ano_anterior_int} (LA-1):",
                        min_value=0,
                        step=1,
                        value=la_minus_1,
                        key=f"num_195_la_minus_1_{ano_sel}"
                    )
                    la_atual_input = st.number_input(
                        f"Nº de leitos sob gestão municipal - {ano_atual_int} (LA):",
                        min_value=0,
                        step=1,
                        value=la_atual,
                        key=f"num_195_la_atual_{ano_sel}"
                    )

                    st.markdown("**Vagas Disponibilizadas em SRT:**")
                    va_minus_1_input = st.number_input(
                        f"Nº de vagas em SRT sob gestão municipal - {ano_anterior_int} (VA-1):",
                        min_value=0,
                        step=1,
                        value=va_minus_1,
                        key=f"num_195_va_minus_1_{ano_sel}"
                    )
                    va_atual_input = st.number_input(
                        f"Nº de vagas em SRT sob gestão municipal - {ano_atual_int} (VA):",
                        min_value=0,
                        step=1,
                        value=va_atual,
                        key=f"num_195_va_atual_{ano_sel}"
                    )

                with c195_2:
                    link_19_5_input = st.text_area(
                        f"Relatório do CNES ou ato formal de desospitalização/extinção de leitos ({ano_anterior_int}-{ano_atual_int}) (19.5):",
                        value=l_salvo_195,
                        key=f"txt_link_19_5_evolucao_{ano_sel}",
                        height=250
                    )

                    links_195_visuais = re.findall(REGEX_PURE_URL, link_19_5_input or "")
                    if links_195_visuais:
                        st.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_195_visuais]
                            )
                        )

                # CÁLCULO DA REGRA DE PENALIZAÇÃO
                pts_19_5 = 0.0
                motivo_penalidade = []

                # Recuperação das unidades de 19.2 para validação cruzada
                d19_2 = res_data.get("19.2") or {"valor": ""}
                vals_192 = d19_2.get("valor", "").split("|") if d19_2.get("valor") else []
                soma_unidades_192 = 0
                for v in vals_192:
                    if ":" in v:
                        try:
                            soma_unidades_192 += int(v.split(":")[1])
                        except ValueError:
                            pass

                # Condição 1: Sem SRTs
                if soma_unidades_192 == 0 or va_atual_input == 0:
                    pts_19_5 = -15.0
                    motivo_penalidade.append(f"Município não possui unidades registradas no quesito 19.2 ou o número de vagas em {ano_atual_int} (VA) é zero.")

                # Condição 2: Aumento de Leitos
                if la_atual_input > la_minus_1_input:
                    pts_19_5 = -15.0
                    motivo_penalidade.append(f"Houve aumento de leitos psiquiátricos (LA de {ano_atual_int} [{la_atual_input}] > LA-1 de {ano_anterior_int} [{la_minus_1_input}]).")

                # Condição 3: Diminuição de SRTs ou redução de leitos superior à expansão de SRTs
                if va_atual_input < va_minus_1_input:
                    pts_19_5 = -15.0
                    motivo_penalidade.append(f"Houve diminuição no número absoluto de vagas de SRT (VA de {ano_atual_int} [{va_atual_input}] < VA-1 de {ano_anterior_int} [{va_minus_1_input}]).")

                reducao_leitos = la_minus_1_input - la_atual_input
                aumento_srt = va_atual_input - va_minus_1_input
                if reducao_leitos > aumento_srt:
                    pts_19_5 = -15.0
                    motivo_penalidade.append(f"A redução de leitos foi maior do que a capacidade de absorção em novas vagas de SRT (Redução de leitos: {reducao_leitos} > Aumento de SRT: {aumento_srt}).")

                # Exibição do feedback das regras
                if pts_19_5 < 0:
                    texto_erros = "⚠️ **Critério de Penalidade Atingido conforme regras do quesito:**\n\n"
                    for motivo in motivo_penalidade:
                        texto_erros += f"❌ *{motivo}*\n\n"
                    st.error(texto_erros)
                else:
                    st.success("✅ Critério de conformidade atingido (Diminuição de leitos menor ou igual ao aumento de SRTs) ou (Manutenção/Aumento de SRTs).")

                # Chat de comentários
                bloco_comentarios_isaude("19.5", res_data)

                # String estruturada dos dados numéricos
                string_estruturada_195 = f"{la_minus_1_input}|{la_atual_input}|{va_minus_1_input}|{va_atual_input}"

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 19.5", key=f"btn_salvar_19_5_evolucao_{ano_sel}", type="primary"):
                    val_str_195 = string_estruturada_195
                    val_lk_195 = link_19_5_input.strip()
                    comentarios_195 = d19_5.get("comentarios", [])

                    save_resp_isaude(
                        qid="19.5",
                        valor=val_str_195,
                        pontos=pts_19_5,
                        link=val_lk_195,
                        comentarios=comentarios_195
                    )

                    # Modal de aviso para links novos/alterados
                    links_atuais_195 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_19_5_input or "")]
                    links_antigos_195 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_195 or "")]

                    if (val_str_195 != v_salvo_195 or val_lk_195 != l_salvo_195) and links_atuais_195 and links_atuais_195 != links_antigos_195:
                        st.session_state[f"links_pendentes_19_5_{ano_sel}"] = links_atuais_195
                        st.session_state[f"gatilho_modal_19_5_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 19.5 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                if pts_19_5 < 0:
                    st.markdown(
                        f"<span style='color:#dc3545; font-weight:bold;'>"
                        f"📊 Pontuação Aplicada no Quesito 19.5: {pts_19_5:.1f} pontos (Fórmula Aplica Perda Máxima de 15 pts)</span>",
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        f"<span style='color:#6c757d; font-weight:bold;'>"
                        f"📊 Pontuação Aplicada no Quesito 19.5: +{pts_19_5:.1f} pontos (Sem penalidades aplicadas)</span>",
                        unsafe_allow_html=True,
                    )

        # GATILHO DO MODAL 19.5
        if st.session_state.get(f"gatilho_modal_19_5_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("19.5", st.session_state.get(f"links_pendentes_19_5_{ano_sel}", []), ano_sel)

        # =============================================================================
        # SEÇÃO 20 - VIGILÂNCIA EM SAÚDE
        # =============================================================================
        st.subheader("🛡️ Seção 20 - Vigilância em Saúde")

        # -----------------------------------------------------------------------------
        # QUESITO 20.0 - GESTÃO DE INSUMOS
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_gestao_insumos_20_0_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 20.0 • Tipos de Insumos sob Gestão Municipal ({ano_sel})", expanded=True):
                st.subheader(f"20.0 • Tipos de Insumos sob Gestão Municipal ({ano_sel})")
                st.write("**Sobre Vigilância em Saúde, a Prefeitura realiza gestão de quais tipos de insumos?**")
                st.caption("ℹ️ *Marque as opções aplicáveis, informe o link de evidência e clique no botão 'Salvar Quesito 20.0' para registrar os dados.*")

                d20_0 = res_data.get("20.0") or {
                    "valor": "",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_200 = d20_0.get("valor", "")
                l_salvo_200 = d20_0.get("link", "")

                v20_0_list = v_salvo_200.split("|") if v_salvo_200 else []

                c200_1, c200_2 = st.columns([1, 1])

                with c200_1:
                    st.write("📋 **Selecione os tipos de insumos sob gestão:**")
                    insumo_imuno = st.checkbox(
                        "Imunobiológicos (soros, vacinas e imunoglobulinas) [Informativo / 0.0 pt]",
                        value="Imunobiológicos" in v20_0_list,
                        key=f"chk_20_0_imuno_{ano_sel}"
                    )
                    insumo_diag = st.checkbox(
                        "Meios de diagnóstico laboratorial para as doenças sob monitoramento epidemiológico [Informativo / 0.0 pt]",
                        value="Diagnóstico" in v20_0_list,
                        key=f"chk_20_0_diag_{ano_sel}"
                    )
                    insumo_vetor = st.checkbox(
                        "Controle de vetores (inseticidas, larvicidas) [Informativo / 0.0 pt]",
                        value="Vetores" in v20_0_list,
                        key=f"chk_20_0_vetor_{ano_sel}"
                    )
                    pts_20_0 = 0.0

                with c200_2:
                    link_20_0_input = st.text_area(
                        "Link/Evidência de atos, relatórios de estoque ou sistema de controle (20.0):",
                        value=l_salvo_200,
                        key=f"txt_link_20_0_insumos_{ano_sel}",
                        height=180
                    )

                    links_200_visuais = re.findall(REGEX_PURE_URL, link_20_0_input or "")
                    if links_200_visuais:
                        st.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_200_visuais]
                            )
                        )

                # Montagem da string dos selecionados
                selecionados_20_0 = []
                if insumo_imuno:
                    selecionados_20_0.append("Imunobiológicos")
                if insumo_diag:
                    selecionados_20_0.append("Diagnóstico")
                if insumo_vetor:
                    selecionados_20_0.append("Vetores")

                str_20_0 = "|".join(selecionados_20_0)

                # Chat de comentários
                bloco_comentarios_isaude("20.0", res_data)

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 20.0", key=f"btn_salvar_20_0_insumos_{ano_sel}", type="primary"):
                    val_str_200 = str_20_0
                    val_lk_200 = link_20_0_input.strip()
                    comentarios_200 = d20_0.get("comentarios", [])

                    save_resp_isaude(
                        qid="20.0",
                        valor=val_str_200,
                        pontos=pts_20_0,
                        link=val_lk_200,
                        comentarios=comentarios_200
                    )

                    # Modal de aviso para links novos/alterados
                    links_atuais_200 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_20_0_input or "")]
                    links_antigos_200 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_200 or "")]

                    if (val_str_200 != v_salvo_200 or val_lk_200 != l_salvo_200) and links_atuais_200 and links_atuais_200 != links_antigos_200:
                        st.session_state[f"links_pendentes_20_0_{ano_sel}"] = links_atuais_200
                        st.session_state[f"gatilho_modal_20_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 20.0 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                st.markdown(
                    f"<span style='color:#6c757d; font-weight:bold;'>"
                    f"📊 Pontuação Aplicada no Quesito 20.0: +{pts_20_0:.1f} pontos (Dados Informativos)</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 20.0
        if st.session_state.get(f"gatilho_modal_20_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("20.0", st.session_state.get(f"links_pendentes_20_0_{ano_sel}", []), ano_sel)


        # -----------------------------------------------------------------------------
        # QUESITO 20.1 - USO DE FRIGOBAR
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_uso_frigobar_20_1_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 20.1 • Uso de Frigobar para Imunobiológicos ({ano_sel})", expanded=True):
                st.subheader(f"20.1 • Uso de Frigobar para Imunobiológicos ({ano_sel})")
                st.write(
                    "**A Prefeitura utiliza frigobar para refrigeração, manutenção, monitoramento e controle "
                    "da temperatura dos imunobiológicos (soros, vacinas e imunoglobulinas)?**"
                )
                st.caption("ℹ️ *Selecione uma opção, informe o link de evidência e clique no botão 'Salvar Quesito 20.1' para registrar os dados.*")

                d20_1 = res_data.get("20.1") or {
                    "valor": "Selecione...",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_201 = d20_1.get("valor", "Selecione...")
                l_salvo_201 = d20_1.get("link", "")

                # Dicionário de opções com os pontos explicitados nos rótulos
                opcoes_map_20_1 = {
                    "Selecione...": {"label": "Selecione...", "pts": 0.0},
                    "Sim, em todos os estabelecimentos de saúde sob gestão municipal": {
                        "label": "Sim, em todos os estabelecimentos de saúde sob gestão municipal (-5.0 pts)",
                        "pts": -5.0
                    },
                    "Sim, na maior parte dos estabelecimentos de saúde sob gestão municipal": {
                        "label": "Sim, na maior parte dos estabelecimentos de saúde sob gestão municipal (-3.0 pts)",
                        "pts": -3.0
                    },
                    "Sim, na menor parte dos estabelecimentos de saúde sob gestão municipal": {
                        "label": "Sim, na menor parte dos estabelecimentos de saúde sob gestão municipal (-1.0 pt)",
                        "pts": -1.0
                    },
                    "Não": {
                        "label": "Não (0.0 pt)",
                        "pts": 0.0
                    }
                }

                opts_20_1_chaves = list(opcoes_map_20_1.keys())
                opts_20_1_labels = [opcoes_map_20_1[k]["label"] for k in opts_20_1_chaves]

                # Localização do índice salvo (tratando formato com ou sem label de pontos)
                idx_201 = 0
                for i, k in enumerate(opts_20_1_chaves):
                    if v_salvo_201 == k or v_salvo_201 == opcoes_map_20_1[k]["label"]:
                        idx_201 = i
                        break

                c201_1, c201_2 = st.columns([1, 1])

                with c201_1:
                    st.write("📋 **Selecione a extensão de uso de frigobar:**")

                    label_selecionada = st.radio(
                        "Uso de Frigobar:",
                        options=opts_20_1_labels,
                        index=idx_201,
                        key=f"rad_20_1_{ano_sel}",
                        label_visibility="collapsed"
                    )

                    # Mapeamento da chave e pontos correspondentes à seleção
                    chave_selecionada = opts_20_1_chaves[opts_20_1_labels.index(label_selecionada)]
                    pts_20_1 = opcoes_map_20_1[chave_selecionada]["pts"]

                with c201_2:
                    link_20_1_input = st.text_area(
                        "Link/Evidência de inventários de equipamentos de rede de frio ou relatórios de vistoria (20.1):",
                        value=l_salvo_201,
                        key=f"txt_link_20_1_frigobar_{ano_sel}",
                        height=180
                    )

                    links_201_visuais = re.findall(REGEX_PURE_URL, link_20_1_input or "")
                    if links_201_visuais:
                        st.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_201_visuais]
                            )
                        )

                # Feedback visual de regra
                if chave_selecionada != "Selecione..." and pts_20_1 < 0:
                    st.error(f"⚠️ Penalidade aplicada: {pts_20_1:.1f} pontos devido ao uso inadequado de frigobar para imunobiológicos.")
                elif chave_selecionada == "Não":
                    st.success("✅ Regular: O município não utiliza frigobares para armazenamento de imunobiológicos.")

                # Chat de comentários
                bloco_comentarios_isaude("20.1", res_data)

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 20.1", key=f"btn_salvar_20_1_frigobar_{ano_sel}", type="primary"):
                    val_str_201 = chave_selecionada
                    val_lk_201 = link_20_1_input.strip()
                    comentarios_201 = d20_1.get("comentarios", [])

                    save_resp_isaude(
                        qid="20.1",
                        valor=val_str_201,
                        pontos=pts_20_1,
                        link=val_lk_201,
                        comentarios=comentarios_201
                    )

                    # Modal de aviso para links novos/alterados
                    links_atuais_201 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_20_1_input or "")]
                    links_antigos_201 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_201 or "")]

                    if (val_str_201 != v_salvo_201 or val_lk_201 != l_salvo_201) and links_atuais_201 and links_atuais_201 != links_antigos_201:
                        st.session_state[f"links_pendentes_20_1_{ano_sel}"] = links_atuais_201
                        st.session_state[f"gatilho_modal_20_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 20.1 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                if pts_20_1 < 0:
                    st.markdown(
                        f"<span style='color:#dc3545; font-weight:bold;'>"
                        f"📊 Pontuação Aplicada no Quesito 20.1: {pts_20_1:.1f} pontos (Penalidade)</span>",
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        f"<span style='color:#6c757d; font-weight:bold;'>"
                        f"📊 Pontuação Aplicada no Quesito 20.1: +{pts_20_1:.1f} pontos</span>",
                        unsafe_allow_html=True,
                    )

        # GATILHO DO MODAL 20.1
        if st.session_state.get(f"gatilho_modal_20_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("20.1", st.session_state.get(f"links_pendentes_20_1_{ano_sel}", []), ano_sel)

        # -----------------------------------------------------------------------------
        # QUESITO 20.2 - MATERIAIS PARA DIAGNÓSTICO LABORATORIAL
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_materiais_diag_20_2_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 20.2 • Materiais para Coleta de Diagnóstico Laboratorial ({ano_sel})", expanded=True):
                st.subheader(f"20.2 • Materiais para Coleta de Diagnóstico Laboratorial ({ano_sel})")
                st.write(
                    "**A Prefeitura disponibilizou os materiais necessários para a coleta dos meios de diagnóstico laboratorial "
                    "para as doenças sob monitoramento epidemiológico (coleta de sangue, fluidos orgânicos como: saliva, secreção, suor, urina, fezes)?**"
                )
                st.caption("ℹ️ *Selecione uma opção, informe o link de evidência e clique no botão 'Salvar Quesito 20.2' para registrar os dados.*")

                d20_2 = res_data.get("20.2") or {
                    "valor": "Selecione...",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_202 = d20_2.get("valor", "Selecione...")
                l_salvo_202 = d20_2.get("link", "")

                # Dicionário de opções com os pontos explicitados nos rótulos
                opcoes_map_20_2 = {
                    "Selecione...": {"label": "Selecione...", "pts": 0.0},
                    "Sim, para todas as amostras": {
                        "label": "Sim, para todas as amostras (0.0 pt)",
                        "pts": 0.0
                    },
                    "Sim, para a maior parte das amostras": {
                        "label": "Sim, para a maior parte das amostras (-1.0 pt)",
                        "pts": -1.0
                    },
                    "Sim, para a menor parte das amostras": {
                        "label": "Sim, para a menor parte das amostras (-3.0 pts)",
                        "pts": -3.0
                    },
                    "Não": {
                        "label": "Não (-5.0 pts)",
                        "pts": -5.0
                    }
                }

                opts_20_2_chaves = list(opcoes_map_20_2.keys())
                opts_20_2_labels = [opcoes_map_20_2[k]["label"] for k in opts_20_2_chaves]

                # Localização do índice salvo
                idx_202 = 0
                for i, k in enumerate(opts_20_2_chaves):
                    if v_salvo_202 == k or v_salvo_202 == opcoes_map_20_2[k]["label"]:
                        idx_202 = i
                        break

                c202_1, c202_2 = st.columns([1, 1])

                with c202_1:
                    st.write("📋 **Selecione a disponibilidade dos materiais:**")

                    label_selecionada_202 = st.radio(
                        "Materiais Diagnóstico:",
                        options=opts_20_2_labels,
                        index=idx_202,
                        key=f"rad_20_2_{ano_sel}",
                        label_visibility="collapsed"
                    )

                    chave_selecionada_202 = opts_20_2_chaves[opts_20_2_labels.index(label_selecionada_202)]
                    pts_20_2 = opcoes_map_20_2[chave_selecionada_202]["pts"]

                with c202_2:
                    link_20_2_input = st.text_area(
                        "Link/Evidência de ordens de compra, notas fiscais ou controle de estoque (20.2):",
                        value=l_salvo_202,
                        key=f"txt_link_20_2_diag_{ano_sel}",
                        height=180
                    )

                    links_202_visuais = re.findall(REGEX_PURE_URL, link_20_2_input or "")
                    if links_202_visuais:
                        st.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_202_visuais]
                            )
                        )

                # Feedback visual de regra
                if chave_selecionada_202 != "Selecione..." and pts_20_2 < 0:
                    st.error(f"⚠️ Penalidade aplicada: {pts_20_2:.1f} pontos devido à indisponibilidade total de materiais para diagnósticos.")
                elif chave_selecionada_202 == "Sim, para todas as amostras":
                    st.success("✅ Em conformidade: Fornecimento total garantido para coleta de amostras.")

                # Chat de comentários
                bloco_comentarios_isaude("20.2", res_data)

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 20.2", key=f"btn_salvar_20_2_diag_{ano_sel}", type="primary"):
                    val_str_202 = chave_selecionada_202
                    val_lk_202 = link_20_2_input.strip()
                    comentarios_202 = d20_2.get("comentarios", [])

                    save_resp_isaude(
                        qid="20.2",
                        valor=val_str_202,
                        pontos=pts_20_2,
                        link=val_lk_202,
                        comentarios=comentarios_202
                    )

                    # Modal de aviso para links novos/alterados
                    links_atuais_202 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_20_2_input or "")]
                    links_antigos_202 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_202 or "")]

                    if (val_str_202 != v_salvo_202 or val_lk_202 != l_salvo_202) and links_atuais_202 and links_atuais_202 != links_antigos_202:
                        st.session_state[f"links_pendentes_20_2_{ano_sel}"] = links_atuais_202
                        st.session_state[f"gatilho_modal_20_2_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 20.2 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                if pts_20_2 < 0:
                    st.markdown(
                        f"<span style='color:#dc3545; font-weight:bold;'>"
                        f"📊 Pontuação Aplicada no Quesito 20.2: {pts_20_2:.1f} pontos (Penalidade)</span>",
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        f"<span style='color:#6c757d; font-weight:bold;'>"
                        f"📊 Pontuação Aplicada no Quesito 20.2: +{pts_20_2:.1f} pontos</span>",
                        unsafe_allow_html=True,
                    )

        # GATILHO DO MODAL 20.2
        if st.session_state.get(f"gatilho_modal_20_2_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("20.2", st.session_state.get(f"links_pendentes_20_2_{ano_sel}", []), ano_sel)


        # -----------------------------------------------------------------------------
        # QUESITO 20.3 - EPI PARA CONTROLE DE VETORES
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_epi_vetores_20_3_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 20.3 • Equipamentos de Proteção Individual (EPI) ({ano_sel})", expanded=True):
                st.subheader(f"20.3 • Equipamentos de Proteção Individual (EPI) ({ano_sel})")
                st.write(
                    "**A Prefeitura disponibilizou todos os equipamentos de proteção individual (EPIs) "
                    "para o manuseio dos insumos para controle de vetores (inseticidas e pesticidas)?**"
                )
                st.caption("ℹ️ *Selecione uma opção, informe o link de evidência e clique no botão 'Salvar Quesito 20.3' para registrar os dados.*")

                d20_3 = res_data.get("20.3") or {
                    "valor": "Selecione...",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_203 = d20_3.get("valor", "Selecione...")
                l_salvo_203 = d20_3.get("link", "")

                # Dicionário de opções com os pontos explicitados nos rótulos
                opcoes_map_20_3 = {
                    "Selecione...": {"label": "Selecione...", "pts": 0.0},
                    "Sim, para todos os profissionais": {
                        "label": "Sim, para todos os profissionais (0.0 pt)",
                        "pts": 0.0
                    },
                    "Sim, para a maior parte dos profissionais": {
                        "label": "Sim, para a maior parte dos profissionais (-1.0 pt)",
                        "pts": -1.0
                    },
                    "Sim, para a menor parte dos profissionais": {
                        "label": "Sim, para a menor parte dos profissionais (-3.0 pts)",
                        "pts": -3.0
                    },
                    "Não": {
                        "label": "Não (-5.0 pts)",
                        "pts": -5.0
                    }
                }

                opts_20_3_chaves = list(opcoes_map_20_3.keys())
                opts_20_3_labels = [opcoes_map_20_3[k]["label"] for k in opts_20_3_chaves]

                # Localização do índice salvo (suportando formatos antigos com texto extra)
                idx_203 = 0
                for i, k in enumerate(opts_20_3_chaves):
                    if v_salvo_203 == k or v_salvo_203.startswith(k) or v_salvo_203 == opcoes_map_20_3[k]["label"]:
                        idx_203 = i
                        break

                c203_1, c203_2 = st.columns([1, 1])

                with c203_1:
                    st.write("📋 **Selecione a disponibilização de EPIs:**")

                    label_selecionada_203 = st.radio(
                        "Disponibilização de EPIs:",
                        options=opts_20_3_labels,
                        index=idx_203,
                        key=f"rad_20_3_{ano_sel}",
                        label_visibility="collapsed"
                    )

                    chave_selecionada_203 = opts_20_3_chaves[opts_20_3_labels.index(label_selecionada_203)]
                    pts_20_3 = opcoes_map_20_3[chave_selecionada_203]["pts"]

                with c203_2:
                    link_20_3_input = st.text_area(
                        "Link/Evidência de relatórios de entrega de EPIs, cautelas ou processos de compra (20.3):",
                        value=l_salvo_203,
                        key=f"txt_link_20_3_epi_{ano_sel}",
                        height=180
                    )

                    links_203_visuais = re.findall(REGEX_PURE_URL, link_20_3_input or "")
                    if links_203_visuais:
                        st.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_203_visuais]
                            )
                        )

                # Feedback visual de regra
                if chave_selecionada_203 != "Selecione..." and pts_20_3 < 0:
                    st.error(f"⚠️ Penalidade aplicada: {pts_20_3:.1f} pontos devido à falta de EPIs para manuseio de insumos de vetores.")
                elif chave_selecionada_203 == "Sim, para todos os profissionais":
                    st.success("✅ Em conformidade: EPIs fornecidos integralmente a todos os profissionais.")

                # Chat de comentários
                bloco_comentarios_isaude("20.3", res_data)

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 20.3", key=f"btn_salvar_20_3_epi_{ano_sel}", type="primary"):
                    val_str_203 = chave_selecionada_203
                    val_lk_203 = link_20_3_input.strip()
                    comentarios_203 = d20_3.get("comentarios", [])

                    save_resp_isaude(
                        qid="20.3",
                        valor=val_str_203,
                        pontos=pts_20_3,
                        link=val_lk_203,
                        comentarios=comentarios_203
                    )

                    # Modal de aviso para links novos/alterados
                    links_atuais_203 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_20_3_input or "")]
                    links_antigos_203 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_203 or "")]

                    if (val_str_203 != v_salvo_203 or val_lk_203 != l_salvo_203) and links_atuais_203 and links_atuais_203 != links_antigos_203:
                        st.session_state[f"links_pendentes_20_3_{ano_sel}"] = links_atuais_203
                        st.session_state[f"gatilho_modal_20_3_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 20.3 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                if pts_20_3 < 0:
                    st.markdown(
                        f"<span style='color:#dc3545; font-weight:bold;'>"
                        f"📊 Pontuação Aplicada no Quesito 20.3: {pts_20_3:.1f} pontos (Penalidade)</span>",
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        f"<span style='color:#6c757d; font-weight:bold;'>"
                        f"📊 Pontuação Aplicada no Quesito 20.3: +{pts_20_3:.1f} pontos</span>",
                        unsafe_allow_html=True,
                    )

        # GATILHO DO MODAL 20.3
        if st.session_state.get(f"gatilho_modal_20_3_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("20.3", st.session_state.get(f"links_pendentes_20_3_{ano_sel}", []), ano_sel)

        # =============================================================================
        # SEÇÃO 21 - ARBOVIROSES (ANÁLISE)
        # =============================================================================
        st.subheader("🦟 Seção 21 - Monitoramento de Arboviroses")

        # -----------------------------------------------------------------------------
        # QUESITO 21.0 - ANÁLISE SEMANAL DE DADOS
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_analise_arboviroses_21_0_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 21.0 • Análise Semanal de Dados ({ano_sel})", expanded=True):
                st.subheader(f"21.0 • Análise Semanal de Dados ({ano_sel})")
                st.write(
                    "**O município analisa semanalmente os dados de casos de arboviroses, "
                    "acompanhando a tendência dos casos e verificando as variações entre as semanas epidemiológicas?**"
                )
                st.caption("ℹ️ *Selecione uma opção, informe o link de evidência e clique no botão 'Salvar Quesito 21.0' para registrar os dados.*")

                d21_0 = res_data.get("21.0") or {
                    "valor": "Selecione...",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_210 = d21_0.get("valor", "Selecione...")
                l_salvo_210 = d21_0.get("link", "")

                # Dicionário de opções com os pontos explicitados nos rótulos
                opcoes_map_21_0 = {
                    "Selecione...": {"label": "Selecione...", "pts": 0.0},
                    "Sim": {
                        "label": "Sim (10.0 pts)",
                        "pts": 10.0
                    },
                    "Não": {
                        "label": "Não (0.0 pt)",
                        "pts": 0.0
                    },
                    "Não houve casos de arboviroses": {
                        "label": "Não houve casos de arboviroses (10.0 pts)",
                        "pts": 10.0
                    }
                }

                opts_21_0_chaves = list(opcoes_map_21_0.keys())
                opts_21_0_labels = [opcoes_map_21_0[k]["label"] for k in opts_21_0_chaves]

                # Localização do índice salvo (compatível com textos legados contendo pontuação)
                idx_210 = 0
                for i, k in enumerate(opts_21_0_chaves):
                    if v_salvo_210 == k or v_salvo_210.startswith(k) or v_salvo_210 == opcoes_map_21_0[k]["label"]:
                        idx_210 = i
                        break

                c210_1, c210_2 = st.columns([1, 1])

                with c210_1:
                    st.write("📋 **Selecione o status da análise de dados:**")

                    label_selecionada_210 = st.radio(
                        "Análise Semanal:",
                        options=opts_21_0_labels,
                        index=idx_210,
                        key=f"rad_21_0_{ano_sel}",
                        label_visibility="collapsed"
                    )

                    chave_selecionada_210 = opts_21_0_chaves[opts_21_0_labels.index(label_selecionada_210)]
                    pts_21_0 = opcoes_map_21_0[chave_selecionada_210]["pts"]

                with c210_2:
                    link_21_0_input = st.text_area(
                        "Link/Evidência de boletins epidemiológicos ou relatórios de monitoramento (21.0):",
                        value=l_salvo_210,
                        key=f"txt_link_21_0_arbovirose_{ano_sel}",
                        height=180
                    )

                    links_210_visuais = re.findall(REGEX_PURE_URL, link_21_0_input or "")
                    if links_210_visuais:
                        st.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_210_visuais]
                            )
                        )

                # Feedback visual de regra
                if chave_selecionada_210 in ["Sim", "Não houve casos de arboviroses"]:
                    st.success("✅ Meta Atingida: Monitoramento epidemiológico semanal realizado adequadamente.")
                elif chave_selecionada_210 == "Não":
                    st.warning("⚠️ Atenção: O município não realiza a análise semanal dos dados de arboviroses.")

                # Chat de comentários
                bloco_comentarios_isaude("21.0", res_data)

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 21.0", key=f"btn_salvar_21_0_arbovirose_{ano_sel}", type="primary"):
                    val_str_210 = chave_selecionada_210
                    val_lk_210 = link_21_0_input.strip()
                    comentarios_210 = d21_0.get("comentarios", [])

                    save_resp_isaude(
                        qid="21.0",
                        valor=val_str_210,
                        pontos=pts_21_0,
                        link=val_lk_210,
                        comentarios=comentarios_210
                    )

                    # Modal de aviso para links novos/alterados
                    links_atuais_210 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_21_0_input or "")]
                    links_antigos_210 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_210 or "")]

                    if (val_str_210 != v_salvo_210 or val_lk_210 != l_salvo_210) and links_atuais_210 and links_atuais_210 != links_antigos_210:
                        st.session_state[f"links_pendentes_21_0_{ano_sel}"] = links_atuais_210
                        st.session_state[f"gatilho_modal_21_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 21.0 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                if pts_21_0 > 0:
                    st.markdown(
                        f"<span style='color:#28a745; font-weight:bold;'>"
                        f"📊 Pontuação Aplicada no Quesito 21.0: +{pts_21_0:.1f} pontos (Meta Atingida)</span>",
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        f"<span style='color:#6c757d; font-weight:bold;'>"
                        f"📊 Pontuação Aplicada no Quesito 21.0: +{pts_21_0:.1f} pontos</span>",
                        unsafe_allow_html=True,
                    )

        # GATILHO DO MODAL 21.0
        if st.session_state.get(f"gatilho_modal_21_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("21.0", st.session_state.get(f"links_pendentes_21_0_{ano_sel}", []), ano_sel)


        # =============================================================================
        # SEÇÃO 22 - ARBOVIROSES (INVESTIGAÇÃO)
        # =============================================================================
        st.subheader("🔍 Seção 22 - Investigação de Arboviroses")

        # -----------------------------------------------------------------------------
        # QUESITO 22.0 - INVESTIGAÇÃO DE CASOS, SURTOS E ÓBITOS
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_investigacao_arboviroses_22_0_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 22.0 • Investigação de Casos, Surtos e Óbitos ({ano_sel})", expanded=True):
                st.subheader(f"22.0 • Investigação de Casos, Surtos e Óbitos ({ano_sel})")
                st.write(
                    "**O município investiga casos notificados, surtos e óbitos de arboviroses?**"
                )
                st.caption("ℹ️ *Selecione uma opção, informe o link de evidência e clique no botão 'Salvar Quesito 22.0' para registrar os dados.*")

                d22_0 = res_data.get("22.0") or {
                    "valor": "Selecione...",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_220 = d22_0.get("valor", "Selecione...")
                l_salvo_220 = d22_0.get("link", "")

                # Dicionário de opções com os pontos explicitados nos rótulos
                opcoes_map_22_0 = {
                    "Selecione...": {"label": "Selecione...", "pts": 0.0},
                    "Sim, investiga todos os casos": {
                        "label": "Sim, investiga todos os casos (30.0 pts)",
                        "pts": 30.0
                    },
                    "Sim, investiga parte dos casos": {
                        "label": "Sim, investiga parte dos casos (15.0 pts)",
                        "pts": 15.0
                    },
                    f"Não houve casos em {ano_sel}": {
                        "label": f"Não houve casos em {ano_sel} (30.0 pts)",
                        "pts": 30.0
                    },
                    "Não investiga": {
                        "label": "Não investiga (0.0 pt)",
                        "pts": 0.0
                    }
                }

                opts_22_0_chaves = list(opcoes_map_22_0.keys())
                opts_22_0_labels = [opcoes_map_22_0[k]["label"] for k in opts_22_0_chaves]

                # Localização do índice salvo (compatível com textos legados)
                idx_220 = 0
                for i, k in enumerate(opts_22_0_chaves):
                    if v_salvo_220 == k or v_salvo_220.startswith(k.split(" em ")[0]) or v_salvo_220 == opcoes_map_22_0[k]["label"]:
                        idx_220 = i
                        break

                c220_1, c220_2 = st.columns([1, 1])

                with c220_1:
                    st.write("📋 **Selecione o nível de investigação:**")

                    label_selecionada_220 = st.radio(
                        "Investigação de Casos:",
                        options=opts_22_0_labels,
                        index=idx_220,
                        key=f"rad_22_0_{ano_sel}",
                        label_visibility="collapsed"
                    )

                    chave_selecionada_220 = opts_22_0_chaves[opts_22_0_labels.index(label_selecionada_220)]
                    pts_22_0 = opcoes_map_22_0[chave_selecionada_220]["pts"]

                with c220_2:
                    link_22_0_input = st.text_area(
                        "Link/Evidência de fichas de investigação no SINAN, relatórios de surto ou comitê de óbito (22.0):",
                        value=l_salvo_220,
                        key=f"txt_link_22_0_investigacao_{ano_sel}",
                        height=180
                    )

                    links_220_visuais = re.findall(REGEX_PURE_URL, link_22_0_input or "")
                    if links_220_visuais:
                        st.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_220_visuais]
                            )
                        )

                # Feedback visual de regra
                if chave_selecionada_220 in ["Sim, investiga todos os casos", f"Não houve casos em {ano_sel}"]:
                    st.success("✅ Meta Atingida: Cobertura total de investigação de casos/óbitos.")
                elif chave_selecionada_220 == "Sim, investiga parte dos casos":
                    st.warning("⚠️ Meta Parcial: Nem todos os casos notificados passam por investigação epidemiológica.")
                elif chave_selecionada_220 == "Não investiga":
                    st.error("❌ Em não conformidade: O município não investiga os casos notificados de arboviroses.")

                # Chat de comentários
                bloco_comentarios_isaude("22.0", res_data)

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 22.0", key=f"btn_salvar_22_0_investigacao_{ano_sel}", type="primary"):
                    val_str_220 = chave_selecionada_220
                    val_lk_220 = link_22_0_input.strip()
                    comentarios_220 = d22_0.get("comentarios", [])

                    save_resp_isaude(
                        qid="22.0",
                        valor=val_str_220,
                        pontos=pts_22_0,
                        link=val_lk_220,
                        comentarios=comentarios_220
                    )

                    # Modal de aviso para links novos/alterados
                    links_atuais_220 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_22_0_input or "")]
                    links_antigos_220 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_220 or "")]

                    if (val_str_220 != v_salvo_220 or val_lk_220 != l_salvo_220) and links_atuais_220 and links_atuais_220 != links_antigos_220:
                        st.session_state[f"links_pendentes_22_0_{ano_sel}"] = links_atuais_220
                        st.session_state[f"gatilho_modal_22_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 22.0 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                if pts_22_0 > 0:
                    st.markdown(
                        f"<span style='color:#28a745; font-weight:bold;'>"
                        f"📊 Pontuação Aplicada no Quesito 22.0: +{pts_22_0:.1f} pontos</span>",
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        f"<span style='color:#6c757d; font-weight:bold;'>"
                        f"📊 Pontuação Aplicada no Quesito 22.0: +{pts_22_0:.1f} pontos</span>",
                        unsafe_allow_html=True,
                    )

        # GATILHO DO MODAL 22.0
        if st.session_state.get(f"gatilho_modal_22_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("22.0", st.session_state.get(f"links_pendentes_22_0_{ano_sel}", []), ano_sel)

        # =============================================================================
        # SEÇÃO 23 - VIGILÂNCIA ENTOMOLÓGICA
        # =============================================================================
        st.subheader("🗺️ Seção 23 - Vigilância Entomológica e Controle Vetorial")

        # -----------------------------------------------------------------------------
        # QUESITO 23.0 - EXERCÍCIO DE ATRIBUIÇÕES
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_vigilancia_entomologica_23_0_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 23.0 • Atribuições Relacionadas ({ano_sel})", expanded=True):
                st.subheader(f"23.0 • Atribuições Relacionadas à Vigilância Entomológica ({ano_sel})")
                st.write(
                    f"**O município exerceu as atribuições relacionadas a vigilância entomológica e controle vetorial em {ano_sel}?**"
                )
                st.caption("ℹ️ *Selecione uma opção, informe o link de evidência e clique no botão 'Salvar Quesito 23.0' para registrar os dados.*")

                d23_0 = res_data.get("23.0") or {
                    "valor": "Selecione...",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_230 = d23_0.get("valor", "Selecione...")
                l_salvo_230 = d23_0.get("link", "")

                opcoes_map_23_0 = {
                    "Selecione...": {"label": "Selecione...", "pts": 0.0},
                    "Sim": {"label": "Sim (0.0 pt - Informativo)", "pts": 0.0},
                    "Não": {"label": "Não (0.0 pt - Informativo)", "pts": 0.0}
                }

                opts_23_0_chaves = list(opcoes_map_23_0.keys())
                opts_23_0_labels = [opcoes_map_23_0[k]["label"] for k in opts_23_0_chaves]

                idx_230 = 0
                for i, k in enumerate(opts_23_0_chaves):
                    if v_salvo_230 == k or v_salvo_230 == opcoes_map_23_0[k]["label"]:
                        idx_230 = i
                        break

                c230_1, c230_2 = st.columns([1, 1])

                with c230_1:
                    st.write("📋 **Selecione o exercício de atribuições:**")

                    label_selecionada_230 = st.radio(
                        "Exercício de atribuições:",
                        options=opts_23_0_labels,
                        index=idx_230,
                        key=f"rad_23_0_{ano_sel}",
                        label_visibility="collapsed"
                    )

                    chave_selecionada_230 = opts_23_0_chaves[opts_23_0_labels.index(label_selecionada_230)]
                    pts_23_0 = opcoes_map_23_0[chave_selecionada_230]["pts"]

                with c230_2:
                    link_23_0_input = st.text_area(
                        "Link/Evidência de relatórios ou documentos comprobatórios (23.0):",
                        value=l_salvo_230,
                        key=f"txt_link_23_0_vigilancia_{ano_sel}",
                        height=180
                    )

                    placeholder_links_230 = st.empty()
                    links_230_visuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_23_0_input or "")]
                    if links_230_visuais:
                        placeholder_links_230.markdown(
                            "**🔗 Links ativos:** "
                            + " | ".join([f"[{u}]({u})" for u in links_230_visuais])
                        )

                # Feedback visual de regra
                if chave_selecionada_230 == "Sim":
                    st.success("✅ Atribuições exercidas no município em vigilância entomológica.")
                elif chave_selecionada_230 == "Não":
                    st.warning("⚠️ Atribuições de vigilância entomológica não exercidas no município.")

                # Chat de comentários
                bloco_comentarios_isaude("23.0", res_data)

                # Impacto de pontuação
                st.markdown(
                    f"<span style='color:#6c757d; font-weight:bold;'>"
                    f"📊 Pontuação Aplicada no Quesito 23.0: +{pts_23_0:.1f} pontos (Dado Informativo)</span>",
                    unsafe_allow_html=True,
                )

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 23.0", key=f"btn_salvar_23_0_vigilancia_{ano_sel}", type="primary"):
                    val_str_230 = chave_selecionada_230
                    val_lk_230 = link_23_0_input.strip()
                    comentarios_230 = d23_0.get("comentarios", [])

                    save_resp_isaude(
                        qid="23.0",
                        valor=val_str_230,
                        pontos=pts_23_0,
                        link=val_lk_230,
                        comentarios=comentarios_230
                    )

                    # Modal de aviso para links novos/alterados
                    links_atuais_230 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_23_0_input or "")]
                    links_antigos_230 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_230 or "")]

                    if (val_str_230 != v_salvo_230 or val_lk_230 != l_salvo_230) and links_atuais_230 and links_atuais_230 != links_antigos_230:
                        st.session_state[f"links_pendentes_23_0_{ano_sel}"] = links_atuais_230
                        st.session_state[f"gatilho_modal_23_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 23.0 salvos com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 23.0
        if st.session_state.get(f"gatilho_modal_23_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("23.0", st.session_state.get(f"links_pendentes_23_0_{ano_sel}", []), ano_sel)

        # -----------------------------------------------------------------------------
        # QUESITO 23.1 - LISTA DE ATRIBUIÇÕES CUMULATIVAS
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_atribuicoes_vetorial_23_1_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 23.1 • Atribuições da Vigilância Entomológica ({ano_sel})", expanded=True):
                st.subheader(f"23.1 • Atribuições da Vigilância Entomológica ({ano_sel})")
                st.write(
                    "**Assinale as atribuições da vigilância entomológica e controle vetorial:**"
                )
                st.caption("ℹ️ *Selecione os itens correspondentes, informe o link de evidência e clique no botão 'Salvar Quesito 23.1' para registrar os dados.*")

                d23_1 = res_data.get("23.1") or {
                    "valor": "",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_231 = d23_1.get("valor", "").split("|") if d23_1.get("valor") else []
                l_salvo_231 = d23_1.get("link", "")

                atribuicoes_specs = {
                    "vig_sanitaria": {"text": "Incluir a vigilância sanitária municipal e como suporte às ações de vigilância e controle vetorial, que exigem o cumprimento da legislação sanitária (3.0 pts)", "pts": 3.0},
                    "integrar_equipes": {"text": "Integrar as equipes de saúde da família nas atividades de controle vetorial, unificando os territórios de atuação de ACS e ACE (3.0 pts)", "pts": 3.0},
                    "levantamento_ind": {"text": "Realizar o levantamento de indicadores entomológicos (3.0 pts)", "pts": 3.0},
                    "acoes_controle": {"text": "Executar as ações de controle mecânico, químico e biológico do mosquito (3.0 pts)", "pts": 3.0},
                    "enviar_dados": {"text": "Enviar os dados entomológicos ao nível estadual, dentro dos prazos estabelecidos (3.0 pts)", "pts": 3.0},
                    "gerenciar_estoques": {"text": "Gerenciar os estoques municipais de inseticidas e biolarvicidas (3.0 pts)", "pts": 3.0},
                    "adquirir_vestuarios": {"text": "Adquirir as vestimentas e equipamentos necessários à rotina de controle vetorial (3.0 pts)", "pts": 3.0},
                    "adquirir_epi": {"text": "Adquirir os equipamentos de EPI recomendados para a aplicação de inseticidas e biolarvicidas nas ações de rotina (3.0 pts)", "pts": 3.0},
                    "dosagem_colinesterase": {"text": "Coletar e enviar ao laboratório de referência amostras de sangue aos trabalhadores do controle vetorial que manuseiam inseticidas e/ou larvicidas, para dosagem de colinesterase, na frequência recomendada (3.0 pts)", "pts": 3.0},
                    "comite_gestor": {"text": "Possuir Comitê Gestor Intersetorial, sob coordenação da secretaria municipal de saúde, com representantes das áreas do município que tenham interface com o problema dengue (defesa civil, limpeza urbana, infraestrutura, segurança, turismo, planejamento, saneamento etc.), definindo responsabilidades, metas e indicadores de acompanhamento de cada área de atuação (3.0 pts)", "pts": 3.0},
                    "outros": {"text": "Outros (0.0 pt)", "pts": 0.0}
                }

                keys_atrib = list(atribuicoes_specs.keys())
                metade = (len(keys_atrib) + 1) // 2

                c231_1, c231_2 = st.columns([1, 1])
                chks_selecionados = []
                pts_totais_23_1 = 0.0

                with c231_1:
                    st.write("📋 **Ações e Atribuições (Parte 1):**")
                    for k in keys_atrib[:metade]:
                        marcado = st.checkbox(atribuicoes_specs[k]["text"], value=k in v_salvo_231, key=f"chk_23_1_{k}_{ano_sel}")
                        if marcado:
                            chks_selecionados.append(k)
                            pts_totais_23_1 += atribuicoes_specs[k]["pts"]

                with c231_2:
                    st.write("📋 **Ações e Atribuições (Parte 2):**")
                    for k in keys_atrib[metade:]:
                        marcado = st.checkbox(atribuicoes_specs[k]["text"], value=k in v_salvo_231, key=f"chk_23_1_{k}_{ano_sel}")
                        if marcado:
                            chks_selecionados.append(k)
                            pts_totais_23_1 += atribuicoes_specs[k]["pts"]

                link_23_1_input = st.text_area(
                    "Link/Evidência de relatórios, atas do comitê, comprovantes de EPIs ou dados de vigilância (23.1):",
                    value=l_salvo_231,
                    key=f"txt_link_23_1_atribuicoes_{ano_sel}",
                    height=120
                )

                placeholder_links_231 = st.empty()
                links_231_visuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_23_1_input or "")]
                if links_231_visuais:
                    placeholder_links_231.markdown(
                        "**🔗 Links ativos:** "
                        + " | ".join([f"[{u}]({u})" for u in links_231_visuais])
                    )

                # Feedback visual
                if len(chks_selecionados) > 0:
                    st.success(f"✅ {len(chks_selecionados)} atribuição(ões) selecionada(s).")
                else:
                    st.warning("⚠️ Nenhuma atribuição selecionada.")

                # Chat de comentários
                bloco_comentarios_isaude("23.1", res_data)

                # Impacto de pontuação
                if pts_totais_23_1 > 0:
                    st.markdown(
                        f"<span style='color:#28a745; font-weight:bold;'>"
                        f"📊 Pontuação Aplicada no Quesito 23.1: +{pts_totais_23_1:.1f} pontos</span>",
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        f"<span style='color:#6c757d; font-weight:bold;'>"
                        f"📊 Pontuação Aplicada no Quesito 23.1: +{pts_totais_23_1:.1f} pontos</span>",
                        unsafe_allow_html=True,
                    )

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 23.1", key=f"btn_salvar_23_1_atribuicoes_{ano_sel}", type="primary"):
                    val_str_231 = "|".join(chks_selecionados)
                    val_lk_231 = link_23_1_input.strip()
                    comentarios_231 = d23_1.get("comentarios", [])

                    save_resp_isaude(
                        qid="23.1",
                        valor=val_str_231,
                        pontos=pts_totais_23_1,
                        link=val_lk_231,
                        comentarios=comentarios_231
                    )

                    # Modal de aviso para links novos/alterados
                    links_atuais_231 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_23_1_input or "")]
                    links_antigos_231 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_231 or "")]

                    if (val_str_231 != "|".join(v_salvo_231) or val_lk_231 != l_salvo_231) and links_atuais_231 and links_atuais_231 != links_antigos_231:
                        st.session_state[f"links_pendentes_23_1_{ano_sel}"] = links_atuais_231
                        st.session_state[f"gatilho_modal_23_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 23.1 salvos com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 23.1
        if st.session_state.get(f"gatilho_modal_23_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("23.1", st.session_state.get(f"links_pendentes_23_1_{ano_sel}", []), ano_sel)
                            
        
        # =============================================================================
        # SEÇÃO 24 - EDUCAÇÃO EM SAÚDE
        # =============================================================================
        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        st.subheader("📢 Seção 24 - Educação em Saúde")

        # -----------------------------------------------------------------------------
        # QUESITO 24.0 - EXECUÇÃO DE ATIVIDADES
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_educacao_saude_24_0_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 24.0 • Atividades de Educação em Saúde ({ano_sel})", expanded=True):
                st.subheader(f"24.0 • Atividades de Educação em Saúde ({ano_sel})")
                st.write("**O município executou atividades de Educação em Saúde?**")
                st.caption("ℹ️ *Selecione a opção correspondente, informe o link de evidência e clique no botão 'Salvar Quesito 24.0' para registrar os dados.*")

                d24_0 = res_data.get("24.0") or {
                    "valor": "Selecione...",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_240 = d24_0.get("valor", "Selecione...")
                l_salvo_240 = d24_0.get("link", "")

                opts_24_0 = ["Selecione...", "Sim", "Não"]
                idx_24_0 = opts_24_0.index(v_salvo_240) if v_salvo_240 in opts_24_0 else 0

                c240_1, c240_2 = st.columns([1, 1])
                with c240_1:
                    sel_24_0 = st.radio(
                        "Execução de atividades:",
                        options=opts_24_0,
                        index=idx_24_0,
                        key=f"rad_24_0_{ano_sel}"
                    )
                    pts_24_0 = 0.0

                with c240_2:
                    link_24_0_input = st.text_area(
                        "Link/Evidência de atividades de educação em saúde (24.0):",
                        value=l_salvo_240,
                        key=f"txt_link_24_0_educacao_{ano_sel}",
                        height=120
                    )

                placeholder_links_240 = st.empty()
                links_240_visuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_24_0_input or "")]
                if links_240_visuais:
                    placeholder_links_240.markdown(
                        "**🔗 Links ativos:** "
                        + " | ".join([f"[{u}]({u})" for u in links_240_visuais])
                    )

                # Feedback visual
                if sel_24_0 != "Selecione...":
                    st.success(f"✅ Opção selecionada: **{sel_24_0}**")
                else:
                    st.warning("⚠️ Nenhuma opção selecionada.")

                # Chat de comentários
                bloco_comentarios_isaude("24.0", res_data)

                # Impacto de pontuação
                if sel_24_0 != "Selecione...":
                    st.markdown(
                        f"<span style='color:#6c757d; font-weight:bold;'>"
                        f"📊 Pontuação Aplicada no Quesito 24.0: +{pts_24_0:.1f} pontos (Dados Informativos)</span>",
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        f"<span style='color:#6c757d; font-weight:bold;'>"
                        f"📊 Pontuação Aplicada no Quesito 24.0: +{pts_24_0:.1f} pontos (Aguardando Seleção)</span>",
                        unsafe_allow_html=True,
                    )

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 24.0", key=f"btn_salvar_24_0_educacao_{ano_sel}", type="primary"):
                    val_str_240 = sel_24_0
                    val_lk_240 = link_24_0_input.strip()
                    comentarios_240 = d24_0.get("comentarios", [])

                    save_resp_isaude(
                        qid="24.0",
                        valor=val_str_240,
                        pontos=pts_24_0,
                        link=val_lk_240,
                        comentarios=comentarios_240
                    )

                    # Modal de aviso para links novos/alterados
                    links_atuais_240 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_24_0_input or "")]
                    links_antigos_240 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_240 or "")]

                    if (val_str_240 != v_salvo_240 or val_lk_240 != l_salvo_240) and links_atuais_240 and links_atuais_240 != links_antigos_240:
                        st.session_state[f"links_pendentes_24_0_{ano_sel}"] = links_atuais_240
                        st.session_state[f"gatilho_modal_24_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 24.0 salvos com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 24.0
        if st.session_state.get(f"gatilho_modal_24_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("24.0", st.session_state.get(f"links_pendentes_24_0_{ano_sel}", []), ano_sel)

        # -----------------------------------------------------------------------------
        # QUESITO 24.1 - CAMPANHAS REALIZADAS
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_campanhas_realizadas_24_1_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 24.1 • Campanhas Realizadas ({ano_sel})", expanded=True):
                st.subheader(f"24.1 • Campanhas Realizadas ({ano_sel})")
                st.write(f"**Assinale as campanhas realizadas em {ano_sel}:**")
                st.caption("ℹ️ *Selecione os itens correspondentes, informe o link de evidência e clique no botão 'Salvar Quesito 24.1' para registrar os dados.*")

                d24_1 = res_data.get("24.1") or {
                    "valor": "",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_241 = d24_1.get("valor", "").split("|") if d24_1.get("valor") else []
                l_salvo_241 = d24_1.get("link", "")

                campanhas_specs = {
                    "plan_familiar": {"text": "Planejamento familiar - concepção e contracepção (Prevenção à Gravidez) (0.5 pt)", "pts": 0.5},
                    "pre_natal": {"text": "Pré-Natal (0.5 pt)", "pts": 0.5},
                    "assist_parto": {"text": "Assistência ao parto, ao puerpério e ao neonato, incluindo aleitamento materno e doação de leite materno (0.5 pt)", "pts": 0.5},
                    "prev_ist": {"text": "Prevenção às IST - Infecção Sexualmente Transmissível (0.5 pt)", "pts": 0.5},
                    "prev_cancer": {"text": "Prevenção dos cânceres do colo do útero, de mama e da saúde do homem (0.5 pt)", "pts": 0.5},
                    "vacinacao": {"text": "Vacinação (0.5 pt)", "pts": 0.5},
                    "hipertensao": {"text": "Hipertensão (0.5 pt)", "pts": 0.5},
                    "diabetes": {"text": "Diabetes (0.5 pt)", "pts": 0.5},
                    "hanseniase": {"text": "Hanseníase (0.5 pt)", "pts": 0.5},
                    "hepatite": {"text": "Hepatite (0.5 pt)", "pts": 0.5},
                    "covid": {"text": "Coronavírus - COVID19 (0.5 pt)", "pts": 0.5},
                    "tuberculose": {"text": "Tuberculose (0.5 pt)", "pts": 0.5},
                    "chagas": {"text": "Doença de Chagas (0.5 pt)", "pts": 0.5},
                    "arboviroses": {"text": "Dengue/Zika/Chikungunya/Febre Amarela/Malária (Arboviroses) (0.5 pt)", "pts": 0.5},
                    "tabaco": {"text": "Tabaco (0.5 pt)", "pts": 0.5},
                    "drogas": {"text": "Drogas e entorpecentes (0.5 pt)", "pts": 0.5},
                    "saude_bucal": {"text": "Saúde Bucal (0.5 pt)", "pts": 0.5},
                    "doacao_sangue": {"text": "Doação de Sangue (0.5 pt)", "pts": 0.5},
                    "doacao_orgaos": {"text": "Doação de Órgãos (0.5 pt)", "pts": 0.5},
                    "depressao_suicidio": {"text": "Prevenção à Depressão e ao Suicídio (0.5 pt)", "pts": 0.5},
                    "hiv_aids": {"text": "HIV/Aids (0.0 pt)", "pts": 0.0},
                    "falciforme": {"text": "Doença Falciforme (0.0 pt)", "pts": 0.0},
                    "outros": {"text": "Outros (0.0 pt)", "pts": 0.0}
                }

                keys_campanhas = list(campanhas_specs.keys())
                metade = (len(keys_campanhas) + 1) // 2

                c241_1, c241_2 = st.columns([1, 1])
                chks_selecionados = []
                pts_totais_24_1 = 0.0

                with c241_1:
                    st.write("📋 **Campanhas Realizadas (Parte 1):**")
                    for k in keys_campanhas[:metade]:
                        marcado = st.checkbox(campanhas_specs[k]["text"], value=k in v_salvo_241, key=f"chk_24_1_{k}_{ano_sel}")
                        if marcado:
                            chks_selecionados.append(k)
                            pts_totais_24_1 += campanhas_specs[k]["pts"]

                with c241_2:
                    st.write("📋 **Campanhas Realizadas (Parte 2):**")
                    for k in keys_campanhas[metade:]:
                        marcado = st.checkbox(campanhas_specs[k]["text"], value=k in v_salvo_241, key=f"chk_24_1_{k}_{ano_sel}")
                        if marcado:
                            chks_selecionados.append(k)
                            pts_totais_24_1 += campanhas_specs[k]["pts"]

                link_24_1_input = st.text_area(
                    "Link/Evidência de fotos, relatórios ou divulgações das campanhas (24.1):",
                    value=l_salvo_241,
                    key=f"txt_link_24_1_campanhas_{ano_sel}",
                    height=120
                )

                placeholder_links_241 = st.empty()
                links_241_visuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_24_1_input or "")]
                if links_241_visuais:
                    placeholder_links_241.markdown(
                        "**🔗 Links ativos:** "
                        + " | ".join([f"[{u}]({u})" for u in links_241_visuais])
                    )

                # Feedback visual
                if len(chks_selecionados) > 0:
                    st.success(f"✅ {len(chks_selecionados)} campanha(s) selecionada(s).")
                else:
                    st.warning("⚠️ Nenhuma campanha selecionada.")

                # Chat de comentários
                bloco_comentarios_isaude("24.1", res_data)

                # Impacto de pontuação
                if pts_totais_24_1 > 0:
                    st.markdown(
                        f"<span style='color:#28a745; font-weight:bold;'>"
                        f"📊 Pontuação Aplicada no Quesito 24.1: +{pts_totais_24_1:.1f} pontos</span>",
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        f"<span style='color:#6c757d; font-weight:bold;'>"
                        f"📊 Pontuação Aplicada no Quesito 24.1: +{pts_totais_24_1:.1f} pontos</span>",
                        unsafe_allow_html=True,
                    )

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 24.1", key=f"btn_salvar_24_1_campanhas_{ano_sel}", type="primary"):
                    val_str_241 = "|".join(chks_selecionados)
                    val_lk_241 = link_24_1_input.strip()
                    comentarios_241 = d24_1.get("comentarios", [])

                    save_resp_isaude(
                        qid="24.1",
                        valor=val_str_241,
                        pontos=pts_totais_24_1,
                        link=val_lk_241,
                        comentarios=comentarios_241
                    )

                    # Modal de aviso para links novos/alterados
                    links_atuais_241 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_24_1_input or "")]
                    links_antigos_241 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_241 or "")]

                    if (val_str_241 != "|".join(v_salvo_241) or val_lk_241 != l_salvo_241) and links_atuais_241 and links_atuais_241 != links_antigos_241:
                        st.session_state[f"links_pendentes_24_1_{ano_sel}"] = links_atuais_241
                        st.session_state[f"gatilho_modal_24_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 24.1 salvos com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 24.1
        if st.session_state.get(f"gatilho_modal_24_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("24.1", st.session_state.get(f"links_pendentes_24_1_{ano_sel}", []), ano_sel)

        # =============================================================================
        # SEÇÃO 25 - AÇÕES REGULADORAS E COMPLEXOS REGULADORES
        # =============================================================================
        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        st.subheader("⚙️ Seção 25 - Regulação do Acesso e Complexos Reguladores")

        # -----------------------------------------------------------------------------
        # QUESITO 25.0 - AÇÕES REGULADORAS NO TERRITÓRIO
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_regulacao_acesso_25_0_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 25.0 • Ações Reguladoras no Território ({ano_sel})", expanded=True):
                st.subheader(f"25.0 • Ações Reguladoras no Território ({ano_sel})")
                st.write("**O município desenvolve ações reguladoras em seu território, operacionalizando por meio de complexo regulador municipal e/ou participando em co-gestão da operacionalização dos Complexos Reguladores Regionais?**")
                st.caption("ℹ️ *Selecione a opção correspondente, informe o link de evidência e clique no botão 'Salvar Quesito 25.0' para registrar os dados.*")

                d25_0 = res_data.get("25.0") or {
                    "valor": "Selecione...",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_250 = d25_0.get("valor", "Selecione...")
                l_salvo_250 = d25_0.get("link", "")

                opts_25_0 = ["Selecione...", "Sim – 05", "Não – 00"]
                idx_25_0 = opts_25_0.index(v_salvo_250) if v_salvo_250 in opts_25_0 else 0

                c250_1, c250_2 = st.columns([1, 1])
                with c250_1:
                    sel_25_0 = st.radio(
                        "Ações reguladoras:",
                        options=opts_25_0,
                        index=idx_25_0,
                        key=f"rad_25_0_{ano_sel}"
                    )
                    
                    opcoes_pts_250 = {
                        "Sim – 05": 5.0,
                        "Não – 00": 0.0,
                        "Selecione...": 0.0
                    }
                    pts_25_0 = opcoes_pts_250.get(sel_25_0, 0.0)

                with c250_2:
                    link_25_0_input = st.text_area(
                        "Link/Evidência de atos normativos, atas ou fluxos regulatórios (25.0):",
                        value=l_salvo_250,
                        key=f"txt_link_25_0_regulacao_{ano_sel}",
                        height=120
                    )

                placeholder_links_250 = st.empty()
                links_250_visuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_25_0_input or "")]
                if links_250_visuais:
                    placeholder_links_250.markdown(
                        "**🔗 Links ativos:** "
                        + " | ".join([f"[{u}]({u})" for u in links_250_visuais])
                    )

                # Feedback visual
                if sel_25_0 != "Selecione...":
                    st.success(f"✅ Opção selecionada: **{sel_25_0}**")
                else:
                    st.warning("⚠️ Nenhuma opção selecionada.")

                # Chat de comentários
                bloco_comentarios_isaude("25.0", res_data)

                # Impacto de pontuação
                if pts_25_0 > 0:
                    st.markdown(
                        f"<span style='color:#28a745; font-weight:bold;'>"
                        f"📊 Pontuação Aplicada no Quesito 25.0: +{pts_25_0:.1f} pontos</span>",
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        f"<span style='color:#6c757d; font-weight:bold;'>"
                        f"📊 Pontuação Aplicada no Quesito 25.0: +{pts_25_0:.1f} pontos</span>",
                        unsafe_allow_html=True,
                    )

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 25.0", key=f"btn_salvar_25_0_regulacao_{ano_sel}", type="primary"):
                    val_str_250 = sel_25_0
                    val_lk_250 = link_25_0_input.strip()
                    comentarios_250 = d25_0.get("comentarios", [])

                    save_resp_isaude(
                        qid="25.0",
                        valor=val_str_250,
                        pontos=pts_25_0,
                        link=val_lk_250,
                        comentarios=comentarios_250
                    )

                    # Modal de aviso para links novos/alterados
                    links_atuais_250 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_25_0_input or "")]
                    links_antigos_250 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_250 or "")]

                    if (val_str_250 != v_salvo_250 or val_lk_250 != l_salvo_250) and links_atuais_250 and links_atuais_250 != links_antigos_250:
                        st.session_state[f"links_pendentes_25_0_{ano_sel}"] = links_atuais_250
                        st.session_state[f"gatilho_modal_25_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 25.0 salvos com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 25.0
        if st.session_state.get(f"gatilho_modal_25_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("25.0", st.session_state.get(f"links_pendentes_25_0_{ano_sel}", []), ano_sel)

        st.markdown('</div>', unsafe_allow_html=True)  # Fecha o card geral da Seção 25

        # =============================================================================
        # SEÇÃO 26 - PROTOCOLOS DE REGULAÇÃO
        # =============================================================================
        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        st.subheader("📋 Seção 26 - Protocolos de Regulação")

        # -----------------------------------------------------------------------------
        # QUESITO 26.0 - PROTOCOLOS DE REGULAÇÃO DE ACESSO FORMALIZADOS
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_protocolos_regulacao_26_0_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 26.0 • Protocolos de Regulação de Acesso Formalizados ({ano_sel})", expanded=True):
                st.subheader(f"26.0 • Protocolos de Regulação de Acesso Formalizados ({ano_sel})")
                st.write("**O município elaborou os protocolos de regulação de acesso formalizados?**")
                st.caption("ℹ️ *Selecione a opção correspondente, informe o link de evidência e clique no botão 'Salvar Quesito 26.0' para registrar os dados.*")

                d26_0 = res_data.get("26.0") or {
                    "valor": "Selecione...",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_260 = d26_0.get("valor", "Selecione...")
                l_salvo_260 = d26_0.get("link", "")

                opts_26_0 = ["Selecione...", "Sim – 10", "Não – 00"]
                idx_26_0 = opts_26_0.index(v_salvo_260) if v_salvo_260 in opts_26_0 else 0

                c260_1, c260_2 = st.columns([1, 1])
                with c260_1:
                    sel_26_0 = st.radio(
                        "Protocolos de regulação:",
                        options=opts_26_0,
                        index=idx_26_0,
                        key=f"rad_26_0_{ano_sel}"
                    )
                    
                    opcoes_pts_260 = {
                        "Sim – 10": 10.0,
                        "Não – 00": 0.0,
                        "Selecione...": 0.0
                    }
                    pts_26_0 = opcoes_pts_260.get(sel_26_0, 0.0)

                with c260_2:
                    link_26_0_input = st.text_area(
                        "Link/Evidência dos protocolos de regulação formalizados (26.0):",
                        value=l_salvo_260,
                        key=f"txt_link_26_0_protocolos_{ano_sel}",
                        height=120
                    )

                placeholder_links_260 = st.empty()
                links_260_visuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_26_0_input or "")]
                if links_260_visuais:
                    placeholder_links_260.markdown(
                        "**🔗 Links ativos:** "
                        + " | ".join([f"[{u}]({u})" for u in links_260_visuais])
                    )

                # Feedback visual
                if sel_26_0 != "Selecione...":
                    st.success(f"✅ Opção selecionada: **{sel_26_0}**")
                else:
                    st.warning("⚠️ Nenhuma opção selecionada.")

                # Chat de comentários
                bloco_comentarios_isaude("26.0", res_data)

                # Impacto de pontuação
                if pts_26_0 > 0:
                    st.markdown(
                        f"<span style='color:#28a745; font-weight:bold;'>"
                        f"📊 Pontuação Aplicada no Quesito 26.0: +{pts_26_0:.1f} pontos</span>",
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        f"<span style='color:#6c757d; font-weight:bold;'>"
                        f"📊 Pontuação Aplicada no Quesito 26.0: +{pts_26_0:.1f} pontos</span>",
                        unsafe_allow_html=True,
                    )

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 26.0", key=f"btn_salvar_26_0_protocolos_{ano_sel}", type="primary"):
                    val_str_260 = sel_26_0
                    val_lk_260 = link_26_0_input.strip()
                    comentarios_260 = d26_0.get("comentarios", [])

                    save_resp_isaude(
                        qid="26.0",
                        valor=val_str_260,
                        pontos=pts_26_0,
                        link=val_lk_260,
                        comentarios=comentarios_260
                    )

                    # Modal de aviso para links novos/alterados
                    links_atuais_260 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_26_0_input or "")]
                    links_antigos_260 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_260 or "")]

                    if (val_str_260 != v_salvo_260 or val_lk_260 != l_salvo_260) and links_atuais_260 and links_atuais_260 != links_antigos_260:
                        st.session_state[f"links_pendentes_26_0_{ano_sel}"] = links_atuais_260
                        st.session_state[f"gatilho_modal_26_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 26.0 salvos com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 26.0
        if st.session_state.get(f"gatilho_modal_26_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("26.0", st.session_state.get(f"links_pendentes_26_0_{ano_sel}", []), ano_sel)

        # =============================================================================
        # SEÇÃO 27 - REGULAÇÃO DA REFERÊNCIA INTERMUNICIPAL
        # =============================================================================
        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        st.subheader("🔗 Seção 27 - Regulação de Referência Intermunicipal")

        # -----------------------------------------------------------------------------
        # QUESITO 27.0 - REGULAÇÃO DA REFERÊNCIA EM OUTROS MUNICÍPIOS
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_referencia_intermunicipal_27_0_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 27.0 • Regulação da Referência em Outros Municípios ({ano_sel})", expanded=True):
                st.subheader(f"27.0 • Regulação da Referência em Outros Municípios ({ano_sel})")
                st.write("**O município regula a referência a ser realizada em outros municípios, de acordo com a programação pactuada e integrada, integrando-se aos fluxos regionais estabelecidos?**")
                st.caption("ℹ️ *Selecione a opção correspondente, informe o link de evidência e clique no botão 'Salvar Quesito 27.0' para registrar os dados.*")

                d27_0 = res_data.get("27.0") or {
                    "valor": "Selecione...",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_270 = d27_0.get("valor", "Selecione...")
                l_salvo_270 = d27_0.get("link", "")

                opts_27_0 = ["Selecione...", "Sim – 05", "Não – 00"]
                idx_27_0 = opts_27_0.index(v_salvo_270) if v_salvo_270 in opts_27_0 else 0

                c270_1, c270_2 = st.columns([1, 1])
                with c270_1:
                    sel_27_0 = st.radio(
                        "Regulação da referência:",
                        options=opts_27_0,
                        index=idx_27_0,
                        key=f"rad_27_0_{ano_sel}"
                    )
                    
                    opcoes_pts_270 = {
                        "Sim – 05": 5.0,
                        "Não – 00": 0.0,
                        "Selecione...": 0.0
                    }
                    pts_27_0 = opcoes_pts_270.get(sel_27_0, 0.0)

                with c270_2:
                    link_27_0_input = st.text_area(
                        "Link/Evidência dos fluxos regionais ou pactuação intermunicipal (27.0):",
                        value=l_salvo_270,
                        key=f"txt_link_27_0_referencia_{ano_sel}",
                        height=120
                    )

                placeholder_links_270 = st.empty()
                links_270_visuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_27_0_input or "")]
                if links_270_visuais:
                    placeholder_links_270.markdown(
                        "**🔗 Links ativos:** "
                        + " | ".join([f"[{u}]({u})" for u in links_270_visuais])
                    )

                # Feedback visual
                if sel_27_0 != "Selecione...":
                    st.success(f"✅ Opção selecionada: **{sel_27_0}**")
                else:
                    st.warning("⚠️ Nenhuma opção selecionada.")

                # Chat de comentários
                bloco_comentarios_isaude("27.0", res_data)

                # Impacto de pontuação
                if pts_27_0 > 0:
                    st.markdown(
                        f"<span style='color:#28a745; font-weight:bold;'>"
                        f"📊 Pontuação Aplicada no Quesito 27.0: +{pts_27_0:.1f} pontos</span>",
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        f"<span style='color:#6c757d; font-weight:bold;'>"
                        f"📊 Pontuação Aplicada no Quesito 27.0: +{pts_27_0:.1f} pontos</span>",
                        unsafe_allow_html=True,
                    )

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 27.0", key=f"btn_salvar_27_0_referencia_{ano_sel}", type="primary"):
                    val_str_270 = sel_27_0
                    val_lk_270 = link_27_0_input.strip()
                    comentarios_270 = d27_0.get("comentarios", [])

                    save_resp_isaude(
                        qid="27.0",
                        valor=val_str_270,
                        pontos=pts_27_0,
                        link=val_lk_270,
                        comentarios=comentarios_270
                    )

                    # Modal de aviso para links novos/alterados
                    links_atuais_270 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_27_0_input or "")]
                    links_antigos_270 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_270 or "")]

                    if (val_str_270 != v_salvo_270 or val_lk_270 != l_salvo_270) and links_atuais_270 and links_atuais_270 != links_antigos_270:
                        st.session_state[f"links_pendentes_27_0_{ano_sel}"] = links_atuais_270
                        st.session_state[f"gatilho_modal_27_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 27.0 salvos com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 27.0
        if st.session_state.get(f"gatilho_modal_27_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("27.0", st.session_state.get(f"links_pendentes_27_0_{ano_sel}", []), ano_sel)


        # =============================================================================
        # SEÇÃO 28 - CONTROLE DA FILA DE ESPERA (ATENÇÃO ESPECIALIZADA)
        # =============================================================================
        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        st.subheader("⏳ Seção 28 - Controle da Fila de Espera")

        # -----------------------------------------------------------------------------
        # QUESITO 28.0 - CONTROLE DA FILA (FORA DO CROSS)
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_controle_fila_28_0_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 28.0 • Controle da Fila de Espera (Atenção Especializada - {ano_sel})", expanded=True):
                st.subheader(f"28.0 • Controle da Fila de Espera (Atenção Especializada - {ano_sel})")
                st.write("**O município possui controle da fila de espera para os atendimentos da Atenção Especializada que não foram inseridos no sistema de regulação do governo estadual (Portal CROSS)?**")
                st.caption("ℹ️ *Refere-se ao Município como Unidade Solicitante.*")
                st.caption("ℹ️ *Selecione a opção correspondente, informe o link de evidência e clique no botão 'Salvar Quesito 28.0' para registrar os dados.*")

                opts_28_0 = [
                    "Selecione...",
                    "Sim, com a relação nominal de pacientes e tempo de espera para todos os serviços da Atenção Especializada com fila de espera – 05",
                    "Sim, com a relação nominal de pacientes e tempo de espera para a maior parte dos serviços da Atenção Especializada com fila de espera – 02",
                    "Sim, com a relação nominal de pacientes e tempo de espera para a menor parte dos serviços da Atenção Especializada com fila de espera – 01",
                    "Não possui controle da fila de espera – 00",
                    "Não possui fila de espera além da inserida no sistema de regulação do governo estadual (Portal CROSS) – 05"
                ]

                d28_0 = res_data.get("28.0") or {
                    "valor": "Selecione...",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_280 = d28_0.get("valor", "Selecione...")
                l_salvo_280 = d28_0.get("link", "")
                idx_28_0 = opts_28_0.index(v_salvo_280) if v_salvo_280 in opts_28_0 else 0

                c280_1, c280_2 = st.columns([1, 1])
                with c280_1:
                    sel_28_0 = st.radio(
                        "Controle da fila:",
                        options=opts_28_0,
                        index=idx_28_0,
                        key=f"rad_28_0_{ano_sel}"
                    )
                    
                    opcoes_pts_280 = {
                        "Sim, com a relação nominal de pacientes e tempo de espera para todos os serviços da Atenção Especializada com fila de espera – 05": 5.0,
                        "Sim, com a relação nominal de pacientes e tempo de espera para a maior parte dos serviços da Atenção Especializada com fila de espera – 02": 2.0,
                        "Sim, com a relação nominal de pacientes e tempo de espera para a menor parte dos serviços da Atenção Especializada com fila de espera – 01": 1.0,
                        "Não possui controle da fila de espera – 00": 0.0,
                        "Não possui fila de espera além da inserida no sistema de regulação do governo estadual (Portal CROSS) – 05": 5.0,
                        "Selecione...": 0.0
                    }
                    pts_28_0 = opcoes_pts_280.get(sel_28_0, 0.0)

                with c280_2:
                    link_28_0_input = st.text_area(
                        "Link/Evidência do controle da fila de espera (28.0):",
                        value=l_salvo_280,
                        key=f"txt_link_28_0_controle_{ano_sel}",
                        height=120
                    )

                placeholder_links_280 = st.empty()
                links_280_visuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_28_0_input or "")]
                if links_280_visuais:
                    placeholder_links_280.markdown(
                        "**🔗 Links ativos:** "
                        + " | ".join([f"[{u}]({u})" for u in links_280_visuais])
                    )

                # Feedback visual
                if sel_28_0 != "Selecione...":
                    st.success(f"✅ Opção selecionada: **{sel_28_0}**")
                else:
                    st.warning("⚠️ Nenhuma opção selecionada.")

                # Chat de comentários
                bloco_comentarios_isaude("28.0", res_data)

                # Impacto de pontuação
                if pts_28_0 > 0:
                    st.markdown(
                        f"<span style='color:#28a745; font-weight:bold;'>"
                        f"📊 Pontuação Aplicada no Quesito 28.0: +{pts_28_0:.1f} pontos</span>",
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        f"<span style='color:#6c757d; font-weight:bold;'>"
                        f"📊 Pontuação Aplicada no Quesito 28.0: +{pts_28_0:.1f} pontos</span>",
                        unsafe_allow_html=True,
                    )

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 28.0", key=f"btn_salvar_28_0_controle_{ano_sel}", type="primary"):
                    val_str_280 = sel_28_0
                    val_lk_280 = link_28_0_input.strip()
                    comentarios_280 = d28_0.get("comentarios", [])

                    save_resp_isaude(
                        qid="28.0",
                        valor=val_str_280,
                        pontos=pts_28_0,
                        link=val_lk_280,
                        comentarios=comentarios_280
                    )

                    # Modal de aviso para links novos/alterados
                    links_atuais_280 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_28_0_input or "")]
                    links_antigos_280 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_280 or "")]

                    if (val_str_280 != v_salvo_280 or val_lk_280 != l_salvo_280) and links_atuais_280 and links_atuais_280 != links_antigos_280:
                        st.session_state[f"links_pendentes_28_0_{ano_sel}"] = links_atuais_280
                        st.session_state[f"gatilho_modal_28_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 28.0 salvos com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 28.0
        if st.session_state.get(f"gatilho_modal_28_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("28.0", st.session_state.get(f"links_pendentes_28_0_{ano_sel}", []), ano_sel)


        # -----------------------------------------------------------------------------
        # QUESITO 28.1 - TIPO DE CONTROLE
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_tipo_controle_fila_28_1_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 28.1 • Tipo de Controle da Lista de Espera ({ano_sel})", expanded=True):
                st.subheader(f"28.1 • Tipo de Controle da Lista de Espera ({ano_sel})")
                st.write("**Assinale o tipo de controle da lista de espera para os atendimentos da Atenção Especializada que não foram inseridos no sistema de regulação do governo estadual:**")
                st.caption("ℹ️ *Atenção: Planilha eletrônica não é considerada sistema informatizado.*")
                st.caption("ℹ️ *Selecione a opção correspondente, informe o link de evidência e clique no botão 'Salvar Quesito 28.1' para registrar os dados.*")

                opts_28_1 = [
                    "Selecione...",
                    "Em sistema informatizado – 05",
                    "De forma manual – -05 (perde 05 pontos)"
                ]

                d28_1 = res_data.get("28.1") or {
                    "valor": "Selecione...",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_281 = d28_1.get("valor", "Selecione...")
                l_salvo_281 = d28_1.get("link", "")
                idx_28_1 = opts_28_1.index(v_salvo_281) if v_salvo_281 in opts_28_1 else 0

                c281_1, c281_2 = st.columns([1, 1])
                with c281_1:
                    sel_28_1 = st.radio(
                        "Tipo de controle:",
                        options=opts_28_1,
                        index=idx_28_1,
                        key=f"rad_28_1_{ano_sel}"
                    )
                    
                    opcoes_pts_281 = {
                        "Em sistema informatizado – 05": 5.0,
                        "De forma manual – -05 (perde 05 pontos)": -5.0,
                        "Selecione...": 0.0
                    }
                    pts_28_1 = opcoes_pts_281.get(sel_28_1, 0.0)

                with c281_2:
                    link_28_1_input = st.text_area(
                        "Link/Evidência do tipo de controle da fila (28.1):",
                        value=l_salvo_281,
                        key=f"txt_link_28_1_tipo_controle_{ano_sel}",
                        height=120
                    )

                placeholder_links_281 = st.empty()
                links_281_visuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_28_1_input or "")]
                if links_281_visuais:
                    placeholder_links_281.markdown(
                        "**🔗 Links ativos:** "
                        + " | ".join([f"[{u}]({u})" for u in links_281_visuais])
                    )

                # Feedback visual
                if sel_28_1 != "Selecione...":
                    st.success(f"✅ Opção selecionada: **{sel_28_1}**")
                else:
                    st.warning("⚠️ Nenhuma opção selecionada.")

                # Chat de comentários
                bloco_comentarios_isaude("28.1", res_data)

                # Impacto de pontuação
                if pts_28_1 > 0:
                    st.markdown(
                        f"<span style='color:#28a745; font-weight:bold;'>"
                        f"📊 Pontuação Aplicada no Quesito 28.1: +{pts_28_1:.1f} pontos</span>",
                        unsafe_allow_html=True,
                    )
                elif pts_28_1 < 0:
                    st.markdown(
                        f"<span style='color:#dc3545; font-weight:bold;'>"
                        f"⚠️ Penalidade Aplicada no Quesito 28.1: {pts_28_1:.1f} pontos</span>",
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        f"<span style='color:#6c757d; font-weight:bold;'>"
                        f"📊 Pontuação Aplicada no Quesito 28.1: +{pts_28_1:.1f} pontos</span>",
                        unsafe_allow_html=True,
                    )

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 28.1", key=f"btn_salvar_28_1_tipo_controle_{ano_sel}", type="primary"):
                    val_str_281 = sel_28_1
                    val_lk_281 = link_28_1_input.strip()
                    comentarios_281 = d28_1.get("comentarios", [])

                    save_resp_isaude(
                        qid="28.1",
                        valor=val_str_281,
                        pontos=pts_28_1,
                        link=val_lk_281,
                        comentarios=comentarios_281
                    )

                    # Modal de aviso para links novos/alterados
                    links_atuais_281 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_28_1_input or "")]
                    links_antigos_281 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_281 or "")]

                    if (val_str_281 != v_salvo_281 or val_lk_281 != l_salvo_281) and links_atuais_281 and links_atuais_281 != links_antigos_281:
                        st.session_state[f"links_pendentes_28_1_{ano_sel}"] = links_atuais_281
                        st.session_state[f"gatilho_modal_28_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 28.1 salvos com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 28.1
        if st.session_state.get(f"gatilho_modal_28_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("28.1", st.session_state.get(f"links_pendentes_28_1_{ano_sel}", []), ano_sel)

        # -----------------------------------------------------------------------------
        # QUESITO 28.2 - SERVIÇOS FORA DO PORTAL CROSS
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_servicos_fora_cross_28_2_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 28.2 • Serviços com Lista de Espera Fora do Portal CROSS ({ano_sel})", expanded=True):
                st.subheader(f"28.2 • Serviços com Lista de Espera Fora do Portal CROSS ({ano_sel})")
                st.write("**Assinale os serviços da Atenção Especializada com lista de espera que não foram inseridos no sistema de regulação do governo estadual (Portal CROSS):**")
                st.caption("ℹ️ *Selecione as opções correspondentes, informe o link de evidência e clique no botão 'Salvar Quesito 28.2' para registrar os dados.*")

                d28_2 = res_data.get("28.2") or {
                    "valor": "",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_282 = d28_2.get("valor", "").split("|") if d28_2.get("valor") else []
                l_salvo_282 = d28_2.get("link", "")

                servicos_specs = {
                    "consultas": "Consultas por especialidade",
                    "exames": "Exames",
                    "terapias": "Terapias / tratamentos",
                    "medicamentos": "Medicamentos",
                    "opm": "OPM",
                    "cirurgias": "Cirurgias eletivas",
                    "outros": "Outros"
                }

                c282_1, c282_2 = st.columns([1, 1])
                chks_28_2 = []
                keys_servicos = list(servicos_specs.keys())
                metade_servicos = (len(keys_servicos) + 1) // 2

                with c282_1:
                    for k in keys_servicos[:metade_servicos]:
                        marcado = st.checkbox(
                            servicos_specs[k],
                            value=k in v_salvo_282,
                            key=f"chk_28_2_{k}_{ano_sel}"
                        )
                        if marcado:
                            chks_28_2.append(k)

                with c282_2:
                    for k in keys_servicos[metade_servicos:]:
                        marcado = st.checkbox(
                            servicos_specs[k],
                            value=k in v_salvo_282,
                            key=f"chk_28_2_{k}_{ano_sel}"
                        )
                        if marcado:
                            chks_28_2.append(k)

                link_28_2_input = st.text_area(
                    "Link/Evidência dos serviços fora do portal CROSS (28.2):",
                    value=l_salvo_282,
                    key=f"txt_link_28_2_servicos_fora_{ano_sel}",
                    height=120
                )

                placeholder_links_282 = st.empty()
                links_282_visuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_28_2_input or "")]
                if links_282_visuais:
                    placeholder_links_282.markdown(
                        "**🔗 Links ativos:** "
                        + " | ".join([f"[{u}]({u})" for u in links_282_visuais])
                    )

                # Feedback visual
                if chks_28_2:
                    itens_txt = ", ".join([servicos_specs[k] for k in chks_28_2])
                    st.success(f"✅ Itens selecionados: **{itens_txt}**")
                else:
                    st.warning("⚠️ Nenhum serviço selecionado.")

                # Chat de comentários
                bloco_comentarios_isaude("28.2", res_data)

                # Impacto de pontuação
                pts_28_2 = 0.0
                st.markdown(
                    f"<span style='color:#6c757d; font-weight:bold;'>"
                    f"📊 Pontuação Aplicada no Quesito 28.2: +{pts_28_2:.1f} pontos (Dados Informativos)</span>",
                    unsafe_allow_html=True,
                )

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 28.2", key=f"btn_salvar_28_2_servicos_fora_{ano_sel}", type="primary"):
                    val_str_282 = "|".join(chks_28_2)
                    val_lk_282 = link_28_2_input.strip()
                    comentarios_282 = d28_2.get("comentarios", [])

                    save_resp_isaude(
                        qid="28.2",
                        valor=val_str_282,
                        pontos=pts_28_2,
                        link=val_lk_282,
                        comentarios=comentarios_282
                    )

                    # Modal de aviso para links novos/alterados
                    links_atuais_282 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_28_2_input or "")]
                    links_antigos_282 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_282 or "")]

                    if (val_str_282 != d28_2.get("valor", "") or val_lk_282 != l_salvo_282) and links_atuais_282 and links_atuais_282 != links_antigos_282:
                        st.session_state[f"links_pendentes_28_2_{ano_sel}"] = links_atuais_282
                        st.session_state[f"gatilho_modal_28_2_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 28.2 salvos com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 28.2
        if st.session_state.get(f"gatilho_modal_28_2_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("28.2", st.session_state.get(f"links_pendentes_28_2_{ano_sel}", []), ano_sel)


        # -----------------------------------------------------------------------------
        # QUESITO 28.2.1 - MAIORES TEMPOS DE ESPERA: CONSULTAS
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_maiores_esperas_consultas_28_2_1_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 28.2.1 • Top 3 Consultas Médicas com Maior Tempo de Espera ({ano_sel})", expanded=True):
                st.subheader(f"28.2.1 • Top 3 Consultas Médicas com Maior Tempo de Espera ({ano_sel})")
                st.write("**Informe as 3 consultas médicas com maior tempo de espera:**")
                st.caption("ℹ️ *Preencha as especialidades e os respectivos dias de espera, informe o link e clique no botão 'Salvar Quesito 28.2.1' para registrar os dados.*")

                d28_2_1 = res_data.get("28.2.1") or {
                    "valor": "|||||",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_2821 = d28_2_1.get("valor", "|||||").split("|")
                while len(v_salvo_2821) < 6:
                    v_salvo_2821.append("")

                l_salvo_2821 = d28_2_1.get("link", "")

                c2821_1, c2821_2 = st.columns([1, 1])
                with c2821_1:
                    esp_1 = st.text_input("1ª Especialidade médica:", value=v_salvo_2821[0], key=f"txt_2821_esp1_{ano_sel}")
                    tempo_1 = st.number_input("Tempo médio de espera 1 (em dias):", min_value=0, value=int(v_salvo_2821[1]) if v_salvo_2821[1].isdigit() else 0, key=f"num_2821_t1_{ano_sel}")

                    esp_2 = st.text_input("2ª Especialidade médica:", value=v_salvo_2821[2], key=f"txt_2821_esp2_{ano_sel}")
                    tempo_2 = st.number_input("Tempo médio de espera 2 (em dias):", min_value=0, value=int(v_salvo_2821[3]) if v_salvo_2821[3].isdigit() else 0, key=f"num_2821_t2_{ano_sel}")

                    esp_3 = st.text_input("3ª Especialidade médica:", value=v_salvo_2821[4], key=f"txt_2821_esp3_{ano_sel}")
                    tempo_3 = st.number_input("Tempo médio de espera 3 (em dias):", min_value=0, value=int(v_salvo_2821[5]) if v_salvo_2821[5].isdigit() else 0, key=f"num_2821_t3_{ano_sel}")

                with c2821_2:
                    link_28_2_1_input = st.text_area(
                        "Link/Evidência do tempo de espera das consultas (28.2.1):",
                        value=l_salvo_2821,
                        key=f"txt_link_28_2_1_maiores_esperas_{ano_sel}",
                        height=210
                    )

                placeholder_links_2821 = st.empty()
                links_2821_visuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_28_2_1_input or "")]
                if links_2821_visuais:
                    placeholder_links_2821.markdown(
                        "**🔗 Links ativos:** "
                        + " | ".join([f"[{u}]({u})" for u in links_2821_visuais])
                    )

                # Feedback visual
                preenchidos = [esp for esp in [esp_1, esp_2, esp_3] if esp.strip()]
                if preenchidos:
                    st.success(f"✅ Especialidades informadas: **{', '.join(preenchidos)}**")
                else:
                    st.warning("⚠️ Nenhuma especialidade informada.")

                # Chat de comentários
                bloco_comentarios_isaude("28.2.1", res_data)

                # Impacto de pontuação
                pts_28_2_1 = 0.0
                st.markdown(
                    f"<span style='color:#6c757d; font-weight:bold;'>"
                    f"📊 Pontuação Aplicada no Quesito 28.2.1: +{pts_28_2_1:.1f} pontos (Dados Informativos)</span>",
                    unsafe_allow_html=True,
                )

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 28.2.1", key=f"btn_salvar_28_2_1_maiores_esperas_{ano_sel}", type="primary"):
                    val_str_2821 = f"{esp_1.strip()}|{tempo_1}|{esp_2.strip()}|{tempo_2}|{esp_3.strip()}|{tempo_3}"
                    val_lk_2821 = link_28_2_1_input.strip()
                    comentarios_2821 = d28_2_1.get("comentarios", [])

                    save_resp_isaude(
                        qid="28.2.1",
                        valor=val_str_2821,
                        pontos=pts_28_2_1,
                        link=val_lk_2821,
                        comentarios=comentarios_2821
                    )

                    # Modal de aviso para links novos/alterados
                    links_atuais_2821 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_28_2_1_input or "")]
                    links_antigos_2821 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_2821 or "")]

                    if (val_str_2821 != d28_2_1.get("valor", "") or val_lk_2821 != l_salvo_2821) and links_atuais_2821 and links_atuais_2821 != links_antigos_2821:
                        st.session_state[f"links_pendentes_28_2_1_{ano_sel}"] = links_atuais_2821
                        st.session_state[f"gatilho_modal_28_2_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 28.2.1 salvos com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 28.2.1
        if st.session_state.get(f"gatilho_modal_28_2_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("28.2.1", st.session_state.get(f"links_pendentes_28_2_1_{ano_sel}", []), ano_sel)

        # -----------------------------------------------------------------------------
        # QUESITO 28.2.2 - MAIORES TEMPOS DE ESPERA: EXAMES
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_maiores_esperas_exames_28_2_2_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 28.2.2 • Top 3 Exames Médicos com Maior Tempo de Espera ({ano_sel})", expanded=True):
                st.subheader(f"28.2.2 • Top 3 Exames Médicos com Maior Tempo de Espera ({ano_sel})")
                st.write("**Informe os 3 exames médicos com maior tempo de espera:**")
                st.caption("ℹ️ *Preencha os exames e os respectivos dias de espera, informe o link e clique no botão 'Salvar Quesito 28.2.2' para registrar os dados.*")

                d28_2_2 = res_data.get("28.2.2") or {
                    "valor": "|||||",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_2822 = d28_2_2.get("valor", "|||||").split("|")
                while len(v_salvo_2822) < 6:
                    v_salvo_2822.append("")

                l_salvo_2822 = d28_2_2.get("link", "")

                c2822_1, c2822_2 = st.columns([1, 1])
                with c2822_1:
                    exm_1 = st.text_input("1º Exame médico:", value=v_salvo_2822[0], key=f"txt_2822_exm1_{ano_sel}")
                    tempo_exm1 = st.number_input("Tempo médio de espera exm 1 (em dias):", min_value=0, value=int(v_salvo_2822[1]) if v_salvo_2822[1].isdigit() else 0, key=f"num_2822_t1_{ano_sel}")

                    exm_2 = st.text_input("2º Exame médico:", value=v_salvo_2822[2], key=f"txt_2822_exm2_{ano_sel}")
                    tempo_exm2 = st.number_input("Tempo médio de espera exm 2 (em dias):", min_value=0, value=int(v_salvo_2822[3]) if v_salvo_2822[3].isdigit() else 0, key=f"num_2822_t2_{ano_sel}")

                    exm_3 = st.text_input("3º Exame médico:", value=v_salvo_2822[4], key=f"txt_2822_exm3_{ano_sel}")
                    tempo_exm3 = st.number_input("Tempo médio de espera exm 3 (em dias):", min_value=0, value=int(v_salvo_2822[5]) if v_salvo_2822[5].isdigit() else 0, key=f"num_2822_t3_{ano_sel}")

                with c2822_2:
                    link_28_2_2_input = st.text_area(
                        "Link/Evidência do tempo de espera dos exames (28.2.2):",
                        value=l_salvo_2822,
                        key=f"txt_link_28_2_2_maiores_esperas_{ano_sel}",
                        height=210
                    )

                placeholder_links_2822 = st.empty()
                links_2822_visuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_28_2_2_input or "")]
                if links_2822_visuais:
                    placeholder_links_2822.markdown(
                        "**🔗 Links ativos:** "
                        + " | ".join([f"[{u}]({u})" for u in links_2822_visuais])
                    )

                # Feedback visual
                preenchidos_2822 = [exm for exm in [exm_1, exm_2, exm_3] if exm.strip()]
                if preenchidos_2822:
                    st.success(f"✅ Exames informados: **{', '.join(preenchidos_2822)}**")
                else:
                    st.warning("⚠️ Nenhum exame informado.")

                # Chat de comentários
                bloco_comentarios_isaude("28.2.2", res_data)

                # Impacto de pontuação
                pts_28_2_2 = 0.0
                st.markdown(
                    f"<span style='color:#6c757d; font-weight:bold;'>"
                    f"📊 Pontuação Aplicada no Quesito 28.2.2: +{pts_28_2_2:.1f} pontos (Dados Informativos)</span>",
                    unsafe_allow_html=True,
                )

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 28.2.2", key=f"btn_salvar_28_2_2_maiores_esperas_{ano_sel}", type="primary"):
                    val_str_2822 = f"{exm_1.strip()}|{tempo_exm1}|{exm_2.strip()}|{tempo_exm2}|{exm_3.strip()}|{tempo_exm3}"
                    val_lk_2822 = link_28_2_2_input.strip()
                    comentarios_2822 = d28_2_2.get("comentarios", [])

                    save_resp_isaude(
                        qid="28.2.2",
                        valor=val_str_2822,
                        pontos=pts_28_2_2,
                        link=val_lk_2822,
                        comentarios=comentarios_2822
                    )

                    # Modal de aviso para links novos/alterados
                    links_atuais_2822 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_28_2_2_input or "")]
                    links_antigos_2822 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_2822 or "")]

                    if (val_str_2822 != d28_2_2.get("valor", "") or val_lk_2822 != l_salvo_2822) and links_atuais_2822 and links_atuais_2822 != links_antigos_2822:
                        st.session_state[f"links_pendentes_28_2_2_{ano_sel}"] = links_atuais_2822
                        st.session_state[f"gatilho_modal_28_2_2_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 28.2.2 salvos com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 28.2.2
        if st.session_state.get(f"gatilho_modal_28_2_2_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("28.2.2", st.session_state.get(f"links_pendentes_28_2_2_{ano_sel}", []), ano_sel)

        # -----------------------------------------------------------------------------
        # QUESITO 28.2.3 - MAIORES TEMPOS DE ESPERA: TERAPIAS
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_maiores_esperas_terapias_28_2_3_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 28.2.3 • Top 3 Terapias/Tratamentos com Maior Tempo de Espera ({ano_sel})", expanded=True):
                st.subheader(f"28.2.3 • Top 3 Terapias/Tratamentos com Maior Tempo de Espera ({ano_sel})")
                st.write("**Informe as 3 terapias ou tratamentos com maior tempo de espera:**")
                st.caption("ℹ️ *Preencha as terapias/tratamentos e os respectivos dias de espera, informe o link e clique no botão 'Salvar Quesito 28.2.3' para registrar os dados.*")

                d28_2_3 = res_data.get("28.2.3") or {
                    "valor": "|||||",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_2823 = d28_2_3.get("valor", "|||||").split("|")
                while len(v_salvo_2823) < 6:
                    v_salvo_2823.append("")

                l_salvo_2823 = d28_2_3.get("link", "")

                c2823_1, c2823_2 = st.columns([1, 1])
                with c2823_1:
                    ter_1 = st.text_input("1ª Terapia / tratamento:", value=v_salvo_2823[0], key=f"txt_2823_ter1_{ano_sel}")
                    tempo_ter1 = st.number_input("Tempo médio de espera ter 1 (em dias):", min_value=0, value=int(v_salvo_2823[1]) if v_salvo_2823[1].isdigit() else 0, key=f"num_2823_t1_{ano_sel}")

                    ter_2 = st.text_input("2ª Terapia / tratamento:", value=v_salvo_2823[2], key=f"txt_2823_ter2_{ano_sel}")
                    tempo_ter2 = st.number_input("Tempo médio de espera ter 2 (em dias):", min_value=0, value=int(v_salvo_2823[3]) if v_salvo_2823[3].isdigit() else 0, key=f"num_2823_t2_{ano_sel}")

                    ter_3 = st.text_input("3ª Terapia / tratamento:", value=v_salvo_2823[4], key=f"txt_2823_ter3_{ano_sel}")
                    tempo_ter3 = st.number_input("Tempo médio de espera ter 3 (em dias):", min_value=0, value=int(v_salvo_2823[5]) if v_salvo_2823[5].isdigit() else 0, key=f"num_2823_t3_{ano_sel}")

                with c2823_2:
                    link_28_2_3_input = st.text_area(
                        "Link/Evidência do tempo de espera das terapias (28.2.3):",
                        value=l_salvo_2823,
                        key=f"txt_link_28_2_3_maiores_esperas_{ano_sel}",
                        height=210
                    )

                placeholder_links_2823 = st.empty()
                links_2823_visuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_28_2_3_input or "")]
                if links_2823_visuais:
                    placeholder_links_2823.markdown(
                        "**🔗 Links ativos:** "
                        + " | ".join([f"[{u}]({u})" for u in links_2823_visuais])
                    )

                # Feedback visual
                preenchidos_2823 = [ter for ter in [ter_1, ter_2, ter_3] if ter.strip()]
                if preenchidos_2823:
                    st.success(f"✅ Terapias informadas: **{', '.join(preenchidos_2823)}**")
                else:
                    st.warning("⚠️ Nenhuma terapia informada.")

                # Chat de comentários
                bloco_comentarios_isaude("28.2.3", res_data)

                # Impacto de pontuação
                pts_28_2_3 = 0.0
                st.markdown(
                    f"<span style='color:#6c757d; font-weight:bold;'>"
                    f"📊 Pontuação Aplicada no Quesito 28.2.3: +{pts_28_2_3:.1f} pontos (Dados Informativos)</span>",
                    unsafe_allow_html=True,
                )

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 28.2.3", key=f"btn_salvar_28_2_3_maiores_esperas_{ano_sel}", type="primary"):
                    val_str_2823 = f"{ter_1.strip()}|{tempo_ter1}|{ter_2.strip()}|{tempo_ter2}|{ter_3.strip()}|{tempo_ter3}"
                    val_lk_2823 = link_28_2_3_input.strip()
                    comentarios_2823 = d28_2_3.get("comentarios", [])

                    save_resp_isaude(
                        qid="28.2.3",
                        valor=val_str_2823,
                        pontos=pts_28_2_3,
                        link=val_lk_2823,
                        comentarios=comentarios_2823
                    )

                    # Modal de aviso para links novos/alterados
                    links_atuais_2823 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_28_2_3_input or "")]
                    links_antigos_2823 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_2823 or "")]

                    if (val_str_2823 != d28_2_3.get("valor", "") or val_lk_2823 != l_salvo_2823) and links_atuais_2823 and links_atuais_2823 != links_antigos_2823:
                        st.session_state[f"links_pendentes_28_2_3_{ano_sel}"] = links_atuais_2823
                        st.session_state[f"gatilho_modal_28_2_3_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 28.2.3 salvos com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 28.2.3
        if st.session_state.get(f"gatilho_modal_28_2_3_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("28.2.3", st.session_state.get(f"links_pendentes_28_2_3_{ano_sel}", []), ano_sel)

# -----------------------------------------------------------------------------
        # QUESITO 28.2.4 - MAIORES TEMPOS DE ESPERA: MEDICAMENTOS
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_maiores_esperas_medicamentos_28_2_4_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 28.2.4 • Top 3 Medicamentos com Maior Tempo de Espera ({ano_sel})", expanded=True):
                st.subheader(f"28.2.4 • Top 3 Medicamentos com Maior Tempo de Espera ({ano_sel})")
                st.write("**Informe os 3 medicamentos com maior tempo de espera:**")
                st.caption("ℹ️ *Preencha os medicamentos e os respectivos dias de espera, informe o link e clique no botão 'Salvar Quesito 28.2.4' para registrar os dados.*")

                d28_2_4 = res_data.get("28.2.4") or {
                    "valor": "|||||",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_2824 = d28_2_4.get("valor", "|||||").split("|")
                while len(v_salvo_2824) < 6:
                    v_salvo_2824.append("")

                l_salvo_2824 = d28_2_4.get("link", "")

                c2824_1, c2824_2 = st.columns([1, 1])
                with c2824_1:
                    med_1 = st.text_input("1º Medicamento:", value=v_salvo_2824[0], key=f"txt_2824_med1_{ano_sel}")
                    tempo_med1 = st.number_input("Tempo médio de espera med 1 (em dias):", min_value=0, value=int(v_salvo_2824[1]) if v_salvo_2824[1].isdigit() else 0, key=f"num_2824_t1_{ano_sel}")

                    med_2 = st.text_input("2º Medicamento:", value=v_salvo_2824[2], key=f"txt_2824_med2_{ano_sel}")
                    tempo_med2 = st.number_input("Tempo médio de espera med 2 (em dias):", min_value=0, value=int(v_salvo_2824[3]) if v_salvo_2824[3].isdigit() else 0, key=f"num_2824_t2_{ano_sel}")

                    med_3 = st.text_input("3º Medicamento:", value=v_salvo_2824[4], key=f"txt_2824_med3_{ano_sel}")
                    tempo_med3 = st.number_input("Tempo médio de espera med 3 (em dias):", min_value=0, value=int(v_salvo_2824[5]) if v_salvo_2824[5].isdigit() else 0, key=f"num_2824_t3_{ano_sel}")

                with c2824_2:
                    link_28_2_4_input = st.text_area(
                        "Link/Evidência do tempo de espera dos medicamentos (28.2.4):",
                        value=l_salvo_2824,
                        key=f"txt_link_28_2_4_maiores_esperas_{ano_sel}",
                        height=210
                    )

                placeholder_links_2824 = st.empty()
                links_2824_visuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_28_2_4_input or "")]
                if links_2824_visuais:
                    placeholder_links_2824.markdown(
                        "**🔗 Links ativos:** "
                        + " | ".join([f"[{u}]({u})" for u in links_2824_visuais])
                    )

                # Feedback visual
                preenchidos_2824 = [med for med in [med_1, med_2, med_3] if med.strip()]
                if preenchidos_2824:
                    st.success(f"✅ Medicamentos informados: **{', '.join(preenchidos_2824)}**")
                else:
                    st.warning("⚠️ Nenhum medicamento informado.")

                # Chat de comentários
                bloco_comentarios_isaude("28.2.4", res_data)

                # Impacto de pontuação
                pts_28_2_4 = 0.0
                st.markdown(
                    f"<span style='color:#6c757d; font-weight:bold;'>"
                    f"📊 Pontuação Aplicada no Quesito 28.2.4: +{pts_28_2_4:.1f} pontos (Dados Informativos)</span>",
                    unsafe_allow_html=True,
                )

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 28.2.4", key=f"btn_salvar_28_2_4_maiores_esperas_{ano_sel}", type="primary"):
                    val_str_2824 = f"{med_1.strip()}|{tempo_med1}|{med_2.strip()}|{tempo_med2}|{med_3.strip()}|{tempo_med3}"
                    val_lk_2824 = link_28_2_4_input.strip()
                    comentarios_2824 = d28_2_4.get("comentarios", [])

                    save_resp_isaude(
                        qid="28.2.4",
                        valor=val_str_2824,
                        pontos=pts_28_2_4,
                        link=val_lk_2824,
                        comentarios=comentarios_2824
                    )

                    # Modal de aviso para links novos/alterados
                    links_atuais_2824 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_28_2_4_input or "")]
                    links_antigos_2824 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_2824 or "")]

                    if (val_str_2824 != d28_2_4.get("valor", "") or val_lk_2824 != l_salvo_2824) and links_atuais_2824 and links_atuais_2824 != links_antigos_2824:
                        st.session_state[f"links_pendentes_28_2_4_{ano_sel}"] = links_atuais_2824
                        st.session_state[f"gatilho_modal_28_2_4_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 28.2.4 salvos com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 28.2.4
        if st.session_state.get(f"gatilho_modal_28_2_4_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("28.2.4", st.session_state.get(f"links_pendentes_28_2_4_{ano_sel}", []), ano_sel)

        # -----------------------------------------------------------------------------
        # QUESITO 28.2.5 - MAIORES TEMPOS DE ESPERA: OPM
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_maiores_esperas_opm_28_2_5_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 28.2.5 • Top 3 OPM com Maior Tempo de Espera ({ano_sel})", expanded=True):
                st.subheader(f"28.2.5 • Top 3 OPM com Maior Tempo de Espera ({ano_sel})")
                st.write("**Informe as 3 OPM (Órteses, Próteses e Materiais Especiais) com maior tempo de espera:**")
                st.caption("ℹ️ *Preencha as OPM e os respectivos dias de espera, informe o link e clique no botão 'Salvar Quesito 28.2.5' para registrar os dados.*")

                d28_2_5 = res_data.get("28.2.5") or {
                    "valor": "|||||",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_2825 = d28_2_5.get("valor", "|||||").split("|")
                while len(v_salvo_2825) < 6:
                    v_salvo_2825.append("")

                l_salvo_2825 = d28_2_5.get("link", "")

                c2825_1, c2825_2 = st.columns([1, 1])
                with c2825_1:
                    opm_1 = st.text_input("1ª OPM:", value=v_salvo_2825[0], key=f"txt_2825_opm1_{ano_sel}")
                    tempo_opm1 = st.number_input("Tempo médio de espera opm 1 (em dias):", min_value=0, value=int(v_salvo_2825[1]) if v_salvo_2825[1].isdigit() else 0, key=f"num_2825_t1_{ano_sel}")

                    opm_2 = st.text_input("2ª OPM:", value=v_salvo_2825[2], key=f"txt_2825_opm2_{ano_sel}")
                    tempo_opm2 = st.number_input("Tempo médio de espera opm 2 (em dias):", min_value=0, value=int(v_salvo_2825[3]) if v_salvo_2825[3].isdigit() else 0, key=f"num_2825_t2_{ano_sel}")

                    opm_3 = st.text_input("3ª OPM:", value=v_salvo_2825[4], key=f"txt_2825_opm3_{ano_sel}")
                    tempo_opm3 = st.number_input("Tempo médio de espera opm 3 (em dias):", min_value=0, value=int(v_salvo_2825[5]) if v_salvo_2825[5].isdigit() else 0, key=f"num_2825_t3_{ano_sel}")

                with c2825_2:
                    link_28_2_5_input = st.text_area(
                        "Link/Evidência do tempo de espera das OPM (28.2.5):",
                        value=l_salvo_2825,
                        key=f"txt_link_28_2_5_maiores_esperas_{ano_sel}",
                        height=210
                    )

                placeholder_links_2825 = st.empty()
                links_2825_visuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_28_2_5_input or "")]
                if links_2825_visuais:
                    placeholder_links_2825.markdown(
                        "**🔗 Links ativos:** "
                        + " | ".join([f"[{u}]({u})" for u in links_2825_visuais])
                    )

                # Feedback visual
                preenchidos_2825 = [opm for opm in [opm_1, opm_2, opm_3] if opm.strip()]
                if preenchidos_2825:
                    st.success(f"✅ OPM informadas: **{', '.join(preenchidos_2825)}**")
                else:
                    st.warning("⚠️ Nenhuma OPM informada.")

                # Chat de comentários
                bloco_comentarios_isaude("28.2.5", res_data)

                # Impacto de pontuação
                pts_28_2_5 = 0.0
                st.markdown(
                    f"<span style='color:#6c757d; font-weight:bold;'>"
                    f"📊 Pontuação Aplicada no Quesito 28.2.5: +{pts_28_2_5:.1f} pontos (Dados Informativos)</span>",
                    unsafe_allow_html=True,
                )

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 28.2.5", key=f"btn_salvar_28_2_5_maiores_esperas_{ano_sel}", type="primary"):
                    val_str_2825 = f"{opm_1.strip()}|{tempo_opm1}|{opm_2.strip()}|{tempo_opm2}|{opm_3.strip()}|{tempo_opm3}"
                    val_lk_2825 = link_28_2_5_input.strip()
                    comentarios_2825 = d28_2_5.get("comentarios", [])

                    save_resp_isaude(
                        qid="28.2.5",
                        valor=val_str_2825,
                        pontos=pts_28_2_5,
                        link=val_lk_2825,
                        comentarios=comentarios_2825
                    )

                    # Modal de aviso para links novos/alterados
                    links_atuais_2825 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_28_2_5_input or "")]
                    links_antigos_2825 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_2825 or "")]

                    if (val_str_2825 != d28_2_5.get("valor", "") or val_lk_2825 != l_salvo_2825) and links_atuais_2825 and links_atuais_2825 != links_antigos_2825:
                        st.session_state[f"links_pendentes_28_2_5_{ano_sel}"] = links_atuais_2825
                        st.session_state[f"gatilho_modal_28_2_5_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 28.2.5 salvos com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 28.2.5
        if st.session_state.get(f"gatilho_modal_28_2_5_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("28.2.5", st.session_state.get(f"links_pendentes_28_2_5_{ano_sel}", []), ano_sel)

        # -----------------------------------------------------------------------------
        # QUESITO 28.2.6 - MAIORES TEMPOS DE ESPERA: CIRURGIAS ELETIVAS
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_maiores_esperas_cirurgias_28_2_6_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 28.2.6 • Top 3 Cirurgias Eletivas com Maior Tempo de Espera ({ano_sel})", expanded=True):
                st.subheader(f"28.2.6 • Top 3 Cirurgias Eletivas com Maior Tempo de Espera ({ano_sel})")
                st.write("**Informe as 3 Cirurgias eletivas da Atenção Especializada com maior tempo de espera:**")
                st.caption("ℹ️ *Preencha as cirurgias eletivas e os respectivos dias de espera, informe o link e clique no botão 'Salvar Quesito 28.2.6' para registrar os dados.*")

                d28_2_6 = res_data.get("28.2.6") or {
                    "valor": "|||||",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_2826 = d28_2_6.get("valor", "|||||").split("|")
                while len(v_salvo_2826) < 6:
                    v_salvo_2826.append("")

                l_salvo_2826 = d28_2_6.get("link", "")

                c2826_1, c2826_2 = st.columns([1, 1])
                with c2826_1:
                    cir_1 = st.text_input("1ª Cirurgia eletiva:", value=v_salvo_2826[0], key=f"txt_2826_cir1_{ano_sel}")
                    tempo_cir1 = st.number_input("Tempo médio de espera cir 1 (em dias):", min_value=0, value=int(v_salvo_2826[1]) if v_salvo_2826[1].isdigit() else 0, key=f"num_2826_t1_{ano_sel}")

                    cir_2 = st.text_input("2ª Cirurgia eletiva:", value=v_salvo_2826[2], key=f"txt_2826_cir2_{ano_sel}")
                    tempo_cir2 = st.number_input("Tempo médio de espera cir 2 (em dias):", min_value=0, value=int(v_salvo_2826[3]) if v_salvo_2826[3].isdigit() else 0, key=f"num_2826_t2_{ano_sel}")

                    cir_3 = st.text_input("3ª Cirurgia eletiva:", value=v_salvo_2826[4], key=f"txt_2826_cir3_{ano_sel}")
                    tempo_cir3 = st.number_input("Tempo médio de espera cir 3 (em dias):", min_value=0, value=int(v_salvo_2826[5]) if v_salvo_2826[5].isdigit() else 0, key=f"num_2826_t3_{ano_sel}")

                with c2826_2:
                    link_28_2_6_input = st.text_area(
                        "Link/Evidência do tempo de espera das cirurgias (28.2.6):",
                        value=l_salvo_2826,
                        key=f"txt_link_28_2_6_maiores_esperas_{ano_sel}",
                        height=210
                    )

                placeholder_links_2826 = st.empty()
                links_2826_visuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_28_2_6_input or "")]
                if links_2826_visuais:
                    placeholder_links_2826.markdown(
                        "**🔗 Links ativos:** "
                        + " | ".join([f"[{u}]({u})" for u in links_2826_visuais])
                    )

                # Feedback visual
                preenchidos_2826 = [cir for cir in [cir_1, cir_2, cir_3] if cir.strip()]
                if preenchidos_2826:
                    st.success(f"✅ Cirurgias eletivas informadas: **{', '.join(preenchidos_2826)}**")
                else:
                    st.warning("⚠️ Nenhuma cirurgia eletiva informada.")

                # Chat de comentários
                bloco_comentarios_isaude("28.2.6", res_data)

                # Impacto de pontuação
                pts_28_2_6 = 0.0
                st.markdown(
                    f"<span style='color:#6c757d; font-weight:bold;'>"
                    f"📊 Pontuação Aplicada no Quesito 28.2.6: +{pts_28_2_6:.1f} pontos (Dados Informativos)</span>",
                    unsafe_allow_html=True,
                )

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 28.2.6", key=f"btn_salvar_28_2_6_maiores_esperas_{ano_sel}", type="primary"):
                    val_str_2826 = f"{cir_1.strip()}|{tempo_cir1}|{cir_2.strip()}|{tempo_cir2}|{cir_3.strip()}|{tempo_cir3}"
                    val_lk_2826 = link_28_2_6_input.strip()
                    comentarios_2826 = d28_2_6.get("comentarios", [])

                    save_resp_isaude(
                        qid="28.2.6",
                        valor=val_str_2826,
                        pontos=pts_28_2_6,
                        link=val_lk_2826,
                        comentarios=comentarios_2826
                    )

                    # Modal de aviso para links novos/alterados
                    links_atuais_2826 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_28_2_6_input or "")]
                    links_antigos_2826 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_2826 or "")]

                    if (val_str_2826 != d28_2_6.get("valor", "") or val_lk_2826 != l_salvo_2826) and links_atuais_2826 and links_atuais_2826 != links_antigos_2826:
                        st.session_state[f"links_pendentes_28_2_6_{ano_sel}"] = links_atuais_2826
                        st.session_state[f"gatilho_modal_28_2_6_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 28.2.6 salvos com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 28.2.6
        if st.session_state.get(f"gatilho_modal_28_2_6_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("28.2.6", st.session_state.get(f"links_pendentes_28_2_6_{ano_sel}", []), ano_sel)

# -----------------------------------------------------------------------------
        # QUESITO 28.2.7 - MAIORES TEMPOS DE ESPERA: OUTROS SERVIÇOS
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_maiores_esperas_outros_28_2_7_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 28.2.7 • Top 3 Outros Serviços com Maior Tempo de Espera ({ano_sel})", expanded=True):
                st.subheader(f"28.2.7 • Top 3 Outros Serviços com Maior Tempo de Espera ({ano_sel})")
                st.write("**Informe os 3 Outros serviços da Atenção Especializada com maior tempo de espera:**")
                st.caption("ℹ️ *Preencha os serviços e os respectivos dias de espera, informe o link e clique no botão 'Salvar Quesito 28.2.7' para registrar os dados.*")

                d28_2_7 = res_data.get("28.2.7") or {
                    "valor": "|||||",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_2827 = d28_2_7.get("valor", "|||||").split("|")
                while len(v_salvo_2827) < 6:
                    v_salvo_2827.append("")

                l_salvo_2827 = d28_2_7.get("link", "")

                c2827_1, c2827_2 = st.columns([1, 1])
                with c2827_1:
                    out_1 = st.text_input("1º Outro serviço:", value=v_salvo_2827[0], key=f"txt_2827_out1_{ano_sel}")
                    tempo_out1 = st.number_input("Tempo médio de espera out 1 (em dias):", min_value=0, value=int(v_salvo_2827[1]) if v_salvo_2827[1].isdigit() else 0, key=f"num_2827_t1_{ano_sel}")

                    out_2 = st.text_input("2º Outro serviço:", value=v_salvo_2827[2], key=f"txt_2827_out2_{ano_sel}")
                    tempo_out2 = st.number_input("Tempo médio de espera out 2 (em dias):", min_value=0, value=int(v_salvo_2827[3]) if v_salvo_2827[3].isdigit() else 0, key=f"num_2827_t2_{ano_sel}")

                    out_3 = st.text_input("3º Outro serviço:", value=v_salvo_2827[4], key=f"txt_2827_out3_{ano_sel}")
                    tempo_out3 = st.number_input("Tempo médio de espera out 3 (em dias):", min_value=0, value=int(v_salvo_2827[5]) if v_salvo_2827[5].isdigit() else 0, key=f"num_2827_t3_{ano_sel}")

                with c2827_2:
                    link_28_2_7_input = st.text_area(
                        "Link/Evidência do tempo de espera de outros serviços (28.2.7):",
                        value=l_salvo_2827,
                        key=f"txt_link_28_2_7_maiores_esperas_{ano_sel}",
                        height=210
                    )

                placeholder_links_2827 = st.empty()
                links_2827_visuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_28_2_7_input or "")]
                if links_2827_visuais:
                    placeholder_links_2827.markdown(
                        "**🔗 Links ativos:** "
                        + " | ".join([f"[{u}]({u})" for u in links_2827_visuais])
                    )

                # Feedback visual
                preenchidos_2827 = [out for out in [out_1, out_2, out_3] if out.strip()]
                if preenchidos_2827:
                    st.success(f"✅ Outros serviços informados: **{', '.join(preenchidos_2827)}**")
                else:
                    st.warning("⚠️ Nenhum outro serviço informado.")

                # Chat de comentários
                bloco_comentarios_isaude("28.2.7", res_data)

                # Impacto de pontuação
                pts_28_2_7 = 0.0
                st.markdown(
                    f"<span style='color:#6c757d; font-weight:bold;'>"
                    f"📊 Pontuação Aplicada no Quesito 28.2.7: +{pts_28_2_7:.1f} pontos (Dados Informativos)</span>",
                    unsafe_allow_html=True,
                )

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 28.2.7", key=f"btn_salvar_28_2_7_maiores_esperas_{ano_sel}", type="primary"):
                    val_str_2827 = f"{out_1.strip()}|{tempo_out1}|{out_2.strip()}|{tempo_out2}|{out_3.strip()}|{tempo_out3}"
                    val_lk_2827 = link_28_2_7_input.strip()
                    comentarios_2827 = d28_2_7.get("comentarios", [])

                    save_resp_isaude(
                        qid="28.2.7",
                        valor=val_str_2827,
                        pontos=pts_28_2_7,
                        link=val_lk_2827,
                        comentarios=comentarios_2827
                    )

                    # Modal de aviso para links novos/alterados
                    links_atuais_2827 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_28_2_7_input or "")]
                    links_antigos_2827 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_2827 or "")]

                    if (val_str_2827 != d28_2_7.get("valor", "") or val_lk_2827 != l_salvo_2827) and links_atuais_2827 and links_atuais_2827 != links_antigos_2827:
                        st.session_state[f"links_pendentes_28_2_7_{ano_sel}"] = links_atuais_2827
                        st.session_state[f"gatilho_modal_28_2_7_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 28.2.7 salvos com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 28.2.7
        if st.session_state.get(f"gatilho_modal_28_2_7_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("28.2.7", st.session_state.get(f"links_pendentes_28_2_7_{ano_sel}", []), ano_sel)

        # =============================================================================
        # SEÇÃO 29 - CADASTRO NACIONAL DE ESTABELECIMENTOS DE SAÚDE (CNES)
        # =============================================================================
        st.markdown("### 📊 Seção 29 - Atualização do CNES")

        # -----------------------------------------------------------------------------
        # QUESITO 29.0 - ATUALIZAÇÃO DO CNES
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_cnes_atualizacao_29_0_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 29.0 • Atualização do Cadastro de Estabelecimentos e Profissionais ({ano_sel})", expanded=True):
                st.subheader(f"29.0 • Atualização do Cadastro de Estabelecimentos e Profissionais ({ano_sel})")
                st.write("**O município mantém atualizado o Cadastro de Estabelecimentos e Profissionais de Saúde (CNES)?**")
                st.caption("ℹ️ *Selecione uma opção, informe o link de comprovação e clique no botão 'Salvar Quesito 29.0' para registrar as alterações.*")

                opts_29_0 = [
                    "Selecione...",
                    "SIM, os cadastros de estabelecimentos e de profissionais estão atualizados – 15",
                    "Sim, somente o cadastro de estabelecimentos está atualizado – 05",
                    "Sim, somente o cadastro de profissionais está atualizado – 05",
                    "Não – 00"
                ]

                d29_0 = res_data.get("29.0") or {
                    "valor": "Selecione...",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_290 = d29_0.get("valor", "Selecione...")
                idx_29_0 = opts_29_0.index(v_salvo_290) if v_salvo_290 in opts_29_0 else 0
                l_salvo_290 = d29_0.get("link", "")

                c290_1, c290_2 = st.columns([1, 1])
                with c290_1:
                    sel_29_0 = st.radio(
                        "Atualização do CNES:",
                        options=opts_29_0,
                        index=idx_29_0,
                        key=f"rad_29_0_{ano_sel}",
                        label_visibility="collapsed"
                    )

                with c290_2:
                    link_29_0_input = st.text_area(
                        "Link/Evidência da atualização do CNES (29.0):",
                        value=l_salvo_290,
                        key=f"txt_link_29_0_{ano_sel}",
                        height=140
                    )

                placeholder_links_290 = st.empty()
                links_290_visuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_29_0_input or "")]
                if links_290_visuais:
                    placeholder_links_290.markdown(
                        "**🔗 Links ativos:** "
                        + " | ".join([f"[{u}]({u})" for u in links_290_visuais])
                    )

                # Regras de Pontuação
                opcoes_pts_290 = {
                    "SIM, os cadastros de estabelecimentos e de profissionais estão atualizados – 15": 15.0,
                    "Sim, somente o cadastro de estabelecimentos está atualizado – 05": 5.0,
                    "Sim, somente o cadastro de profissionais está atualizado – 05": 5.0,
                    "Não – 00": 0.0,
                    "Selecione...": 0.0
                }
                pts_29_0 = opcoes_pts_290.get(sel_29_0, 0.0)

                # Feedback visual de seleção e pontuação
                if sel_29_0 == "Selecione...":
                    st.warning("⚠️ **Atenção:** Nenhuma opção válida foi selecionada. Selecione uma opção para pontuar.")
                else:
                    st.success(f"✅ Opção selecionada: **{sel_29_0}**")

                # Chat de comentários
                bloco_comentarios_isaude("29.0", res_data)

                # Impacto de pontuação
                st.markdown(
                    f"<span style='color:#198754; font-weight:bold;'>"
                    f"📊 Pontuação Aplicada no Quesito 29.0: +{pts_29_0:.1f} pontos</span>",
                    unsafe_allow_html=True,
                )

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 29.0", key=f"btn_salvar_29_0_{ano_sel}", type="primary"):
                    val_str_290 = sel_29_0
                    val_lk_290 = link_29_0_input.strip()
                    comentarios_290 = d29_0.get("comentarios", [])

                    save_resp_isaude(
                        qid="29.0",
                        valor=val_str_290,
                        pontos=pts_29_0,
                        link=val_lk_290,
                        comentarios=comentarios_290
                    )

                    # Modal de aviso para links novos/alterados
                    links_atuais_290 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_29_0_input or "")]
                    links_antigos_290 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_290 or "")]

                    if (val_str_290 != d29_0.get("valor", "") or val_lk_290 != l_salvo_290) and links_atuais_290 and links_atuais_290 != links_antigos_290:
                        st.session_state[f"links_pendentes_29_0_{ano_sel}"] = links_atuais_290
                        st.session_state[f"gatilho_modal_29_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 29.0 salvos com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 29.0
        if st.session_state.get(f"gatilho_modal_29_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("29.0", st.session_state.get(f"links_pendentes_29_0_{ano_sel}", []), ano_sel)

        # =============================================================================
        # SEÇÃO 30 - COMPLEXO REGULADOR MUNICIPAL
        # =============================================================================
        st.markdown("### 🏢 Seção 30 - Complexo Regulador Municipal")

        # -----------------------------------------------------------------------------
        # QUESITO 30.0 - POSSUI COMPLEXO REGULADOR
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_complexo_regulador_30_0_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 30.0 • Existência de Complexo Regulador Municipal ({ano_sel})", expanded=True):
                st.subheader(f"30.0 • Existência de Complexo Regulador Municipal ({ano_sel})")
                st.write("**O município possui Complexo Regulador Municipal?**")
                st.caption("ℹ️ *Selecione uma opção, informe o link de comprovação e clique no botão 'Salvar Quesito 30.0' para registrar as alterações.*")

                opts_30_0 = ["Selecione...", "Sim", "Não"]

                d30_0 = res_data.get("30.0") or {
                    "valor": "Selecione...",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_300 = d30_0.get("valor", "Selecione...")
                idx_30_0 = opts_30_0.index(v_salvo_300) if v_salvo_300 in opts_30_0 else 0
                l_salvo_300 = d30_0.get("link", "")

                c300_1, c300_2 = st.columns([1, 1])
                with c300_1:
                    sel_30_0 = st.radio(
                        "Possui complexo:",
                        options=opts_30_0,
                        index=idx_30_0,
                        key=f"rad_30_0_{ano_sel}",
                        label_visibility="collapsed"
                    )

                with c300_2:
                    link_30_0_input = st.text_area(
                        "Link/Evidência da existência do Complexo Regulador (30.0):",
                        value=l_salvo_300,
                        key=f"txt_link_30_0_{ano_sel}",
                        height=140
                    )

                placeholder_links_300 = st.empty()
                links_300_visuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_30_0_input or "")]
                if links_300_visuais:
                    placeholder_links_300.markdown(
                        "**🔗 Links ativos:** "
                        + " | ".join([f"[{u}]({u})" for u in links_300_visuais])
                    )

                # Feedback visual e Pontuação Informativa
                pts_30_0 = 0.0
                if sel_30_0 == "Selecione...":
                    st.warning("⚠️ **Atenção:** Nenhuma opção selecionada.")
                else:
                    st.success(f"✅ Opção selecionada: **{sel_30_0}**")

                # Chat de comentários
                bloco_comentarios_isaude("30.0", res_data)

                # Impacto de pontuação
                st.markdown(
                    f"<span style='color:#6c757d; font-weight:bold;'>"
                    f"📊 Pontuação Aplicada no Quesito 30.0: +{pts_30_0:.1f} pontos (Dados Informativos)</span>",
                    unsafe_allow_html=True,
                )

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 30.0", key=f"btn_salvar_30_0_{ano_sel}", type="primary"):
                    val_str_300 = sel_30_0
                    val_lk_300 = link_30_0_input.strip()
                    comentarios_300 = d30_0.get("comentarios", [])

                    save_resp_isaude(
                        qid="30.0",
                        valor=val_str_300,
                        pontos=pts_30_0,
                        link=val_lk_300,
                        comentarios=comentarios_300
                    )

                    # Modal de aviso para links novos/alterados
                    links_atuais_300 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_30_0_input or "")]
                    links_antigos_300 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_300 or "")]

                    if (val_str_300 != d30_0.get("valor", "") or val_lk_300 != l_salvo_300) and links_atuais_300 and links_atuais_300 != links_antigos_300:
                        st.session_state[f"links_pendentes_30_0_{ano_sel}"] = links_atuais_300
                        st.session_state[f"gatilho_modal_30_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 30.0 salvos com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 30.0
        if st.session_state.get(f"gatilho_modal_30_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("30.0", st.session_state.get(f"links_pendentes_30_0_{ano_sel}", []), ano_sel)

# -----------------------------------------------------------------------------
        # QUESITO 30.1 - POSSUI CENTRAL DE REGULAÇÃO
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_central_regulacao_30_1_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 30.1 • Central de Regulação ({ano_sel})", expanded=True):
                st.subheader(f"30.1 • Central de Regulação ({ano_sel})")
                st.write("**O Complexo Regulador Municipal possui Central de Regulação?**")
                st.caption("ℹ️ *Selecione uma opção, informe o link de comprovação e clique no botão 'Salvar Quesito 30.1' para registrar as alterações.*")

                opts_30_1 = ["Selecione...", "Sim", "Não"]

                d30_1 = res_data.get("30.1") or {
                    "valor": "Selecione...",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_301 = d30_1.get("valor", "Selecione...")
                idx_30_1 = opts_30_1.index(v_salvo_301) if v_salvo_301 in opts_30_1 else 0
                l_salvo_301 = d30_1.get("link", "")

                c301_1, c301_2 = st.columns([1, 1])
                with c301_1:
                    sel_30_1 = st.radio(
                        "Possui central:",
                        options=opts_30_1,
                        index=idx_30_1,
                        key=f"rad_30_1_{ano_sel}",
                        label_visibility="collapsed"
                    )

                with c301_2:
                    link_30_1_input = st.text_area(
                        "Link/Evidência da Central de Regulação (30.1):",
                        value=l_salvo_301,
                        key=f"txt_link_30_1_{ano_sel}",
                        height=140
                    )

                placeholder_links_301 = st.empty()
                links_301_visuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_30_1_input or "")]
                if links_301_visuais:
                    placeholder_links_301.markdown(
                        "**🔗 Links ativos:** "
                        + " | ".join([f"[{u}]({u})" for u in links_301_visuais])
                    )

                # Feedback visual e Pontuação
                pts_30_1 = 0.0
                if sel_30_1 == "Selecione...":
                    st.warning("⚠️ **Atenção:** Nenhuma opção selecionada.")
                else:
                    st.success(f"✅ Opção selecionada: **{sel_30_1}**")

                # Chat de comentários
                bloco_comentarios_isaude("30.1", res_data)

                # Impacto de pontuação
                st.markdown(
                    f"<span style='color:#6c757d; font-weight:bold;'>"
                    f"📊 Pontuação Aplicada no Quesito 30.1: +{pts_30_1:.1f} pontos (Dados Informativos)</span>",
                    unsafe_allow_html=True,
                )

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 30.1", key=f"btn_salvar_30_1_{ano_sel}", type="primary"):
                    val_str_301 = sel_30_1
                    val_lk_301 = link_30_1_input.strip()
                    comentarios_301 = d30_1.get("comentarios", [])

                    save_resp_isaude(
                        qid="30.1",
                        valor=val_str_301,
                        pontos=pts_30_1,
                        link=val_lk_301,
                        comentarios=comentarios_301
                    )

                    # Modal de aviso para links novos/alterados
                    links_atuais_301 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_30_1_input or "")]
                    links_antigos_301 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_301 or "")]

                    if (val_str_301 != d30_1.get("valor", "") or val_lk_301 != l_salvo_301) and links_atuais_301 and links_atuais_301 != links_antigos_301:
                        st.session_state[f"links_pendentes_30_1_{ano_sel}"] = links_atuais_301
                        st.session_state[f"gatilho_modal_30_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 30.1 salvos com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 30.1
        if st.session_state.get(f"gatilho_modal_30_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("30.1", st.session_state.get(f"links_pendentes_30_1_{ano_sel}", []), ano_sel)

        # -----------------------------------------------------------------------------
        # QUESITO 30.1.1 - TIPOS DE CENTRAL UTILIZADOS
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_tipos_central_30_1_1_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 30.1.1 • Tipos de Central de Regulação Utilizados ({ano_sel})", expanded=True):
                st.subheader(f"30.1.1 • Tipos de Central de Regulação Utilizados ({ano_sel})")
                st.write("**Assinale os tipos de central de regulação municipal ou regional utilizados pelo município:**")
                st.caption("ℹ️ *Selecione as opções desejadas, informe o link de comprovação e clique no botão 'Salvar Quesito 30.1.1' para registrar os dados.*")

                d30_1_1 = res_data.get("30.1.1") or {
                    "valor": "",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_3011 = d30_1_1.get("valor", "").split("|")
                l_salvo_3011 = d30_1_1.get("link", "")

                central_specs = {
                    "urgencia": {"text": "Central de Urgência – 03", "pts": 3.0},
                    "internacoes": {"text": "Central de Internações – 03", "pts": 3.0},
                    "consultas_servicos": {"text": "Central de Consultas e Serviços de Apoio Diagnóstico e terapêutico – 03", "pts": 3.0}
                }

                c3011_1, c3011_2 = st.columns([1, 1])
                chks_selecionados_3011 = []
                pts_totais_30_1_1 = 0.0

                with c3011_1:
                    for k, spec in central_specs.items():
                        marcado = st.checkbox(
                            spec["text"],
                            value=k in v_salvo_3011,
                            key=f"chk_30_1_1_{k}_{ano_sel}"
                        )
                        if marcado:
                            chks_selecionados_3011.append(k)
                            pts_totais_30_1_1 += spec["pts"]

                with c3011_2:
                    link_30_1_1_input = st.text_area(
                        "Link/Evidência dos tipos de central (30.1.1):",
                        value=l_salvo_3011,
                        key=f"txt_link_30_1_1_{ano_sel}",
                        height=140
                    )

                placeholder_links_3011 = st.empty()
                links_3011_visuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_30_1_input or "")]
                if links_3011_visuais:
                    placeholder_links_3011.markdown(
                        "**🔗 Links ativos:** "
                        + " | ".join([f"[{u}]({u})" for u in links_3011_visuais])
                    )

                # Feedback visual
                if chks_selecionados_3011:
                    st.success(f"✅ {len(chks_selecionados_3011)} opção(ões) selecionada(s).")
                else:
                    st.warning("⚠️ Nenhum tipo de central foi selecionado.")

                # Chat de comentários
                bloco_comentarios_isaude("30.1.1", res_data)

                # Impacto de pontuação
                st.markdown(
                    f"<span style='color:#198754; font-weight:bold;'>"
                    f"📊 Pontuação Aplicada no Quesito 30.1.1: +{pts_totais_30_1_1:.1f} pontos</span>",
                    unsafe_allow_html=True,
                )

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 30.1.1", key=f"btn_salvar_30_1_1_{ano_sel}", type="primary"):
                    val_str_3011 = "|".join(chks_selecionados_3011)
                    val_lk_3011 = link_30_1_1_input.strip()
                    comentarios_3011 = d30_1_1.get("comentarios", [])

                    save_resp_isaude(
                        qid="30.1.1",
                        valor=val_str_3011,
                        pontos=pts_totais_30_1_1,
                        link=val_lk_3011,
                        comentarios=comentarios_3011
                    )

                    # Modal de aviso para links novos/alterados
                    links_atuais_3011 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_30_1_1_input or "")]
                    links_antigos_3011 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_3011 or "")]

                    if (val_str_3011 != d30_1_1.get("valor", "") or val_lk_3011 != l_salvo_3011) and links_atuais_3011 and links_atuais_3011 != links_antigos_3011:
                        st.session_state[f"links_pendentes_30_1_1_{ano_sel}"] = links_atuais_3011
                        st.session_state[f"gatilho_modal_30_1_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 30.1.1 salvos com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 30.1.1
        if st.session_state.get(f"gatilho_modal_30_1_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("30.1.1", st.session_state.get(f"links_pendentes_30_1_1_{ano_sel}", []), ano_sel)

        # =============================================================================
        # SEÇÃO 31 - ATENÇÃO PRÉ-HOSPITALAR E SAMU 192
        # =============================================================================
        st.markdown("### 🚑 Seção 31 - Atenção Pré-Hospitalar e SAMU 192")

        # -----------------------------------------------------------------------------
        # QUESITO 31.0 - SERVIÇO PRÉ-HOSPITALAR E INTEGRAÇÃO SAMU 192
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_pre_hospitalar_samu_31_0_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 31.0 • Serviço Pré-Hospitalar e Integração SAMU 192 ({ano_sel})", expanded=True):
                st.subheader(f"31.0 • Serviço Pré-Hospitalar e Integração SAMU 192 ({ano_sel})")
                st.write("**O município possui serviços de atenção pré-hospitalar e Central Samu 192 ou integra Central Samu 192 de abrangência regional?**")
                st.caption("ℹ️ *Selecione uma opção, informe o link de comprovação e clique no botão 'Salvar Quesito 31.0' para registrar as alterações.*")

                opts_31_0 = ["Selecione...", "Sim", "Não"]

                d31_0 = res_data.get("31.0") or {
                    "valor": "Selecione...",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_310 = d31_0.get("valor", "Selecione...")
                idx_31_0 = opts_31_0.index(v_salvo_310) if v_salvo_310 in opts_31_0 else 0
                l_salvo_310 = d31_0.get("link", "")

                c310_1, c310_2 = st.columns([1, 1])
                with c310_1:
                    sel_31_0 = st.radio(
                        "Atenção pré-hospitalar / SAMU:",
                        options=opts_31_0,
                        index=idx_31_0,
                        key=f"rad_31_0_{ano_sel}",
                        label_visibility="collapsed"
                    )

                with c310_2:
                    link_31_0_input = st.text_area(
                        "Link/Evidência da atenção pré-hospitalar / SAMU (31.0):",
                        value=l_salvo_310,
                        key=f"txt_link_31_0_{ano_sel}",
                        height=140
                    )

                placeholder_links_310 = st.empty()
                links_310_visuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_31_0_input or "")]
                if links_310_visuais:
                    placeholder_links_310.markdown(
                        "**🔗 Links ativos:** "
                        + " | ".join([f"[{u}]({u})" for u in links_310_visuais])
                    )

                # Feedback visual e Pontuação Informativa
                pts_31_0 = 0.0
                if sel_31_0 == "Selecione...":
                    st.warning("⚠️ **Atenção:** Nenhuma opção selecionada.")
                else:
                    st.success(f"✅ Opção selecionada: **{sel_31_0}**")

                # Chat de comentários
                bloco_comentarios_isaude("31.0", res_data)

                # Impacto de pontuação
                st.markdown(
                    f"<span style='color:#6c757d; font-weight:bold;'>"
                    f"📊 Pontuação Aplicada no Quesito 31.0: +{pts_31_0:.1f} pontos (Dados Informativos)</span>",
                    unsafe_allow_html=True,
                )

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 31.0", key=f"btn_salvar_31_0_{ano_sel}", type="primary"):
                    val_str_310 = sel_31_0
                    val_lk_310 = link_31_0_input.strip()
                    comentarios_310 = d31_0.get("comentarios", [])

                    save_resp_isaude(
                        qid="31.0",
                        valor=val_str_310,
                        pontos=pts_31_0,
                        link=val_lk_310,
                        comentarios=comentarios_310
                    )

                    # Modal de aviso para links novos/alterados
                    links_atuais_310 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_31_0_input or "")]
                    links_antigos_310 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_310 or "")]

                    if (val_str_310 != d31_0.get("valor", "") or val_lk_310 != l_salvo_310) and links_atuais_310 and links_atuais_310 != links_antigos_310:
                        st.session_state[f"links_pendentes_31_0_{ano_sel}"] = links_atuais_310
                        st.session_state[f"gatilho_modal_31_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 31.0 salvos com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 31.0
        if st.session_state.get(f"gatilho_modal_31_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("31.0", st.session_state.get(f"links_pendentes_31_0_{ano_sel}", []), ano_sel)

       # -----------------------------------------------------------------------------
        # QUESITO 31.1 - TEMPO DE RESPOSTA DO SAMU (TMR)
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_tempo_resposta_samu_31_1_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 31.1 • Tempo de Resposta em Minutos dos Atendimentos do SAMU ({ano_sel})", expanded=True):
                st.subheader(f"31.1 • Tempo de Resposta em Minutos dos Atendimentos do SAMU ({ano_sel})")
                st.write("**Informe o tempo de resposta em minutos dos atendimentos do SAMU (ou equivalente):**")
                st.caption("ℹ️ *Preencha os tempos numéricos, informe o link de comprovação e clique no botão 'Salvar Quesito 31.1' para registrar as alterações.*")

                # --- INICIALIZAÇÃO PREVENTIVA DA VARIÁVEL ---
                df_tmr_inicial = pd.DataFrame()

                # Cálculo dinâmico dos anos baseado no ano selecionado
                try:
                    ano_atual_int = int(ano_sel)
                except (ValueError, TypeError):
                    ano_atual_int = 2025

                ano_tmr2 = ano_atual_int - 2
                ano_tmr1 = ano_atual_int - 1
                ano_tmr = ano_atual_int

                st.caption(
                    f"ℹ️ *Fórmula de avaliação baseada no Ano Selecionado ({ano_tmr}):* "
                    f"Melhoria ou Estabilidade = 0.0 pontos | Piora [TMR > ({ano_tmr2} + {ano_tmr1}) / 2] = -5.0 pontos"
                )

                d31_1 = res_data.get("31.1") or {
                    "valor": "0|0|0|0|0|0|0|0|0",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_311 = (d31_1.get("valor") or "0|0|0|0|0|0|0|0|0").split("|")
                while len(v_salvo_311) < 9:
                    v_salvo_311.append("0")

                def safe_int(val):
                    try:
                        return int(float(val))
                    except (ValueError, TypeError):
                        return 0

                l_salvo_311 = d31_1.get("link", "")

                c311_1, c311_2 = st.columns([1.2, 1])

                with c311_1:
                    df_tmr_inicial = pd.DataFrame(
                        {
                            "Mínimo (min)": [safe_int(v_salvo_311[0]), safe_int(v_salvo_311[3]), safe_int(v_salvo_311[6])],
                            "Médio (min)": [safe_int(v_salvo_311[1]), safe_int(v_salvo_311[4]), safe_int(v_salvo_311[7])],
                            "Máximo (min)": [safe_int(v_salvo_311[2]), safe_int(v_salvo_311[5]), safe_int(v_salvo_311[8])]
                        },
                        index=[f"Ano {ano_tmr2} (TMR-2)", f"Ano {ano_tmr1} (TMR-1)", f"Ano {ano_tmr} (Atual)"]
                    )

                    df_tmr_editado = st.data_editor(
                        df_tmr_inicial,
                        key=f"editor_tmr_31_1_{ano_sel}",
                        use_container_width=True,
                        column_config={
                            "Mínimo (min)": st.column_config.NumberColumn(min_value=0, step=1, format="%d"),
                            "Médio (min)": st.column_config.NumberColumn(min_value=0, step=1, format="%d"),
                            "Máximo (min)": st.column_config.NumberColumn(min_value=0, step=1, format="%d")
                        }
                    )

                    tmr2_min = safe_int(df_tmr_editado.iloc[0]["Mínimo (min)"])
                    tmr2_med = safe_int(df_tmr_editado.iloc[0]["Médio (min)"])
                    tmr2_max = safe_int(df_tmr_editado.iloc[0]["Máximo (min)"])

                    tmr1_min = safe_int(df_tmr_editado.iloc[1]["Mínimo (min)"])
                    tmr1_med = safe_int(df_tmr_editado.iloc[1]["Médio (min)"])
                    tmr1_max = safe_int(df_tmr_editado.iloc[1]["Máximo (min)"])

                    tmr_min = safe_int(df_tmr_editado.iloc[2]["Mínimo (min)"])
                    tmr_med = safe_int(df_tmr_editado.iloc[2]["Médio (min)"])
                    tmr_max = safe_int(df_tmr_editado.iloc[2]["Máximo (min)"])

                with c311_2:
                    link_31_1_input = st.text_area(
                        "Link/Evidência do Tempo de Resposta do SAMU (31.1):",
                        value=l_salvo_311,
                        key=f"txt_link_31_1_{ano_sel}",
                        height=150
                    )

                placeholder_links_311 = st.empty()
                links_311_visuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_31_1_input or "")]
                if links_311_visuais:
                    placeholder_links_311.markdown(
                        "**🔗 Links ativos:** "
                        + " | ".join([f"[{u}]({u})" for u in links_311_visuais])
                    )

                # Regra e cálculo de pontuação
                meta_media = (tmr2_med + tmr1_med) / 2.0
                
                m1, m2 = st.columns(2)
                m1.metric(label=f"Média dos Anos Anteriores ({ano_tmr2} e {ano_tmr1})", value=f"{meta_media:.1f} min")
                m2.metric(label=f"Tempo Médio Atual ({ano_tmr})", value=f"{tmr_med} min", delta=f"{tmr_med - meta_media:.1f} min", delta_color="inverse")

                if tmr2_med == 0 and tmr1_med == 0 and tmr_med == 0:
                    pts_31_1 = 0.0
                    st.info("ℹ️ **Status:** Preencha os tempos médios dos anos para calcular a regra de pontuação.")
                elif tmr_med > meta_media:
                    pts_31_1 = -5.0
                    st.error(f"⚠️ O Tempo Médio de Resposta atual ({tmr_med} min) é maior que a média anterior ({meta_media:.1f} min). Penalidade Aplicada: `-5.0 pontos`.")
                else:
                    pts_31_1 = 0.0
                    st.success(f"✅ O Tempo Médio de Resposta atual ({tmr_med} min) manteve estabilidade ou melhoria em relação à média anterior ({meta_media:.1f} min). Sem penalidade: `0.0 pontos`.")

                # Chat de comentários
                bloco_comentarios_isaude("31.1", res_data)

                # Impacto de pontuação
                st.markdown(
                    f"<span style='color:#6c757d; font-weight:bold;'>"
                    f"📊 Pontuação Aplicada no Quesito 31.1: {pts_31_1:.1f} pontos</span>",
                    unsafe_allow_html=True,
                )

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 31.1", key=f"btn_salvar_31_1_{ano_sel}", type="primary"):
                    val_str_311 = f"{tmr2_min}|{tmr2_med}|{tmr2_max}|{tmr1_min}|{tmr1_med}|{tmr1_max}|{tmr_min}|{tmr_med}|{tmr_max}"
                    val_lk_311 = link_31_1_input.strip()
                    comentarios_311 = d31_1.get("comentarios", [])

                    save_resp_isaude(
                        qid="31.1",
                        valor=val_str_311,
                        pontos=pts_31_1,
                        link=val_lk_311,
                        comentarios=comentarios_311
                    )

                    # Modal de aviso para links novos/alterados
                    links_atuais_311 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_31_1_input or "")]
                    links_antigos_311 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_311 or "")]

                    if (val_str_311 != d31_1.get("valor", "") or val_lk_311 != l_salvo_311) and links_atuais_311 and links_atuais_311 != links_antigos_311:
                        st.session_state[f"links_pendentes_31_1_{ano_sel}"] = links_atuais_311
                        st.session_state[f"gatilho_modal_31_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 31.1 salvos com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 31.1
        if st.session_state.get(f"gatilho_modal_31_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("31.1", st.session_state.get(f"links_pendentes_31_1_{ano_sel}", []), ano_sel)


        # -----------------------------------------------------------------------------
        # QUESITO 31.2 - COMPOSIÇÃO MÍNIMA DA CENTRAL DE REGULAÇÃO DE URGÊNCIAS
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_composicao_central_31_2_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 31.2 • Composição Mínima das Equipes da Central de Regulação ({ano_sel})", expanded=True):
                st.subheader(f"31.2 • Composição Mínima das Equipes da Central de Regulação ({ano_sel})")
                st.write("**As equipes da Central de Regulação das Urgências tiveram ao menos a composição mínima estipulada na legislação no decorrer do exercício?**")
                st.caption("ℹ️ *Selecione uma opção, informe o link de comprovação e clique no botão 'Salvar Quesito 31.2' para registrar as alterações.*")

                opts_31_2 = [
                    "Selecione...",
                    "Todas as equipes tinham composição mínima – 00",
                    "A maior parte das equipes tinham composição mínima – -03 (perde 03 pontos)",
                    "A menor parte das equipes tinham composição mínima – -07 (perde 07 pontos)",
                    "Nenhuma equipe tinha composição mínima – -10 (perde 10 pontos)"
                ]

                d31_2 = res_data.get("31.2") or {
                    "valor": "Selecione...",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_312 = d31_2.get("valor", "Selecione...")
                idx_31_2 = opts_31_2.index(v_salvo_312) if v_salvo_312 in opts_31_2 else 0
                l_salvo_312 = d31_2.get("link", "")

                c312_1, c312_2 = st.columns([1, 1])
                with c312_1:
                    sel_31_2 = st.radio(
                        "Composição Central de Regulação:",
                        options=opts_31_2,
                        index=idx_31_2,
                        key=f"rad_31_2_{ano_sel}",
                        label_visibility="collapsed"
                    )

                with c312_2:
                    link_31_2_input = st.text_area(
                        "Link/Evidência da composição da Central de Regulação (31.2):",
                        value=l_salvo_312,
                        key=f"txt_link_31_2_{ano_sel}",
                        height=140
                    )

                placeholder_links_312 = st.empty()
                links_312_visuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_31_2_input or "")]
                if links_312_visuais:
                    placeholder_links_312.markdown(
                        "**🔗 Links ativos:** "
                        + " | ".join([f"[{u}]({u})" for u in links_312_visuais])
                    )

                # Tabela de Pontuação
                opcoes_pts_312 = {
                    "Todas as equipes tinham composição mínima – 00": 0.0,
                    "A maior parte das equipes tinham composição mínima – -03 (perde 03 pontos)": -3.0,
                    "A menor parte das equipes tinham composição mínima – -07 (perde 07 pontos)": -7.0,
                    "Nenhuma equipe tinha composição mínima – -10 (perde 10 pontos)": -10.0,
                    "Selecione...": 0.0
                }
                pts_31_2 = opcoes_pts_312.get(sel_31_2, 0.0)

                # Feedback visual
                if sel_31_2 == "Selecione...":
                    st.warning("⚠️ **Atenção:** Nenhuma opção selecionada.")
                elif pts_31_2 < 0:
                    st.error(f"⚠️ Opção selecionada: **{sel_31_2}** (Penalidade: `{pts_31_2:.1f} pontos`)")
                else:
                    st.success(f"✅ Opção selecionada: **{sel_31_2}** (Conformidade atingida)")

                # Chat de comentários
                bloco_comentarios_isaude("31.2", res_data)

                # Impacto de pontuação
                st.markdown(
                    f"<span style='color:#6c757d; font-weight:bold;'>"
                    f"📊 Pontuação Aplicada no Quesito 31.2: {pts_31_2:.1f} pontos</span>",
                    unsafe_allow_html=True,
                )

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 31.2", key=f"btn_salvar_31_2_{ano_sel}", type="primary"):
                    val_str_312 = sel_31_2
                    val_lk_312 = link_31_2_input.strip()
                    comentarios_312 = d31_2.get("comentarios", [])

                    save_resp_isaude(
                        qid="31.2",
                        valor=val_str_312,
                        pontos=pts_31_2,
                        link=val_lk_312,
                        comentarios=comentarios_312
                    )

                    # Modal de aviso para links novos/alterados
                    links_atuais_312 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_31_2_input or "")]
                    links_antigos_312 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_312 or "")]

                    if (val_str_312 != d31_2.get("valor", "") or val_lk_312 != l_salvo_312) and links_atuais_312 and links_atuais_312 != links_antigos_312:
                        st.session_state[f"links_pendentes_31_2_{ano_sel}"] = links_atuais_312
                        st.session_state[f"gatilho_modal_31_2_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 31.2 salvos com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 31.2
        if st.session_state.get(f"gatilho_modal_31_2_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("31.2", st.session_state.get(f"links_pendentes_31_2_{ano_sel}", []), ano_sel)


        # -----------------------------------------------------------------------------
        # QUESITO 31.3 - COMPOSIÇÃO MÍNIMA DAS UNIDADES MÓVEIS
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_composicao_unidades_moveis_31_3_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 31.3 • Composição Mínima das Equipes das Unidades Móveis ({ano_sel})", expanded=True):
                st.subheader(f"31.3 • Composição Mínima das Equipes das Unidades Móveis ({ano_sel})")
                st.write("**As equipes das Unidades Móveis tiveram ao menos a composição mínima estipulada na legislação no decorrer do exercício?**")
                st.caption("ℹ️ *Selecione uma opção, informe o link de comprovação e clique no botão 'Salvar Quesito 31.3' para registrar as alterações.*")

                opts_31_3 = [
                    "Selecione...",
                    "Todas as equipes tinham composição mínima – 00",
                    "A maior parte das equipes tinham composição mínima – -10 (perde 10 pontos)",
                    "A menor parte das equipes tinham composição mínima – -15 (perde 15 pontos)",
                    "Nenhuma equipe tinha composição mínima – -20 (perde 20 pontos)"
                ]

                d31_3 = res_data.get("31.3") or {
                    "valor": "Selecione...",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_313 = d31_3.get("valor", "Selecione...")
                idx_31_3 = opts_31_3.index(v_salvo_313) if v_salvo_313 in opts_31_3 else 0
                l_salvo_313 = d31_3.get("link", "")

                c313_1, c313_2 = st.columns([1, 1])
                with c313_1:
                    sel_31_3 = st.radio(
                        "Composição Unidades Móveis:",
                        options=opts_31_3,
                        index=idx_31_3,
                        key=f"rad_31_3_{ano_sel}",
                        label_visibility="collapsed"
                    )

                with c313_2:
                    link_31_3_input = st.text_area(
                        "Link/Evidência da composição das Unidades Móveis (31.3):",
                        value=l_salvo_313,
                        key=f"txt_link_31_3_{ano_sel}",
                        height=140
                    )

                placeholder_links_313 = st.empty()
                links_313_visuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_31_3_input or "")]
                if links_313_visuais:
                    placeholder_links_313.markdown(
                        "**🔗 Links ativos:** "
                        + " | ".join([f"[{u}]({u})" for u in links_313_visuais])
                    )

                # Tabela de Pontuação
                opcoes_pts_313 = {
                    "Todas as equipes tinham composição mínima – 00": 0.0,
                    "A maior parte das equipes tinham composição mínima – -10 (perde 10 pontos)": -10.0,
                    "A menor parte das equipes tinham composição mínima – -15 (perde 15 pontos)": -15.0,
                    "Nenhuma equipe tinha composição mínima – -20 (perde 20 pontos)": -20.0,
                    "Selecione...": 0.0
                }
                pts_31_3 = opcoes_pts_313.get(sel_31_3, 0.0)

                # Feedback visual
                if sel_31_3 == "Selecione...":
                    st.warning("⚠️ **Atenção:** Nenhuma opção selecionada.")
                elif pts_31_3 < 0:
                    st.error(f"⚠️ Opção selecionada: **{sel_31_3}** (Penalidade: `{pts_31_3:.1f} pontos`)")
                else:
                    st.success(f"✅ Opção selecionada: **{sel_31_3}** (Conformidade atingida)")

                # Chat de comentários
                bloco_comentarios_isaude("31.3", res_data)

                # Impacto de pontuação
                st.markdown(
                    f"<span style='color:#6c757d; font-weight:bold;'>"
                    f"📊 Pontuação Aplicada no Quesito 31.3: {pts_31_3:.1f} pontos</span>",
                    unsafe_allow_html=True,
                )

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 31.3", key=f"btn_salvar_31_3_{ano_sel}", type="primary"):
                    val_str_313 = sel_31_3
                    val_lk_313 = link_31_3_input.strip()
                    comentarios_313 = d31_3.get("comentarios", [])

                    save_resp_isaude(
                        qid="31.3",
                        valor=val_str_313,
                        pontos=pts_31_3,
                        link=val_lk_313,
                        comentarios=comentarios_313
                    )

                    # Modal de aviso para links novos/alterados
                    links_atuais_313 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_31_3_input or "")]
                    links_antigos_313 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_313 or "")]

                    if (val_str_313 != d31_3.get("valor", "") or val_lk_313 != l_salvo_313) and links_atuais_313 and links_atuais_313 != links_antigos_313:
                        st.session_state[f"links_pendentes_31_3_{ano_sel}"] = links_atuais_313
                        st.session_state[f"gatilho_modal_31_3_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 31.3 salvos com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 31.3
        if st.session_state.get(f"gatilho_modal_31_3_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("31.3", st.session_state.get(f"links_pendentes_31_3_{ano_sel}", []), ano_sel)

# =============================================================================
        # SEÇÃO 32 - GERENCIAMENTO DE ESTOQUE
        # =============================================================================
        st.markdown("### 📦 Seção 32 - Gerenciamento de Estoque")

        # -----------------------------------------------------------------------------
        # QUESITO 32.0 - SISTEMA INFORMATIZADO DE ESTOQUE
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_gerenciamento_estoque_32_0_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 32.0 • Sistema Informatizado para Estoque de Materiais e Insumos ({ano_sel})", expanded=True):
                st.subheader(f"32.0 • Sistema Informatizado para Estoque de Materiais e Insumos ({ano_sel})")
                st.write("**32.0 O município utiliza sistema informatizado para gerenciar o estoque de materiais e insumos médicos?**")
                st.caption("ℹ️ *Selecione uma opção, informe o link de comprovação e clique no botão 'Salvar Quesito 32.0' para registrar as alterações.*")

                opts_32_0 = ["Selecione...", "Sim", "Não"]

                d32_0 = res_data.get("32.0") or {
                    "valor": "Selecione...",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_320 = d32_0.get("valor", "Selecione...")
                idx_32_0 = opts_32_0.index(v_salvo_320) if v_salvo_320 in opts_32_0 else 0
                l_salvo_320 = d32_0.get("link", "")

                c320_1, c320_2 = st.columns([1, 1])
                with c320_1:
                    sel_32_0 = st.radio(
                        "Sistema de estoque:",
                        options=opts_32_0,
                        index=idx_32_0,
                        key=f"rad_32_0_{ano_sel}",
                        label_visibility="collapsed"
                    )

                with c320_2:
                    link_32_0_input = st.text_area(
                        "Link/Evidência do Sistema de Estoque (32.0):",
                        value=l_salvo_320,
                        key=f"txt_link_32_0_{ano_sel}",
                        height=140
                    )

                placeholder_links_320 = st.empty()
                links_320_visuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_32_0_input or "")]
                if links_320_visuais:
                    placeholder_links_320.markdown(
                        "**🔗 Links ativos:** "
                        + " | ".join([f"[{u}]({u})" for u in links_320_visuais])
                    )

                # Feedback visual e Pontuação Informativa
                pts_32_0 = 0.0
                if sel_32_0 == "Selecione...":
                    st.warning("⚠️ **Atenção:** Nenhuma opção selecionada.")
                else:
                    st.success(f"✅ Opção selecionada: **{sel_32_0}**")

                # Chat de comentários
                bloco_comentarios_isaude("32.0", res_data)

                # Impacto de pontuação
                st.markdown(
                    f"<span style='color:#6c757d; font-weight:bold;'>"
                    f"📊 Pontuação Aplicada no Quesito 32.0: +{pts_32_0:.1f} pontos (Dados Informativos)</span>",
                    unsafe_allow_html=True,
                )

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 32.0", key=f"btn_salvar_32_0_{ano_sel}", type="primary"):
                    val_str_320 = sel_32_0
                    val_lk_320 = link_32_0_input.strip()
                    comentarios_320 = d32_0.get("comentarios", [])

                    save_resp_isaude(
                        qid="32.0",
                        valor=val_str_320,
                        pontos=pts_32_0,
                        link=val_lk_320,
                        comentarios=comentarios_320
                    )

                    # Modal de aviso para links novos/alterados
                    links_atuais_320 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_32_0_input or "")]
                    links_antigos_320 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_320 or "")]

                    if (val_str_320 != d32_0.get("valor", "") or val_lk_320 != l_salvo_320) and links_atuais_320 and links_atuais_320 != links_antigos_320:
                        st.session_state[f"links_pendentes_32_0_{ano_sel}"] = links_atuais_320
                        st.session_state[f"gatilho_modal_32_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 32.0 salvos com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 32.0
        if st.session_state.get(f"gatilho_modal_32_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("32.0", st.session_state.get(f"links_pendentes_32_0_{ano_sel}", []), ano_sel)

        # -----------------------------------------------------------------------------
        # QUESITO 32.1 - FUNÇÕES DO SISTEMA DE GESTÃO DE ESTOQUE
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_funcoes_estoque_32_1_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 32.1 • Funções do Sistema de Gestão de Estoque ({ano_sel})", expanded=True):
                st.subheader(f"32.1 • Funções do Sistema de Gestão de Estoque ({ano_sel})")
                st.write("**32.1 Assinale as funções do sistema de gestão de estoque de materiais e insumos médicos:**")
                st.caption("ℹ️ *Marque as opções aplicáveis, informe o link de comprovação e clique no botão 'Salvar Quesito 32.1' para registrar as alterações.*")

                d32_1 = res_data.get("32.1") or {
                    "valor": "",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_321 = d32_1.get("valor", "").split("|")
                l_salvo_321 = d32_1.get("link", "")

                estoque_specs = {
                    "posicao_lote": {"text": "Fornece a posição de estoque, movimentação de entrada e saída, lote e validade – 15", "pts": 15.0},
                    "processo_compras": {"text": "Gerenciar o processo de compras dos insumos/materiais de saúde, desde o planejamento até a entrega e o recebimento da nota fiscal – 15", "pts": 15.0},
                    "reposicao_estab": {"text": "Gerenciar a reposição dos insumos/materiais de saúde por estabelecimento de saúde – 15", "pts": 15.0},
                    "outros": {"text": "Outros – 00", "pts": 0.0}
                }

                c321_1, c321_2 = st.columns([1, 1])
                chks_selecionados_321 = []
                pts_totais_32_1 = 0.0

                keys_estoque = list(estoque_specs.keys())
                metade_estoque = (len(keys_estoque) + 1) // 2

                with c321_1:
                    for k in keys_estoque[:metade_estoque]:
                        marcado = st.checkbox(estoque_specs[k]["text"], value=k in v_salvo_321, key=f"chk_32_1_{k}_{ano_sel}")
                        if marcado:
                            chks_selecionados_321.append(k)
                            pts_totais_32_1 += estoque_specs[k]["pts"]

                with c321_2:
                    for k in keys_estoque[metade_estoque:]:
                        marcado = st.checkbox(estoque_specs[k]["text"], value=k in v_salvo_321, key=f"chk_32_1_{k}_{ano_sel}")
                        if marcado:
                            chks_selecionados_321.append(k)
                            pts_totais_32_1 += estoque_specs[k]["pts"]

                link_32_1_input = st.text_area(
                    "Link/Evidência das Funções do Estoque (32.1):",
                    value=l_salvo_321,
                    key=f"txt_link_32_1_{ano_sel}",
                    height=140
                )

                placeholder_links_321 = st.empty()
                links_321_visuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_32_1_input or "")]
                if links_321_visuais:
                    placeholder_links_321.markdown(
                        "**🔗 Links ativos:** "
                        + " | ".join([f"[{u}]({u})" for u in links_321_visuais])
                    )

                # Chat de comentários
                bloco_comentarios_isaude("32.1", res_data)

                # Impacto de pontuação
                st.markdown(
                    f"<span style='color:#6c757d; font-weight:bold;'>"
                    f"📊 Pontuação Aplicada no Quesito 32.1: +{pts_totais_32_1:.1f} pontos</span>",
                    unsafe_allow_html=True,
                )

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 32.1", key=f"btn_salvar_32_1_{ano_sel}", type="primary"):
                    val_str_321 = "|".join(chks_selecionados_321)
                    val_lk_321 = link_32_1_input.strip()
                    comentarios_321 = d32_1.get("comentarios", [])

                    save_resp_isaude(
                        qid="32.1",
                        valor=val_str_321,
                        pontos=pts_totais_32_1,
                        link=val_lk_321,
                        comentarios=comentarios_321
                    )

                    # Modal de aviso para links novos/alterados
                    links_atuais_321 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_32_1_input or "")]
                    links_antigos_321 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_321 or "")]

                    if (val_str_321 != d32_1.get("valor", "") or val_lk_321 != l_salvo_321) and links_atuais_321 and links_atuais_321 != links_antigos_321:
                        st.session_state[f"links_pendentes_32_1_{ano_sel}"] = links_atuais_321
                        st.session_state[f"gatilho_modal_32_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 32.1 salvos com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 32.1
        if st.session_state.get(f"gatilho_modal_32_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("32.1", st.session_state.get(f"links_pendentes_32_1_{ano_sel}", []), ano_sel)

# =============================================================================
        # SEÇÃO 33 - OUVIDORIA DA SAÚDE
        # =============================================================================
        st.markdown("### 🗣️ Seção 33 - Ouvidoria da Saúde")

        # -----------------------------------------------------------------------------
        # QUESITO 33.0 - IMPLANTAÇÃO DA OUVIDORIA
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_ouvidoria_saude_33_0_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 33.0 • Ouvidoria da Saúde Implantada ({ano_sel})", expanded=True):
                st.subheader(f"33.0 • Ouvidoria da Saúde Implantada ({ano_sel})")
                st.write("**33.0 O município possui Ouvidoria da Saúde implantada?**")
                st.caption("ℹ️ *Selecione uma opção, informe o link de comprovação e clique no botão 'Salvar Quesito 33.0' para registrar as alterações.*")

                opts_33_0 = ["Selecione...", "Sim", "Não"]

                d33_0 = res_data.get("33.0") or {
                    "valor": "Selecione...",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_330 = d33_0.get("valor", "Selecione...")
                idx_33_0 = opts_33_0.index(v_salvo_330) if v_salvo_330 in opts_33_0 else 0
                l_salvo_330 = d33_0.get("link", "")

                c330_1, c330_2 = st.columns([1, 1])
                with c330_1:
                    sel_33_0 = st.radio(
                        "Ouvidoria implantada:",
                        options=opts_33_0,
                        index=idx_33_0,
                        key=f"rad_33_0_{ano_sel}",
                        label_visibility="collapsed"
                    )

                with c330_2:
                    link_33_0_input = st.text_area(
                        "Link/Evidência da Ouvidoria (33.0):",
                        value=l_salvo_330,
                        key=f"txt_link_33_0_{ano_sel}",
                        height=140
                    )

                placeholder_links_330 = st.empty()
                links_330_visuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_33_0_input or "")]
                if links_330_visuais:
                    placeholder_links_330.markdown(
                        "**🔗 Links ativos:** "
                        + " | ".join([f"[{u}]({u})" for u in links_330_visuais])
                    )

                # Feedback visual e Pontuação Informativa
                pts_33_0 = 0.0
                if sel_33_0 == "Selecione...":
                    st.warning("⚠️ **Atenção:** Nenhuma opção selecionada.")
                else:
                    st.success(f"✅ Opção selecionada: **{sel_33_0}**")

                # Chat de comentários
                bloco_comentarios_isaude("33.0", res_data)

                # Impacto de pontuação
                st.markdown(
                    f"<span style='color:#6c757d; font-weight:bold;'>"
                    f"📊 Pontuação Aplicada no Quesito 33.0: +{pts_33_0:.1f} pontos (Dados Informativos)</span>",
                    unsafe_allow_html=True,
                )

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 33.0", key=f"btn_salvar_33_0_{ano_sel}", type="primary"):
                    val_str_330 = sel_33_0
                    val_lk_330 = link_33_0_input.strip()
                    comentarios_330 = d33_0.get("comentarios", [])

                    save_resp_isaude(
                        qid="33.0",
                        valor=val_str_330,
                        pontos=pts_33_0,
                        link=val_lk_330,
                        comentarios=comentarios_330
                    )

                    # Modal de aviso para links novos/alterados
                    links_atuais_330 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_33_0_input or "")]
                    links_antigos_330 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_330 or "")]

                    if (val_str_330 != d33_0.get("valor", "") or val_lk_330 != l_salvo_330) and links_atuais_330 and links_atuais_330 != links_antigos_330:
                        st.session_state[f"links_pendentes_33_0_{ano_sel}"] = links_atuais_330
                        st.session_state[f"gatilho_modal_33_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 33.0 salvos com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 33.0
        if st.session_state.get(f"gatilho_modal_33_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("33.0", st.session_state.get(f"links_pendentes_33_0_{ano_sel}", []), ano_sel)

        # -----------------------------------------------------------------------------
        # QUESITO 33.1 - CARACTERÍSTICAS DA OUVIDORIA
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_caracteristicas_ouvidoria_33_1_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 33.1 • Características da Ouvidoria da Saúde ({ano_sel})", expanded=True):
                st.subheader(f"33.1 • Características da Ouvidoria da Saúde ({ano_sel})")
                st.write("**33.1 Assinale as características da Ouvidoria da Saúde:**")
                st.caption("ℹ️ *Marque as opções aplicáveis, informe o link de comprovação e clique no botão 'Salvar Quesito 33.1' para registrar as alterações.*")

                d33_1 = res_data.get("33.1") or {
                    "valor": "",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_331 = d33_1.get("valor", "").split("|")
                l_salvo_331 = d33_1.get("link", "")

                ouvidoria_specs = {
                    "ato_formal": {"text": "Instituída por ato formal no organograma da secretaria de saúde ou equivalente – 03", "pts": 3.0},
                    "estrutura_fisica": {"text": "Possui estrutura física – 02", "pts": 2.0},
                    "equipe_designada": {"text": "Possui equipe ou profissional designado – 05", "pts": 5.0},
                    "outros": {"text": "Outros – 00", "pts": 0.0}
                }

                c331_1, c331_2 = st.columns([1, 1])
                chks_selecionados_331 = []
                pts_totais_33_1 = 0.0

                keys_ouvidoria = list(ouvidoria_specs.keys())
                metade_ouvidoria = (len(keys_ouvidoria) + 1) // 2

                with c331_1:
                    for k in keys_ouvidoria[:metade_ouvidoria]:
                        marcado = st.checkbox(ouvidoria_specs[k]["text"], value=k in v_salvo_331, key=f"chk_33_1_{k}_{ano_sel}")
                        if marcado:
                            chks_selecionados_331.append(k)
                            pts_totais_33_1 += ouvidoria_specs[k]["pts"]

                with c331_2:
                    for k in keys_ouvidoria[metade_ouvidoria:]:
                        marcado = st.checkbox(ouvidoria_specs[k]["text"], value=k in v_salvo_331, key=f"chk_33_1_{k}_{ano_sel}")
                        if marcado:
                            chks_selecionados_331.append(k)
                            pts_totais_33_1 += ouvidoria_specs[k]["pts"]

                link_33_1_input = st.text_area(
                    "Link/Evidência das Características da Ouvidoria (33.1):",
                    value=l_salvo_331,
                    key=f"txt_link_33_1_{ano_sel}",
                    height=140
                )

                placeholder_links_331 = st.empty()
                links_331_visuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_33_1_input or "")]
                if links_331_visuais:
                    placeholder_links_331.markdown(
                        "**🔗 Links ativos:** "
                        + " | ".join([f"[{u}]({u})" for u in links_331_visuais])
                    )

                # Chat de comentários
                bloco_comentarios_isaude("33.1", res_data)

                # Impacto de pontuação
                st.markdown(
                    f"<span style='color:#6c757d; font-weight:bold;'>"
                    f"📊 Pontuação Aplicada no Quesito 33.1: +{pts_totais_33_1:.1f} pontos</span>",
                    unsafe_allow_html=True,
                )

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 33.1", key=f"btn_salvar_33_1_{ano_sel}", type="primary"):
                    val_str_331 = "|".join(chks_selecionados_331)
                    val_lk_331 = link_33_1_input.strip()
                    comentarios_331 = d33_1.get("comentarios", [])

                    save_resp_isaude(
                        qid="33.1",
                        valor=val_str_331,
                        pontos=pts_totais_33_1,
                        link=val_lk_331,
                        comentarios=comentarios_331
                    )

                    # Modal de aviso para links novos/alterados
                    links_atuais_331 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_33_1_input or "")]
                    links_antigos_331 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_331 or "")]

                    if (val_str_331 != d33_1.get("valor", "") or val_lk_331 != l_salvo_331) and links_atuais_331 and links_atuais_331 != links_antigos_331:
                        st.session_state[f"links_pendentes_33_1_{ano_sel}"] = links_atuais_331
                        st.session_state[f"gatilho_modal_33_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 33.1 salvos com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 33.1
        if st.session_state.get(f"gatilho_modal_33_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("33.1", st.session_state.get(f"links_pendentes_33_1_{ano_sel}", []), ano_sel)

        # =============================================================================
        # SEÇÃO 34 - UTILIZAÇÃO DO SISTEMA OUVIDORSUS
        # =============================================================================
        # -----------------------------------------------------------------------------
        # QUESITO 34.0 - USO DO SISTEMA OUVIDORSUS OU EQUIVALENTE
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_ouvidorsus_34_0_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 34.0 • Uso do Sistema OuvidorSUS ou Equivalente ({ano_sel})", expanded=True):
                st.subheader(f"34.0 • Uso do Sistema OuvidorSUS ou Equivalente ({ano_sel})")
                st.write("**34.0 O município utiliza o Sistema OuvidorSUS ou sistema equivalente que, além de permitir a disseminação de informações, o registro e o encaminhamento das manifestações dos cidadãos, possibilita troca de informações entre os órgãos responsáveis pela gestão do SUS?**")
                st.caption("ℹ️ *Selecione uma opção, informe o link de comprovação e clique no botão 'Salvar Quesito 34.0' para registrar as alterações.*")

                opts_34_0 = ["Selecione...", "Sim – 05", "Não – 00"]

                d34_0 = res_data.get("34.0") or {
                    "valor": "Selecione...",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_340 = d34_0.get("valor", "Selecione...")
                idx_34_0 = opts_34_0.index(v_salvo_340) if v_salvo_340 in opts_34_0 else 0
                l_salvo_340 = d34_0.get("link", "")

                c340_1, c340_2 = st.columns([1, 1])
                with c340_1:
                    sel_34_0 = st.radio(
                        "Utilização do OuvidorSUS:",
                        options=opts_34_0,
                        index=idx_34_0,
                        key=f"rad_34_0_{ano_sel}",
                        label_visibility="collapsed"
                    )

                with c340_2:
                    link_34_0_input = st.text_area(
                        "Link/Evidência do OuvidorSUS (34.0):",
                        value=l_salvo_340,
                        key=f"txt_link_34_0_{ano_sel}",
                        height=140
                    )

                placeholder_links_340 = st.empty()
                links_340_visuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_34_0_input or "")]
                if links_340_visuais:
                    placeholder_links_340.markdown(
                        "**🔗 Links ativos:** "
                        + " | ".join([f"[{u}]({u})" for u in links_340_visuais])
                    )

                # Feedback visual e Pontuação
                opcoes_pts_340 = {
                    "Sim – 05": 5.0,
                    "Não – 00": 0.0,
                    "Selecione...": 0.0
                }
                pts_34_0 = opcoes_pts_340.get(sel_34_0, 0.0)

                if sel_34_0 == "Selecione...":
                    st.warning("⚠️ **Atenção:** Nenhuma opção selecionada.")
                else:
                    st.success(f"✅ Opção selecionada: **{sel_34_0}**")

                # Chat de comentários corrigido (bloco_comentarios_isaude)
                bloco_comentarios_isaude("34.0", res_data)

                # Impacto de pontuação
                st.markdown(
                    f"<span style='color:#6c757d; font-weight:bold;'>"
                    f"📊 Pontuação Aplicada no Quesito 34.0: +{pts_34_0:.1f} pontos</span>",
                    unsafe_allow_html=True,
                )

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 34.0", key=f"btn_salvar_34_0_{ano_sel}", type="primary"):
                    val_str_340 = sel_34_0
                    val_lk_340 = link_34_0_input.strip()
                    comentarios_340 = d34_0.get("comentarios", [])

                    save_resp_isaude(
                        qid="34.0",
                        valor=val_str_340,
                        pontos=pts_34_0,
                        link=val_lk_340,
                        comentarios=comentarios_340
                    )

                    # Modal de aviso para links novos/alterados
                    links_atuais_340 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_34_0_input or "")]
                    links_antigos_340 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_340 or "")]

                    if (val_str_340 != d34_0.get("valor", "") or val_lk_340 != l_salvo_340) and links_atuais_340 and links_atuais_340 != links_antigos_340:
                        st.session_state[f"links_pendentes_34_0_{ano_sel}"] = links_atuais_340
                        st.session_state[f"gatilho_modal_34_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 34.0 salvos com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 34.0
        if st.session_state.get(f"gatilho_modal_34_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("34.0", st.session_state.get(f"links_pendentes_34_0_{ano_sel}", []), ano_sel)


        # =============================================================================
        # SEÇÃO 35 - SISTEMA NACIONAL DE AUDITORIA (SNA)
        # =============================================================================
        # -----------------------------------------------------------------------------
        # QUESITO 35.0 - POSSUI COMPONENTE SNA
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_sna_35_0_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 35.0 • Existência do Componente Municipal do SNA ({ano_sel})", expanded=True):
                st.subheader(f"35.0 • Existência do Componente Municipal do SNA ({ano_sel})")
                st.write("**35.0 O município possui o componente municipal do Sistema Nacional de Auditoria?**")
                st.caption("ℹ️ *Selecione uma opção, informe o link de comprovação e clique no botão 'Salvar Quesito 35.0' para registrar as alterações.*")

                opts_35_0 = ["Selecione...", "Sim", "Não"]

                d35_0 = res_data.get("35.0") or {
                    "valor": "Selecione...",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_350 = d35_0.get("valor", "Selecione...")
                idx_35_0 = opts_35_0.index(v_salvo_350) if v_salvo_350 in opts_35_0 else 0
                l_salvo_350 = d35_0.get("link", "")

                c350_1, c350_2 = st.columns([1, 1])
                with c350_1:
                    sel_35_0 = st.radio(
                        "Componente SNA:",
                        options=opts_35_0,
                        index=idx_35_0,
                        key=f"rad_35_0_{ano_sel}",
                        label_visibility="collapsed"
                    )

                with c350_2:
                    link_35_0_input = st.text_area(
                        "Link/Evidência do SNA (35.0):",
                        value=l_salvo_350,
                        key=f"txt_link_35_0_{ano_sel}",
                        height=140
                    )

                placeholder_links_350 = st.empty()
                links_350_visuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_35_0_input or "")]
                if links_350_visuais:
                    placeholder_links_350.markdown(
                        "**🔗 Links ativos:** "
                        + " | ".join([f"[{u}]({u})" for u in links_350_visuais])
                    )

                # Feedback visual e Pontuação Informativa
                pts_35_0 = 0.0
                if sel_35_0 == "Selecione...":
                    st.warning("⚠️ **Atenção:** Nenhuma opção selecionada.")
                else:
                    st.success(f"✅ Opção selecionada: **{sel_35_0}**")

                # Chat de comentários
                bloco_comentarios_isaude("35.0", res_data)

                # Impacto de pontuação
                st.markdown(
                    f"<span style='color:#6c757d; font-weight:bold;'>"
                    f"📊 Pontuação Aplicada no Quesito 35.0: +{pts_35_0:.1f} pontos (Dados Informativos)</span>",
                    unsafe_allow_html=True,
                )

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 35.0", key=f"btn_salvar_35_0_{ano_sel}", type="primary"):
                    val_str_350 = sel_35_0
                    val_lk_350 = link_35_0_input.strip()
                    comentarios_350 = d35_0.get("comentarios", [])

                    save_resp_isaude(
                        qid="35.0",
                        valor=val_str_350,
                        pontos=pts_35_0,
                        link=val_lk_350,
                        comentarios=comentarios_350
                    )

                    # Modal de aviso para links novos/alterados
                    links_atuais_350 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_35_0_input or "")]
                    links_antigos_350 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_350 or "")]

                    if (val_str_350 != d35_0.get("valor", "") or val_lk_350 != l_salvo_350) and links_atuais_350 and links_atuais_350 != links_antigos_350:
                        st.session_state[f"links_pendentes_35_0_{ano_sel}"] = links_atuais_350
                        st.session_state[f"gatilho_modal_35_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 35.0 salvos com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 35.0
        if st.session_state.get(f"gatilho_modal_35_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("35.0", st.session_state.get(f"links_pendentes_35_0_{ano_sel}", []), ano_sel)


        # -----------------------------------------------------------------------------
        # QUESITO 35.1 - CARACTERÍSTICAS DO SNA
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_caracteristicas_sna_35_1_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 35.1 • Características do Componente SNA ({ano_sel})", expanded=True):
                st.subheader(f"35.1 • Características do Componente SNA ({ano_sel})")
                st.write("**35.1 Assinale as características do componente municipal do Sistema Nacional de Auditoria - SNA:**")
                st.caption("ℹ️ *Marque as caixas correspondentes, informe o link de comprovação e clique no botão 'Salvar Quesito 35.1' para registrar as alterações.*")

                d35_1 = res_data.get("35.1") or {
                    "valor": "",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_351 = d35_1.get("valor", "").split("|")
                l_salvo_351 = d35_1.get("link", "")

                sna_specs = {
                    "ato_formal": {"text": "Instituída por ato formal no organograma da secretaria de saúde ou equivalente – 03", "pts": 3.0},
                    "estrutura_fisica": {"text": "Possui estrutura física – 02", "pts": 2.0},
                    "equipe_med_enf": {"text": "Possui equipe com ao menos um médico e um enfermeiro – 10", "pts": 10.0},
                    "outros": {"text": "Outros – 00", "pts": 0.0}
                }

                c351_1, c351_2 = st.columns([1, 1])
                chks_selecionados_351 = []
                pts_totais_35_1 = 0.0

                keys_sna = list(sna_specs.keys())
                metade_sna = (len(keys_sna) + 1) // 2

                with c351_1:
                    for k in keys_sna[:metade_sna]:
                        marcado = st.checkbox(sna_specs[k]["text"], value=k in v_salvo_351, key=f"chk_35_1_{k}_{ano_sel}")
                        if marcado:
                            chks_selecionados_351.append(k)
                            pts_totais_35_1 += sna_specs[k]["pts"]

                with c351_2:
                    for k in keys_sna[metade_sna:]:
                        marcado = st.checkbox(sna_specs[k]["text"], value=k in v_salvo_351, key=f"chk_35_1_{k}_{ano_sel}")
                        if marcado:
                            chks_selecionados_351.append(k)
                            pts_totais_35_1 += sna_specs[k]["pts"]

                    link_35_1_input = st.text_area(
                        "Link/Evidência das Características do SNA (35.1):",
                        value=l_salvo_351,
                        key=f"txt_link_35_1_{ano_sel}",
                        height=140
                    )

                placeholder_links_351 = st.empty()
                links_351_visuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_35_1_input or "")]
                if links_351_visuais:
                    placeholder_links_351.markdown(
                        "**🔗 Links ativos:** "
                        + " | ".join([f"[{u}]({u})" for u in links_351_visuais])
                    )

                # Feedback visual
                if chks_selecionados_351:
                    st.success(f"✅ Opções selecionadas: **{len(chks_selecionados_351)} item(ns)**")
                else:
                    st.warning("⚠️ **Atenção:** Nenhuma opção selecionada.")

                # Chat de comentários
                bloco_comentarios_isaude("35.1", res_data)

                # Impacto de pontuação
                st.markdown(
                    f"<span style='color:#6c757d; font-weight:bold;'>"
                    f"📊 Pontuação Aplicada no Quesito 35.1: +{pts_totais_35_1:.1f} pontos</span>",
                    unsafe_allow_html=True,
                )

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 35.1", key=f"btn_salvar_35_1_{ano_sel}", type="primary"):
                    val_str_351 = "|".join(chks_selecionados_351)
                    val_lk_351 = link_35_1_input.strip()
                    comentarios_351 = d35_1.get("comentarios", [])

                    save_resp_isaude(
                        qid="35.1",
                        valor=val_str_351,
                        pontos=pts_totais_35_1,
                        link=val_lk_351,
                        comentarios=comentarios_351
                    )

                    # Modal de aviso para links novos/alterados
                    links_atuais_351 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_35_1_input or "")]
                    links_antigos_351 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_351 or "")]

                    if (val_str_351 != d35_1.get("valor", "") or val_lk_351 != l_salvo_351) and links_atuais_351 and links_atuais_351 != links_antigos_351:
                        st.session_state[f"links_pendentes_35_1_{ano_sel}"] = links_atuais_351
                        st.session_state[f"gatilho_modal_35_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 35.1 salvos com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 35.1
        if st.session_state.get(f"gatilho_modal_35_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("35.1", st.session_state.get(f"links_pendentes_35_1_{ano_sel}", []), ano_sel)

                # -----------------------------------------------------------------------------
        # QUESITO 35.2 - AUDITORIAS CONCLUÍDAS SITE
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_auditorias_site_35_2_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 35.2 • Disponibilização das Auditorias em Site ({ano_sel})", expanded=True):
                st.subheader(f"35.2 • Disponibilização das Auditorias em Site ({ano_sel})")
                st.write(f"**35.2 As auditorias concluídas (encerradas) do exercício de {ano_sel} pelo componente municipal do Sistema Nacional de Auditoria do SUS - SNA estão disponibilizadas em site para consulta?**")
                st.caption("ℹ️ *Selecione uma opção, informe o link de comprovação e clique no botão 'Salvar Quesito 35.2' para registrar as alterações.*")

                opts_35_2 = ["Selecione...", "Sim – 10", "Não – 00"]

                d35_2 = res_data.get("35.2") or {
                    "valor": "Selecione...",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_352 = d35_2.get("valor", "Selecione...")
                idx_35_2 = opts_35_2.index(v_salvo_352) if v_salvo_352 in opts_35_2 else 0
                l_salvo_352 = d35_2.get("link", "")

                c352_1, c352_2 = st.columns([1, 1])
                with c352_1:
                    sel_35_2 = st.radio(
                        "Disponibilização em site:",
                        options=opts_35_2,
                        index=idx_35_2,
                        key=f"rad_35_2_{ano_sel}",
                        label_visibility="collapsed"
                    )

                with c352_2:
                    link_35_2_input = st.text_area(
                        "Link/Evidência (35.2):",
                        value=l_salvo_352,
                        key=f"txt_link_35_2_{ano_sel}",
                        height=140
                    )

                placeholder_links_352 = st.empty()
                links_352_visuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_35_2_input or "")]
                if links_352_visuais:
                    placeholder_links_352.markdown(
                        "**🔗 Links ativos:** "
                        + " | ".join([f"[{u}]({u})" for u in links_352_visuais])
                    )

                # Feedback visual e Pontuação
                opcoes_pts_352 = {
                    "Sim – 10": 10.0,
                    "Não – 00": 0.0,
                    "Selecione...": 0.0
                }
                pts_35_2 = opcoes_pts_352.get(sel_35_2, 0.0)

                if sel_35_2 == "Selecione...":
                    st.warning("⚠️ **Atenção:** Nenhuma opção selecionada.")
                else:
                    st.success(f"✅ Opção selecionada: **{sel_35_2}**")

                # Chat de comentários do iSaúde
                bloco_comentarios_isaude("35.2", res_data)

                # Impacto de pontuação
                st.markdown(
                    f"<span style='color:#6c757d; font-weight:bold;'>"
                    f"📊 Pontuação Aplicada no Quesito 35.2: +{pts_35_2:.1f} pontos</span>",
                    unsafe_allow_html=True,
                )

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 35.2", key=f"btn_salvar_35_2_{ano_sel}", type="primary"):
                    val_str_352 = sel_35_2
                    val_lk_352 = link_35_2_input.strip()
                    comentarios_352 = d35_2.get("comentarios", [])

                    save_resp_isaude(
                        qid="35.2",
                        valor=val_str_352,
                        pontos=pts_35_2,
                        link=val_lk_352,
                        comentarios=comentarios_352
                    )

                    # Modal de aviso para links novos/alterados
                    links_atuais_352 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_35_2_input or "")]
                    links_antigos_352 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_352 or "")]

                    if (val_str_352 != d35_2.get("valor", "") or val_lk_352 != l_salvo_352) and links_atuais_352 and links_atuais_352 != links_antigos_352:
                        st.session_state[f"links_pendentes_35_2_{ano_sel}"] = links_atuais_352
                        st.session_state[f"gatilho_modal_35_2_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 35.2 salvos com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 35.2
        if st.session_state.get(f"gatilho_modal_35_2_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("35.2", st.session_state.get(f"links_pendentes_35_2_{ano_sel}", []), ano_sel)


        # -----------------------------------------------------------------------------
        # QUESITO 35.2.1 - LINK DO SITE
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_url_auditorias_35_2_1_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 35.2.1 • Página Eletrônica de Divulgação ({ano_sel})", expanded=True):
                st.subheader(f"35.2.1 • Página Eletrônica de Divulgação ({ano_sel})")
                st.write(f"**35.2.1 Informe a página eletrônica (site) de divulgação dos resultados das auditorias concluídas (encerradas) em {ano_sel}:**")
                st.caption("ℹ️ *Preencha o campo com a URL informada, adicione os links/evidências e clique no botão 'Salvar Quesito 35.2.1' para gravar.*")

                d35_2_1 = res_data.get("35.2.1") or {
                    "valor": "",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_3521 = d35_2_1.get("valor", "")
                l_salvo_3521 = d35_2_1.get("link", "")

                c3521_1, c3521_2 = st.columns([1, 1])
                with c3521_1:
                    url_informada = st.text_input(
                        "Informe a URL:",
                        value=v_salvo_3521,
                        placeholder="https://...",
                        key=f"txt_val_3521_{ano_sel}"
                    )

                    placeholder_url_preview = st.empty()
                    if url_informada.strip().startswith(("http://", "https://")):
                        placeholder_url_preview.markdown(f"🌐 **Página Indicada:** [{url_informada.strip()}]({url_informada.strip()})")

                with c3521_2:
                    link_35_2_1_input = st.text_area(
                        "Link/Evidência (35.2.1):",
                        value=l_salvo_3521,
                        key=f"txt_link_35_2_1_{ano_sel}",
                        height=140
                    )

                placeholder_links_3521 = st.empty()
                links_3521_visuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_35_2_1_input or "")]
                if links_3521_visuais:
                    placeholder_links_3521.markdown(
                        "**🔗 Links ativos:** "
                        + " | ".join([f"[{u}]({u})" for u in links_3521_visuais])
                    )

                # Feedback visual e Pontuação Informativa
                pts_35_2_1 = 0.0
                if not url_informada.strip():
                    st.warning("⚠️ **Atenção:** Aguardando preenchimento da URL.")
                else:
                    st.success("✅ Página eletrônica informada.")

                # Chat de comentários do iSaúde
                bloco_comentarios_isaude("35.2.1", res_data)

                # Impacto de pontuação
                st.markdown(
                    f"<span style='color:#6c757d; font-weight:bold;'>"
                    f"📊 Pontuação Aplicada no Quesito 35.2.1: +{pts_35_2_1:.1f} pontos (Dados Informativos)</span>",
                    unsafe_allow_html=True,
                )

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 35.2.1", key=f"btn_salvar_35_2_1_{ano_sel}", type="primary"):
                    val_str_3521 = url_informada.strip()
                    val_lk_3521 = link_35_2_1_input.strip()
                    comentarios_3521 = d35_2_1.get("comentarios", [])

                    save_resp_isaude(
                        qid="35.2.1",
                        valor=val_str_3521,
                        pontos=pts_35_2_1,
                        link=val_lk_3521,
                        comentarios=comentarios_3521
                    )

                    # Modal de aviso para links novos/alterados
                    links_atuais_3521 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_35_2_1_input or "")]
                    links_antigos_3521 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_3521 or "")]

                    if (val_str_3521 != d35_2_1.get("valor", "") or val_lk_3521 != l_salvo_3521) and links_atuais_3521 and links_atuais_3521 != links_antigos_3521:
                        st.session_state[f"links_pendentes_35_2_1_{ano_sel}"] = links_atuais_3521
                        st.session_state[f"gatilho_modal_35_2_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 35.2.1 salvos com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 35.2.1
        if st.session_state.get(f"gatilho_modal_35_2_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("35.2.1", st.session_state.get(f"links_pendentes_35_2_1_{ano_sel}", []), ano_sel)

        # =============================================================================
        # SEÇÃO 36 - SISTEMA DE GESTÃO DE ESTOQUE DE MEDICAMENTOS
        # =============================================================================

        # -----------------------------------------------------------------------------
        # QUESITO 36.0 - SISTEMA INFORMATIZADO PARA GERENCIAMENTO DE MEDICAMENTOS
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_estoque_medicamentos_36_0_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 36.0 • Sistema Informatizado para Gerenciamento de Medicamentos ({ano_sel})", expanded=True):
                st.subheader(f"36.0 • Sistema Informatizado para Gerenciamento de Medicamentos ({ano_sel})")
                st.write("**36.0 O município utiliza sistema informatizado para gerenciar o estoque de itens de medicamentos?**")
                st.caption("ℹ️ *Selecione uma opção, informe o link de comprovação e clique no botão 'Salvar Quesito 36.0' para registrar as alterações.*")

                opts_36_0 = [
                    "Selecione...",
                    "Sim, utiliza o Sistema Hórus – 40",
                    "Sim, utiliza Sistema Próprio – 00",
                    "Não – 00"
                ]

                d36_0 = res_data.get("36.0") or {
                    "valor": "Selecione...",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_360 = d36_0.get("valor", "Selecione...")
                idx_36_0 = opts_36_0.index(v_salvo_360) if v_salvo_360 in opts_36_0 else 0
                l_salvo_360 = d36_0.get("link", "")

                c360_1, c360_2 = st.columns([1, 1])
                with c360_1:
                    sel_36_0 = st.radio(
                        "Gerenciamento de medicamentos:",
                        options=opts_36_0,
                        index=idx_36_0,
                        key=f"rad_36_0_{ano_sel}",
                        label_visibility="collapsed"
                    )

                with c360_2:
                    link_36_0_input = st.text_area(
                        "Link/Evidência (36.0):",
                        value=l_salvo_360,
                        key=f"txt_link_36_0_{ano_sel}",
                        height=140
                    )

                placeholder_links_360 = st.empty()
                links_360_visuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_36_0_input or "")]
                if links_360_visuais:
                    placeholder_links_360.markdown(
                        "**🔗 Links ativos:** "
                        + " | ".join([f"[{u}]({u})" for u in links_360_visuais])
                    )

                # Regra de pontuação para o quesito 36.0
                opcoes_pts_360 = {
                    "Sim, utiliza o Sistema Hórus – 40": 40.0,
                    "Sim, utiliza Sistema Próprio – 00": 0.0,
                    "Não – 00": 0.0,
                    "Selecione...": 0.0
                }
                pts_36_0 = opcoes_pts_360.get(sel_36_0, 0.0)

                # Feedback visual e Pontuação
                if sel_36_0 == "Selecione...":
                    st.warning("⚠️ **Atenção:** Nenhuma opção selecionada.")
                else:
                    st.success(f"✅ Opção selecionada: **{sel_36_0}**")

                # Chat de comentários
                bloco_comentarios_isaude("36.0", res_data)

                # Impacto de pontuação
                st.markdown(
                    f"<span style='color:#6c757d; font-weight:bold;'>"
                    f"📊 Pontuação Aplicada no Quesito 36.0: +{pts_36_0:.1f} pontos</span>",
                    unsafe_allow_html=True,
                )

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 36.0", key=f"btn_salvar_36_0_{ano_sel}", type="primary"):
                    val_str_360 = sel_36_0
                    val_lk_360 = link_36_0_input.strip()
                    comentarios_360 = d36_0.get("comentarios", [])

                    save_resp_isaude(
                        qid="36.0",
                        valor=val_str_360,
                        pontos=pts_36_0,
                        link=val_lk_360,
                        comentarios=comentarios_360
                    )

                    # Modal de aviso para links novos/alterados
                    links_atuais_360 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_36_0_input or "")]
                    links_antigos_360 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_360 or "")]

                    if (val_str_360 != d36_0.get("valor", "") or val_lk_360 != l_salvo_360) and links_atuais_360 and links_atuais_360 != links_antigos_360:
                        st.session_state[f"links_pendentes_36_0_{ano_sel}"] = links_atuais_360
                        st.session_state[f"gatilho_modal_36_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 36.0 salvos com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 36.0
        if st.session_state.get(f"gatilho_modal_36_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("36.0", st.session_state.get(f"links_pendentes_36_0_{ano_sel}", []), ano_sel)


        # -----------------------------------------------------------------------------
        # QUESITO 36.1 - FUNÇÕES DO SISTEMA PRÓPRIO DE MEDICAMENTOS
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_funcoes_sistema_proprio_36_1_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 36.1 • Funções do Sistema Próprio de Gestão de Estoque ({ano_sel})", expanded=True):
                st.subheader(f"36.1 • Funções do Sistema Próprio de Gestão de Estoque ({ano_sel})")
                st.write("**36.1 Assinale as funções existentes no sistema próprio de gestão de estoque de medicamentos:**")
                st.caption("ℹ️ *Marque as caixas correspondentes, informe o link de comprovação e clique no botão 'Salvar Quesito 36.1' para registrar.*")

                d36_1 = res_data.get("36.1") or {
                    "valor": "",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                v_salvo_361 = d36_1.get("valor", "").split("|") if d36_1.get("valor") else []
                l_salvo_361 = d36_1.get("link", "")

                med_specs = {
                    "posicao_lote": {"text": "Fornecer a posição de estoque, movimentação de entrada e saída, lote e validade – 10", "pts": 10.0},
                    "rastreabilidade": {"text": "Permitir a rastreabilidade dos medicamentos dispensados aos pacientes – 10", "pts": 10.0},
                    "processo_compras": {"text": "Gerenciar o processo de compras de itens de medicamentos, desde o planejamento até a entrega e o recebimento da nota fiscal – 10", "pts": 10.0},
                    "reposicao_estab": {"text": "Gerenciar a reposição de itens de medicamentos por estabelecimento de saúde – 10", "pts": 10.0},
                    "integrado_bnafar": {"text": "Integrado à Base Nacional de Dados de Ações e Serviços da Assistência Farmacêutica (BNAFAR) – 00", "pts": 0.0},
                    "outros": {"text": "Outros – 00", "pts": 0.0}
                }

                c361_1, c361_2 = st.columns([1, 1])
                chks_selecionados_361 = []
                pts_totais_36_1 = 0.0

                keys_med = list(med_specs.keys())
                metade_med = (len(keys_med) + 1) // 2

                with c361_1:
                    for k in keys_med[:metade_med]:
                        marcado = st.checkbox(med_specs[k]["text"], value=k in v_salvo_361, key=f"chk_36_1_{k}_{ano_sel}")
                        if marcado:
                            chks_selecionados_361.append(k)
                            pts_totais_36_1 += med_specs[k]["pts"]

                with c361_2:
                    for k in keys_med[metade_med:]:
                        marcado = st.checkbox(med_specs[k]["text"], value=k in v_salvo_361, key=f"chk_36_1_{k}_{ano_sel}")
                        if marcado:
                            chks_selecionados_361.append(k)
                            pts_totais_36_1 += med_specs[k]["pts"]

                    link_36_1_input = st.text_area(
                        "Link/Evidência (36.1):",
                        value=l_salvo_361,
                        key=f"txt_link_36_1_{ano_sel}",
                        height=140
                    )

                placeholder_links_361 = st.empty()
                links_361_visuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_36_1_input or "")]
                if links_361_visuais:
                    placeholder_links_361.markdown(
                        "**🔗 Links ativos:** "
                        + " | ".join([f"[{u}]({u})" for u in links_361_visuais])
                    )

                # Feedback visual de opções selecionadas
                if not chks_selecionados_361:
                    st.warning("⚠️ **Atenção:** Nenhuma função do sistema foi selecionada.")
                else:
                    st.success(f"✅ **{len(chks_selecionados_361)}** função(ões) selecionada(s).")

                # Chat de comentários
                bloco_comentarios_isaude("36.1", res_data)

                # Impacto de pontuação
                st.markdown(
                    f"<span style='color:#6c757d; font-weight:bold;'>"
                    f"📊 Pontuação Aplicada no Quesito 36.1: +{pts_totais_36_1:.1f} pontos</span>",
                    unsafe_allow_html=True,
                )

                # Botão de salvamento dedicado
                if st.button("💾 Salvar Quesito 36.1", key=f"btn_salvar_36_1_{ano_sel}", type="primary"):
                    val_str_361 = "|".join(chks_selecionados_361)
                    val_lk_361 = link_36_1_input.strip()
                    comentarios_361 = d36_1.get("comentarios", [])

                    save_resp_isaude(
                        qid="36.1",
                        valor=val_str_361,
                        pontos=pts_totais_36_1,
                        link=val_lk_361,
                        comentarios=comentarios_361
                    )

                    # Modal de aviso para links novos/alterados
                    links_atuais_361 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, link_36_1_input or "")]
                    links_antigos_361 = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, l_salvo_361 or "")]

                    if (val_str_361 != d36_1.get("valor", "") or val_lk_361 != l_salvo_361) and links_atuais_361 and links_atuais_361 != links_antigos_361:
                        st.session_state[f"links_pendentes_36_1_{ano_sel}"] = links_atuais_361
                        st.session_state[f"gatilho_modal_36_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 36.1 salvos com sucesso!", icon="✅")
                    st.rerun()

        # GATILHO DO MODAL 36.1
        if st.session_state.get(f"gatilho_modal_36_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("36.1", st.session_state.get(f"links_pendentes_36_1_{ano_sel}", []), ano_sel)

        # =============================================================================
        # QUESITO 37.0 • DESABASTECIMENTO DE MEDICAMENTOS (MODELO PADRONIZADO iGov / iSaúde)
        # =============================================================================
        
        with st.container(key=f"container_bloco_isaude_37_0_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 37.0 - Monitoramento de Desabastecimento em {ano_sel}", expanded=True):
                st.subheader("37.0 • Monitoramento de Desabastecimento")
                st.write(
                    f"**Informe os dados de desabastecimento de medicamentos do Componente Básico da Assistência Farmacêutica presentes na REMUME no exercício de {ano_sel}:**"
                )
                
                # Exibição formal da fórmula matemática do indicador
                st.latex(r"Pd = \left( \frac{MD}{TM} \right) \times 100")
                st.caption("ℹ *Preencha os números, insira o link e clique no botão 'Salvar Quesito 37.0' para registrar.*")

                # Estado inicial / persistente
                d37_0 = res_data.get("37.0") or {
                    "valor": "0|0",
                    "pontos": 0.0,
                    "link": "",
                    "comentarios": [],
                    "comentario": ""
                }
                
                v_salvo_37_0 = d37_0.get("valor", "0|0").split("|")
                while len(v_salvo_37_0) < 2:
                    v_salvo_37_0.append("0")

                val_md_salvo = int(v_salvo_37_0[0]) if v_salvo_37_0[0].isdigit() else 0
                val_tm_salvo = int(v_salvo_37_0[1]) if v_salvo_37_0[1].isdigit() else 1
                evidencia_37_0_salva = d37_0.get("link", "")

                # Chaves fixas por componente e ano
                chave_md_37_0 = f"num_370_md_{ano_sel}"
                chave_tm_37_0 = f"num_370_tm_{ano_sel}"
                chave_link_37_0 = f"l_37_0_txt_{ano_sel}"

                c370_1, c370_2 = st.columns([1, 1])
                with c370_1:
                    val_md = st.number_input(
                        f"Nº de itens com desabastecimento superior a 1 mês em {ano_sel} (MD):",
                        min_value=0,
                        value=val_md_salvo,
                        key=chave_md_37_0
                    )
                    val_tm = st.number_input(
                        "Total de itens do Componente Básico presentes na REMUME (TM):",
                        min_value=1,
                        value=val_tm_salvo if val_tm_salvo > 0 else 1,
                        key=chave_tm_37_0
                    )

                with c370_2:
                    link_37_0 = st.text_area(
                        "Link/Evidência (Ata, relatório ou documento oficial da REMUME/CBAF):",
                        value=evidencia_37_0_salva,
                        key=chave_link_37_0,
                        placeholder="Insira o link oficial referente ao quesito 37.0...",
                        height=110,
                    )
                    placeholder_links_37_0 = st.empty()
                    links_37_0_visuais = re.findall(REGEX_PURE_URL, link_37_0 or "")
                    if links_37_0_visuais:
                        placeholder_links_37_0.markdown(
                            "**🔗 Link ativo:** "
                            + " | ".join(
                                [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_37_0_visuais]
                            )
                        )

                # Cálculo prévio reativo da regra de negócio para preview
                pts_37_0_calc = 0.0
                if val_tm > 0:
                    pd = (val_md / val_tm) * 100.0
                    st.markdown(f"📊 **Percentual de Desabastecimento Calculado (Pd):** `{pd:.2f}%` ({val_md} de {val_tm} itens)")
                    
                    if val_md == 0:
                        pts_37_0_calc = 90.0
                        st.success(f"🏅 **Excelente!** Pd = 0% | Pontuação esperada: `{pts_37_0_calc:.1f} pontos`")
                    elif pd <= 5.0:
                        pts_37_0_calc = 75.0
                        st.info(f"✅ **Bom Controle:** 0% < Pd <= 5% | Pontuação esperada: `{pts_37_0_calc:.1f} pontos`")
                    elif pd <= 10.0:
                        pts_37_0_calc = 50.0
                        st.warning(f"⚠️ **Atenção:** 5% < Pd <= 10% | Pontuação esperada: `{pts_37_0_calc:.1f} pontos`")
                    elif pd <= 15.0:
                        pts_37_0_calc = 25.0
                        st.warning(f"🧡 **Alerta Laranja:** 10% < Pd <= 15% | Pontuação esperada: `{pts_37_0_calc:.1f} pontos`")
                    else:
                        pts_37_0_calc = 0.0
                        st.error(f"🚨 **Crítico:** Pd > 15% | Pontuação esperada: `{pts_37_0_calc:.1f} pontos`")
                else:
                    st.error("⚠️ O total de itens da REMUME (TM) deve ser maior que zero para possibilitar o cálculo.")

                # Renderização do chat de comentários
                if "bloco_comentarios_isaude" in globals():
                    bloco_comentarios_isaude("37.0", res_data)

                # Botão de salvamento
                if st.button("💾 Salvar Quesito 37.0", key=f"btn_salvar_37_0_{ano_sel}", type="primary"):
                    md_input = st.session_state.get(chave_md_37_0, val_md_salvo)
                    tm_input = st.session_state.get(chave_tm_37_0, val_tm_salvo)
                    
                    # Recálculo oficial no clique de salvar
                    pts_37_0 = 0.0
                    if tm_input > 0:
                        pd_salvar = (md_input / tm_input) * 100.0
                        if md_input == 0:
                            pts_37_0 = 90.0
                        elif pd_salvar <= 5.0:
                            pts_37_0 = 75.0
                        elif pd_salvar <= 10.0:
                            pts_37_0 = 50.0
                        elif pd_salvar <= 15.0:
                            pts_37_0 = 25.0
                        else:
                            pts_37_0 = 0.0

                    val_str_salvar = f"{md_input}|{tm_input}"
                    lnk_val = link_37_0.strip()
                    comentarios_historico = d37_0.get("comentarios", [])

                    if "save_resp_isaude" in globals():
                        save_resp_isaude(
                            qid="37.0",
                            valor=val_str_salvar,
                            pontos=pts_37_0,
                            link=lnk_val,
                            comentarios=comentarios_historico
                        )

                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_37_0_salva or "")]

                    if lnk_val != evidencia_37_0_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_37_0_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_37_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e histórico do Quesito 37.0 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Impacto de pontuação
                pts_atuais_37_0 = d37_0.get("pontos", 0.0)
                cor_txt_37_0 = "#28a745" if pts_atuais_37_0 > 0.0 else "#6c757d"

                st.markdown(
                    f"<span style='color:{cor_txt_37_0}; font-weight:bold;'>"
                    f"📊 Impacto de Pontuação no Quesito 37.0: +{pts_atuais_37_0:.1f} pontos</span>",
                    unsafe_allow_html=True,
                )

        # GATILHO DO MODAL 37.0 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_37_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("37.0", st.session_state.get(f"links_pendentes_37_0_{ano_sel}", []), ano_sel)

       
