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
# 1. IMPORTAÇÃO DAS FUNÇÕES UTILITÁRIAS COMPARTILHADAS (UTILS)
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

        # Compatibilidade de comentários em lista ou string
        comentarios_lista = comentarios if comentarios is not None else []

        st.session_state[key_ano][str(qid)] = {
            "valor": str(valor),
            "pontos": float(pontos),
            "link": str(link),
            "comentario": str(comentario),
            "comentarios": comentarios_lista,
            "detalhes": {"link": str(link), "comentario": str(comentario), "comentarios": comentarios_lista}
        }
        return True

    def bloco_comentarios(questao_id: str, res_data: dict, sufixo=None):
        """Fallback do Diálogo Interno avançado com histórico, status e deleção."""
        ano_sel = st.session_state.get("ano_referencia_ieduc", st.session_state.get("ano_referencia_igov", date.today().year))
        usuario_atual = st.session_state.get("username", st.session_state.get("usuario", "Usuário Anônimo"))
        
        id_chave = f"{questao_id}_{sufixo}" if sufixo else questao_id
        key_texto = f"v_txt_com_{id_chave}_{ano_sel}"
        key_estado_limpar = f"limpar_input_{id_chave}_{ano_sel}"
        key_radio = f"rad_status_{id_chave}_{ano_sel}"
        
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
            
            # Mudança de Status
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
                    pontos=dados_questao.get("pontos", 0),
                    link=dados_questao.get("link", ""),
                    comentarios=historico
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
                                f"""<div style="background-color: #f8f9fa; padding: 10px 15px; border-radius: 8px; margin-bottom: 6px; border-left: 3px solid #1e88e5;">
                                    <span style="font-size: 11px; color: #1e88e5; font-weight: bold;">{autor}</span> 
                                    <span style="font-size: 10px; color: #999; margin-left: 10px;">{data_com}</span>
                                    <p style="margin: 4px 0 0 0; font-size: 13px; color: #333;">{texto_com}</p>
                                </div>""", unsafe_allow_html=True
                            )
                    
                    with col_lixeira:
                        if st.button("🗑️", key=f"btn_del_com_{id_chave}_{idx}_{ano_sel}"):
                            historico.pop(idx)
                            save_resp_ieduc(
                                qid=questao_id,
                                valor=dados_questao.get("valor", ""),
                                pontos=dados_questao.get("pontos", 0),
                                link=dados_questao.get("link", ""),
                                comentarios=historico
                            )
                            st.rerun()
            
            # Limpeza do campo de entrada
            if st.session_state[key_estado_limpar]:
                st.session_state[key_texto] = ""
                st.session_state[key_estado_limpar] = False
                
            novo_texto = st.text_area("Novo comentário:", key=key_texto, height=70, label_visibility="collapsed")
            
            if st.button("Postar Comentário", key=f"btn_com_{id_chave}_{ano_sel}", type="primary"):
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
                        pontos=dados_questao.get("pontos", 0), 
                        link=dados_questao.get("link", ""),
                        comentarios=historico
                    )
                    st.session_state[key_estado_limpar] = True
                    st.rerun()

    @st.dialog("⚠️ Atenção! Evidência em Link Externo")
    def modal_aviso_link(qid: str = "", links_encontrados: list = None, ano_sel: str = ""):
        if links_encontrados is None:
            links_encontrados = []

        st.warning(f"Detectamos a inclusão de link(s) no campo de evidências da questão **{qid}**.")
        
        for lk in links_encontrados:
            url_limpa = lk[0] if isinstance(lk, tuple) else str(lk)
            st.markdown(f"🔗 **Endereço:** [{url_limpa}]({url_limpa})")
            
        st.markdown("""
        **Por favor, verifique se este link está configurado para acesso público/compartilhado.**
        
        Se as credenciais estiverem privadas ou exigirem login e senha do seu município, as equipes avaliadoras externas **não conseguirão acessar as provas**, invalidando os pontos desse quesito.
        """)
        
        if st.button("Confirmo que o link está liberado para o público", key=f"btn_conf_{qid}_{ano_sel}", type="primary"):
            st.session_state[f"gatilho_modal_{qid}_{ano_sel}"] = False
            st.rerun()

    def render_sidebar_ieduc(*args, **kwargs):
        return 0, {}, datetime.now().year

# =============================================================================
# CONFIGURAÇÃO COMPLETA DE ESTILOS DE RELATÓRIO (PDF) - iEduc
# =============================================================================
styles = getSampleStyleSheet()

title_style = ParagraphStyle(
    'TitleStyle',
    parent=styles['Heading1'],
    fontSize=16,
    alignment=TA_CENTER,
    spaceAfter=12
)
subtitle_style = ParagraphStyle(
    'SubtitleStyle',
    parent=styles['Normal'],
    fontSize=12,
    alignment=TA_CENTER,
    spaceAfter=10
)
section_header_style = ParagraphStyle(
    'SectionHeaderStyle',
    parent=styles['Heading2'],
    fontSize=14,
    spaceBefore=12,
    spaceAfter=6,
    textColor=colors.HexColor("#1e3a8a")
)

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

# =============================================================================
# QUESITO 1.0 • INFRAESTRUTURA DA EDUCAÇÃO INFANTIL (iEduc)
# =============================================================================
def render_questao_1_0_ieduc(res_data: dict, ano_sel: str):
    """Renderiza a Questão 1.0 (Oferta de Creche) no modelo padrão iGov / iEduc."""
    
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
                links_10_visuais = re.findall(REGEX_PURE_URL, link_10 or "")
                if links_10_visuais:
                    placeholder_links_10.markdown(
                        "**🔗 Link ativo:** "
                        + " | ".join(
                            [f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" for u in links_10_visuais]
                        )
                    )

            # Renderização do chat de comentários / histórico
            bloco_comentarios("1.0", res_data, ano_sel)

            # Botão de salvamento
            if st.button("💾 Salvar Questão 1.0", key=f"btn_salvar_1_0_{ano_sel}", type="primary"):
                val_salvar = st.session_state.get(chave_radio_10, v_salvo_10)
                pts_10 = float(opcoes_10.get(val_salvar, 0.0))
                lnk_val = link_10.strip()

                comentarios_historico = d10.get("comentarios", [])
                comentario_simples = d10.get("comentario", "")

                save_resp_ieduc(
                    qid="1.0",
                    valor=val_salvar,
                    pontos=pts_10,
                    link=lnk_val,
                    comentario=comentario_simples,
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
        modal_aviso_link("1.0", st.session_state.get(f"links_pendentes_1_0_{ano_sel}", []), ano_sel)

# =============================================================================
# FUNÇÃO PRINCIPAL / ENTRY POINT PARA O MAIN.PY
# =============================================================================
def mostrar_formulario_educ():
    """Função invocada pelo main.py para carregar a interface do iEduc."""
    st.title("🎓 iEduc — Índice de Educação")
    
    ano_sel = str(st.session_state.get("ano_referencia_ieduc", st.session_state.get("ano_referencia_igov", 2026)))
    
    res_data = load_respostas_ieduc(int(ano_sel) if ano_sel.isdigit() else 2026) or {}
    
    if not isinstance(res_data, dict):
        res_data = {}

    # Renderização das questões
    render_questao_1_0_ieduc(res_data, ano_sel)
