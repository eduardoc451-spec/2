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
        # QUESITO 17.5.2.1.1 - 3 CONSULTAS COM MAIOR TEMPO DE ESPERA
        # =============================================================================
        # Substituída a div HTML manual por contêiner nativo estável com chave fixa
        with st.container(key=f"container_bloco_maior_espera_consultas_17_5_2_1_1_{ano_sel}", border=True):
            
            with st.expander(f"📌 Quesito 17.5.2.1.1 - Consultas com Maior Tempo de Espera", expanded=True):
                st.subheader("17.5.2.1.1 • Consultas com Maior Tempo de Espera")
                st.write(f"**17.5.2.1.1 Informe as 3 consultas médicas com maior tempo de espera na Atenção Especializada:**")
                st.caption("ℹ️ *O salvamento é automático. Qualquer alteração nos campos ou no link grava os dados na hora.*")
                
                # Recupera os dados salvos ou inicia um dicionário padrão
                d17_5_2_1_1 = res_data.get("17.5.2.1.1", {"valor": "", "pontos": 0.0, "link": ""})
                valores_salvos_1_1 = d17_5_2_1_1.get("valor", "")
                
                # Trata a string salva para preencher os campos (Especialidade 1|Dias 1||Especialidade 2|Dias 2||Especialidade 3|Dias 3)
                partes = valores_salvos_1_1.split("||") if valores_salvos_1_1 else []
                
                p1 = partes[0].split("|") if len(partes) > 0 else ["", ""]
                p2 = partes[1].split("|") if len(partes) > 1 else ["", ""]
                p3 = partes[2].split("|") if len(partes) > 2 else ["", ""]
                
                c175211_1, c175211_2 = st.columns([1, 1])
                
                with c175211_1:
                    st.write("🩺 **Especialidades Médicas e Prazos:**")
                    
                    # Primeira Consulta
                    esp_1 = st.text_input("1ª - Descrição da especialidade médica:", value=p1[0] if len(p1) > 0 else "", key=f"esp1_175211_{ano_sel}")
                    dias_1 = st.text_input("1ª - Tempo médio de espera (em dias):", value=p1[1] if len(p1) > 1 else "", key=f"dias1_175211_{ano_sel}")
                    
                    st.markdown("---")
                    
                    # Segunda Consulta
                    esp_2 = st.text_input("2ª - Descrição da especialidade médica:", value=p2[0] if len(p2) > 0 else "", key=f"esp2_175211_{ano_sel}")
                    dias_2 = st.text_input("2ª - Tempo médio de espera (em dias):", value=p2[1] if len(p2) > 1 else "", key=f"dias2_175211_{ano_sel}")
                    
                    st.markdown("---")
                    
                    # Terceira Consulta
                    esp_3 = st.text_input("3ª - Descrição da especialidade médica:", value=p3[0] if len(p3) > 0 else "", key=f"esp3_175211_{ano_sel}")
                    dias_3 = st.text_input("3ª - Tempo médio de espera (em dias):", value=p3[1] if len(p3) > 1 else "", key=f"dias3_175211_{ano_sel}")

                with c175211_2:
                    link_17_5_2_1_1 = st.text_area(
                        "Link/Evidência ou Relatório estatístico dos tempos de espera (17.5.2.1.1):", 
                        value=d17_5_2_1_1.get("link", ""), 
                        key=f"reg_17_5_2_1_1_txt_{ano_sel}",
                        height=320
                    )
                    
                    # SUPORTE MULTI-LINKS ATIVOS (Isolado e protegido de forma síncrona)
                    with st.container(key=f"links_holder_maior_espera_consultas_17_5_2_1_1_{ano_sel}"):
                        links_17_5_2_1_1_atuais = re.findall(r'(https?://[^\s]+)', link_17_5_2_1_1)
                        if links_17_5_2_1_1_atuais:
                            botoes_17_5_2_1_1 = " | ".join([f"🔗 [{u}]({u})" for u in links_17_5_2_1_1_atuais])
                            st.markdown(f"**Links Ativos:** {botoes_17_5_2_1_1}")
                
                # Monta a string estruturada para salvar tudo em um único campo de texto de forma limpa
                string_estruturada = f"{esp_1}|{dias_1}||{esp_2}|{dias_2}||{esp_3}|{dias_3}"
                # Caso esteja tudo em branco, salva vazio
                if string_estruturada == "||||":
                    string_estruturada = ""
                    
                pts_17_5_2_1_1 = 0.0
                
                # ISOLAMENTO DO SCORE: Protegido por container para manter a integridade da árvore do React
                with st.container(key=f"score_holder_maior_espera_consultas_17_5_2_1_1_{ano_sel}"):
                    st.markdown(f"📊 **Pontuação Aplicada no Quesito 17.5.2.1.1:** `{pts_17_5_2_1_1:.1f} pontos` (Dados Informativos)")
                
                # SALVAMENTO TOTALMENTE SINCRONIZADO NA MEMÓRIA LOCAL
                mudou_valores_17_5_2_1_1 = string_estruturada != valores_salvos_1_1
                mudou_link_17_5_2_1_1 = link_17_5_2_1_1 != d17_5_2_1_1.get("link", "")

                if mudou_valores_17_5_2_1_1 or mudou_link_17_5_2_1_1:
                    save_resp("17.5.2.1.1", string_estruturada, pts_17_5_2_1_1, link_17_5_2_1_1)
                    
                    if "17.5.2.1.1" not in res_data:
                        res_data["17.5.2.1.1"] = {}
                    res_data["17.5.2.1.1"]["valor"] = string_estruturada
                    res_data["17.5.2.1.1"]["pontos"] = pts_17_5_2_1_1
                    res_data["17.5.2.1.1"]["link"] = link_17_5_2_1_1
                    
                    if mudou_link_17_5_2_1_1 and links_17_5_2_1_1_atuais:
                        links_17_5_2_1_1_antigos = re.findall(r'(https?://[^\s]+)', d17_5_2_1_1.get("link", ""))
                        if links_17_5_2_1_1_atuais != links_17_5_2_1_1_antigos:
                            modal_aviso_link("17.5.2.1.1", links_17_5_2_1_1_atuais)
                        else:
                            st.rerun()
                    else:
                        st.rerun()
                    
                bloco_comentarios("17.5.2.1.1", res_data)

        # =============================================================================
        # QUESITO 17.5.2.1.2 - 3 EXAMES COM MAIOR TEMPO DE ESPERA
        # =============================================================================
        with st.container(key=f"container_bloco_maior_espera_exames_17_5_2_1_2_{ano_sel}", border=True):
            
            with st.expander(f"📌 Quesito 17.5.2.1.2 - Exames com Maior Tempo de Espera", expanded=True):
                st.subheader("17.5.2.1.2 • Exames com Maior Tempo de Espera")
                st.write(f"**17.5.2.1.2 Informe os 3 exames médicos com maior tempo de espera na Atenção Especializada:**")
                st.caption("ℹ️ *O salvamento é automático. Qualquer alteração nos campos ou no link grava os dados na hora.*")
                
                # Recupera os dados salvos ou inicia um dicionário padrão
                d17_5_2_1_2 = res_data.get("17.5.2.1.2", {"valor": "", "pontos": 0.0, "link": ""})
                valores_salvos_1_2 = d17_5_2_1_2.get("valor", "")
                
                # Trata a string salva para preencher os campos (Exame 1|Dias 1||Exame 2|Dias 2||Exame 3|Dias 3)
                partes_ex = valores_salvos_1_2.split("||") if valores_salvos_1_2 else []
                
                e1 = partes_ex[0].split("|") if len(partes_ex) > 0 else ["", ""]
                e2 = partes_ex[1].split("|") if len(partes_ex) > 1 else ["", ""]
                e3 = partes_ex[2].split("|") if len(partes_ex) > 2 else ["", ""]
                
                c175212_1, c175212_2 = st.columns([1, 1])
                
                with c175212_1:
                    st.write("🔬 **Exames e Prazos:**")
                    
                    # Primeiro Exame
                    ex_1 = st.text_input("1º - Descrição do exame médico:", value=e1[0] if len(e1) > 0 else "", key=f"ex1_175212_{ano_sel}")
                    ex_dias_1 = st.text_input("1º - Tempo médio de espera (em dias):", value=e1[1] if len(e1) > 1 else "", key=f"ex_dias1_175212_{ano_sel}")
                    
                    st.markdown("---")
                    
                    # Segundo Exame
                    ex_2 = st.text_input("2º - Descrição do exame médico:", value=e2[0] if len(e2) > 0 else "", key=f"ex2_175212_{ano_sel}")
                    ex_dias_2 = st.text_input("2º - Tempo médio de espera (em dias):", value=e2[1] if len(e2) > 1 else "", key=f"ex_dias2_175212_{ano_sel}")
                    
                    st.markdown("---")
                    
                    # Terceiro Exame
                    ex_3 = st.text_input("3º - Descrição do exame médico:", value=e3[0] if len(e3) > 0 else "", key=f"ex3_175212_{ano_sel}")
                    ex_dias_3 = st.text_input("3º - Tempo médio de espera (em dias):", value=e3[1] if len(e3) > 1 else "", key=f"ex_dias3_175212_{ano_sel}")

                with c175212_2:
                    link_17_5_2_1_2 = st.text_area(
                        "Link/Evidência ou Relatório estatístico dos tempos de espera de exames (17.5.2.1.2):", 
                        value=d17_5_2_1_2.get("link", ""), 
                        key=f"reg_17_5_2_1_2_txt_{ano_sel}",
                        height=320
                    )
                    
                    # SUPORTE MULTI-LINKS ATIVOS (Isolado e protegido de forma síncrona)
                    with st.container(key=f"links_holder_maior_espera_exames_17_5_2_1_2_{ano_sel}"):
                        links_17_5_2_1_2_atuais = re.findall(r'(https?://[^\s]+)', link_17_5_2_1_2)
                        if links_17_5_2_1_2_atuais:
                            botoes_17_5_2_1_2 = " | ".join([f"🔗 [{u}]({u})" for u in links_17_5_2_1_2_atuais])
                            st.markdown(f"**Links Ativos:** {botoes_17_5_2_1_2}")
                
                # Monta a string estruturada para salvar tudo em um único campo de texto
                string_estruturada_ex = f"{ex_1}|{ex_dias_1}||{ex_2}|{ex_dias_2}||{ex_3}|{ex_dias_3}"
                if string_estruturada_ex == "||||":
                    string_estruturada_ex = ""
                    
                pts_17_5_2_1_2 = 0.0
                
                # ISOLAMENTO DO SCORE: Protegido por container para manter a integridade da árvore do React
                with st.container(key=f"score_holder_maior_espera_exames_17_5_2_1_2_{ano_sel}"):
                    st.markdown(f"📊 **Pontuação Aplicada no Quesito 17.5.2.1.2:** `{pts_17_5_2_1_2:.1f} pontos` (Dados Informativos)")
                
                # SALVAMENTO TOTALMENTE SINCRONIZADO NA MEMÓRIA LOCAL
                mudou_valores_17_5_2_1_2 = string_estruturada_ex != valores_salvos_1_2
                mudou_link_17_5_2_1_2 = link_17_5_2_1_2 != d17_5_2_1_2.get("link", "")

                if mudou_valores_17_5_2_1_2 or mudou_link_17_5_2_1_2:
                    save_resp("17.5.2.1.2", string_estruturada_ex, pts_17_5_2_1_2, link_17_5_2_1_2)
                    
                    if "17.5.2.1.2" not in res_data:
                        res_data["17.5.2.1.2"] = {}
                    res_data["17.5.2.1.2"]["valor"] = string_estruturada_ex
                    res_data["17.5.2.1.2"]["pontos"] = pts_17_5_2_1_2
                    res_data["17.5.2.1.2"]["link"] = link_17_5_2_1_2
                    
                    if mudou_link_17_5_2_1_2 and links_17_5_2_1_2_atuais:
                        links_17_5_2_1_2_antigos = re.findall(r'(https?://[^\s]+)', d17_5_2_1_2.get("link", ""))
                        if links_17_5_2_1_2_atuais != links_17_5_2_1_2_antigos:
                            modal_aviso_link("17.5.2.1.2", links_17_5_2_1_2_atuais)
                        else:
                            st.rerun()
                    else:
                        st.rerun()
                    
                bloco_comentarios("17.5.2.1.2", res_data)

        # =============================================================================
        # QUESITO 17.5.2.1.3 - 3 TERAPIAS/TRATAMENTOS COM MAIOR TEMPO DE ESPERA
        # =============================================================================
        # Substituída a div HTML manual por contêiner nativo estável com chave fixa
        with st.container(key=f"container_bloco_maior_espera_terapias_17_5_2_1_3_{ano_sel}", border=True):
            
            with st.expander(f"📌 Quesito 17.5.2.1.3 - Terapias/Tratamentos com Maior Tempo de Espera", expanded=True):
                st.subheader("17.5.2.1.3 • Terapias/Tratamentos com Maior Tempo de Espera")
                st.write(f"**17.5.2.1.3 Informe as 3 terapias/tratamentos médicos com maior tempo de espera na Atenção Especializada:**")
                st.caption("ℹ️ *O salvamento é automático. Qualquer alteração nos campos ou no link grava os dados na hora.*")
                
                # Recupera os dados salvos ou inicia um dicionário padrão
                d17_5_2_1_3 = res_data.get("17.5.2.1.3", {"valor": "", "pontos": 0.0, "link": ""})
                valores_salvos_1_3 = d17_5_2_1_3.get("valor", "")
                
                # Trata a string salva para preencher os campos (Terapia 1|Dias 1||Terapia 2|Dias 2||Terapia 3|Dias 3)
                partes_ter = valores_salvos_1_3.split("||") if valores_salvos_1_3 else []
                
                t1 = partes_ter[0].split("|") if len(partes_ter) > 0 else ["", ""]
                t2 = partes_ter[1].split("|") if len(partes_ter) > 1 else ["", ""]
                t3 = partes_ter[2].split("|") if len(partes_ter) > 2 else ["", ""]
                
                c175213_1, c175213_2 = st.columns([1, 1])
                
                with c175213_1:
                    st.write("💆‍♂️ **Terapias / Tratamentos e Prazos:**")
                    
                    # Primeira Terapia
                    ter_1 = st.text_input("1ª - Descrição da terapia/ tratamento médico:", value=t1[0] if len(t1) > 0 else "", key=f"ter1_175213_{ano_sel}")
                    ter_dias_1 = st.text_input("1ª - Tempo médio de espera (em dias):", value=t1[1] if len(t1) > 1 else "", key=f"ter_dias1_175213_{ano_sel}")
                    
                    st.markdown("---")
                    
                    # Segunda Terapia
                    ter_2 = st.text_input("2ª - Descrição da terapia/ tratamento médico:", value=t2[0] if len(t2) > 0 else "", key=f"ter2_175213_{ano_sel}")
                    ter_dias_2 = st.text_input("2ª - Tempo médio de espera (em dias):", value=t2[1] if len(t2) > 1 else "", key=f"ter_dias2_175213_{ano_sel}")
                    
                    st.markdown("---")
                    
                    # Terceira Terapia
                    ter_3 = st.text_input("3ª - Descrição da terapia/ tratamento médico:", value=t3[0] if len(t3) > 0 else "", key=f"ter3_175213_{ano_sel}")
                    ter_dias_3 = st.text_input("3ª - Tempo médio de espera (em dias):", value=t3[1] if len(t3) > 1 else "", key=f"ter_dias3_175213_{ano_sel}")

                with c175213_2:
                    link_17_5_2_1_3 = st.text_area(
                        "Link/Evidência ou Relatório estatístico dos tempos de espera de terapias (17.5.2.1.3):", 
                        value=d17_5_2_1_3.get("link", ""), 
                        key=f"reg_17_5_2_1_3_txt_{ano_sel}",
                        height=320
                    )
                    
                    # SUPORTE MULTI-LINKS ATIVOS (Isolado e protegido de forma síncrona)
                    with st.container(key=f"links_holder_maior_espera_terapias_17_5_2_1_3_{ano_sel}"):
                        links_17_5_2_1_3_atuais = re.findall(r'(https?://[^\s]+)', link_17_5_2_1_3)
                        if links_17_5_2_1_3_atuais:
                            botoes_17_5_2_1_3 = " | ".join([f"🔗 [{u}]({u})" for u in links_17_5_2_1_3_atuais])
                            st.markdown(f"**Links Ativos:** {botoes_17_5_2_1_3}")
                
                # Monta a string estruturada para salvar tudo em um único campo de texto
                string_estruturada_ter = f"{ter_1}|{ter_dias_1}||{ter_2}|{ter_dias_2}||{ter_3}|{ter_dias_3}"
                if string_estruturada_ter == "||||":
                    string_estruturada_ter = ""
                    
                pts_17_5_2_1_3 = 0.0
                
                # ISOLAMENTO DO SCORE: Protegido por container para manter a integridade da árvore do React
                with st.container(key=f"score_holder_maior_espera_terapias_17_5_2_1_3_{ano_sel}"):
                    st.markdown(f"📊 **Pontuação Aplicada no Quesito 17.5.2.1.3:** `{pts_17_5_2_1_3:.1f} pontos` (Dados Informativos)")
                
                # SALVAMENTO TOTALMENTE SINCRONIZADO NA MEMÓRIA LOCAL
                mudou_valores_17_5_2_1_3 = string_estruturada_ter != valores_salvos_1_3
                mudou_link_17_5_2_1_3 = link_17_5_2_1_3 != d17_5_2_1_3.get("link", "")

                if mudou_valores_17_5_2_1_3 or mudou_link_17_5_2_1_3:
                    save_resp("17.5.2.1.3", string_estruturada_ter, pts_17_5_2_1_3, link_17_5_2_1_3)
                    
                    if "17.5.2.1.3" not in res_data:
                        res_data["17.5.2.1.3"] = {}
                    res_data["17.5.2.1.3"]["valor"] = string_estruturada_ter
                    res_data["17.5.2.1.3"]["pontos"] = pts_17_5_2_1_3
                    res_data["17.5.2.1.3"]["link"] = link_17_5_2_1_3
                    
                    if mudou_link_17_5_2_1_3 and links_17_5_2_1_3_atuais:
                        links_17_5_2_1_3_antigos = re.findall(r'(https?://[^\s]+)', d17_5_2_1_3.get("link", ""))
                        if links_17_5_2_1_3_atuais != links_17_5_2_1_3_antigos:
                            modal_aviso_link("17.5.2.1.3", links_17_5_2_1_3_atuais)
                        else:
                            st.rerun()
                    else:
                        st.rerun()
                    
                bloco_comentarios("17.5.2.1.3", res_data)
