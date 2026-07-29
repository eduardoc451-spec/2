from datetime import date, datetime
from io import BytesIO
import html
import json
import logging
import os
import re
import sys
import warnings

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
def modal_aviso_link(qid, links_encontrados):
    st.warning(f"Detectamos a inclusão de link(s) no campo de evidências da questão **{qid}**.")
    
    for lk in links_encontrados:
        st.markdown(f"🔗 **Endereço:** [{lk}]({lk})")
        
    st.markdown("""
    **Por favor, verifique se este link está configurado para acesso público/compartilhado.**
    
    Se as credenciais estiverem privadas ou exigirem login e senha do seu município, as equipes avaliadoras externas **não conseguirão acessar as provas**, invalidando os pontos desse quesito.
    """)
    if st.button("Confirmo que o link está liberado para o público", key=f"btn_conf_{qid}"):
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
                modal_aviso_link("1.0", st.session_state.get(f"links_pendentes_1_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_1_0_{ano_sel}"] = False
