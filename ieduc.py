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
# 1. INTEGRAÇÃO COM BANCO NEON / POSTGRESQL & UTILS
# =============================================================================
def get_connection():
    """Conexão direta com o banco PostgreSQL / Neon usando secrets do Streamlit."""
    try:
        # Tenta pegar das secrets do Streamlit
        db_url = st.secrets.get("postgres", {}).get("url") or st.secrets.get("DATABASE_URL") or os.getenv("DATABASE_URL")
        if not db_url:
            raise ValueError("URL do banco de dados não encontrada em st.secrets ou variáveis de ambiente.")
        return psycopg2.connect(db_url)
    except Exception as e:
        logging.error(f"Erro ao conectar com o banco Neon: {e}")
        return None

try:
    from utils import (
        bloco_comentarios,
        load_respostas_ieduc,
        modal_aviso_link,
        render_sidebar_ieduc,
        save_resp_ieduc,
    )
except ImportError:
    logging.warning("Módulo utils.py não importado. Usando métodos diretos com Neon DB.")

    def load_respostas_ieduc(ano: int = None, forcar_recarga: bool = False) -> dict:
        """Carrega respostas diretamente do Neon DB para o iEduc."""
        ano_sel = ano or st.session_state.get("ano_referencia_ieduc", 2026)
        conn = get_connection()
        if not conn:
            key_ano = f"respostas_ieduc_{ano_sel}"
            return st.session_state.get(key_ano, {})

        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT questao_id, resposta FROM respostas_ieduc WHERE ano = %s",
                    (ano_sel,)
                )
                rows = cur.fetchall()
                res = {}
                for r in rows:
                    qid = str(r["questao_id"])
                    val = r["resposta"]
                    res[qid] = json.loads(val) if isinstance(val, str) else val
                return res
        except Exception as e:
            logging.error(f"Erro ao carregar do Neon: {e}")
            key_ano = f"respostas_ieduc_{ano_sel}"
            return st.session_state.get(key_ano, {})
        finally:
            conn.close()

    def save_resp_ieduc(qid, valor, pontos, link="", comentarios=None, comentario=""):
        """Salva respostas diretamente no banco Neon DB."""
        ano_sel = st.session_state.get("ano_referencia_ieduc", 2026)
        comentarios_lista = comentarios if comentarios is not None else []
        
        d_payload = {
            "valor": str(valor),
            "pontos": float(pontos),
            "link": str(link),
            "comentario": str(comentario),
            "comentarios": comentarios_lista,
            "detalhes": {"link": str(link), "comentario": str(comentario), "comentarios": comentarios_lista}
        }

        conn = get_connection()
        if conn:
            try:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO respostas_ieduc (ano, questao_id, resposta, updated_at)
                        VALUES (%s, %s, %s, NOW())
                        ON CONFLICT (ano, questao_id)
                        DO UPDATE SET resposta = EXCLUDED.resposta, updated_at = NOW();
                    """, (ano_sel, str(qid), json.dumps(d_payload)))
                    conn.commit()
            except Exception as e:
                logging.error(f"Erro ao salvar no Neon: {e}")
            finally:
                conn.close()

        # Guarda no session_state para manter sincronizado
        key_ano = f"respostas_ieduc_{ano_sel}"
        if key_ano not in st.session_state:
            st.session_state[key_ano] = {}
        st.session_state[key_ano][str(qid)] = d_payload
        return True

    def bloco_comentarios(questao_id: str, res_data: dict, sufixo=None):
        """Painel de Comentários e Histórico do Quesito."""
        ano_sel = st.session_state.get("ano_referencia_ieduc", date.today().year)
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
        Se as credenciais estiverem privadas, os avaliadores externas não conseguirão visualizar a prova.
        """)
        
        if st.button("Confirmo que o link está liberado para o público", key=f"btn_conf_{qid}_{ano_sel}", type="primary"):
            st.session_state[f"gatilho_modal_{qid}_{ano_sel}"] = False
            st.rerun()

# =============================================================================
# 2. PAINEL DE DESEMPENHO E GRÁFICOS DO iEDUC
# =============================================================================
def render_painel_ieduc(res_data: dict, ano_sel: str):
    """Renderiza a Dashboard / Painel Geral de Indicadores da Educação."""
    st.markdown("## 📊 Painel Geral de Desempenho — iEduc")
    
    # Cálculo das métricas gerais
    total_pontos = sum(float(item.get("pontos", 0.0)) for item in res_data.values() if isinstance(item, dict))
    total_quesitos = len(res_data)
    quesitos_respondidos = sum(1 for item in res_data.values() if isinstance(item, dict) and item.get("valor") not in ["Selecione...", "", None])
    
    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    with kpi1:
        st.metric(label="Pontuação Atual", value=f"{total_pontos:.1f} pts")
    with kpi2:
        st.metric(label="Quesitos Cadastrados", value=f"{total_quesitos}")
    with kpi3:
        st.metric(label="Quesitos Respondidos", value=f"{quesitos_respondidos}")
    with kpi4:
        pct_concluido = (quesitos_respondidos / total_quesitos * 100) if total_quesitos > 0 else 0
        st.metric(label="Conclusão", value=f"{pct_concluido:.0f}%")

    st.markdown("---")
    
    # Gráfico comparativo / visual
    col_g1, col_g2 = st.columns(2)
    with col_g1:
        fig_pie = px.pie(
            names=["Respondidos", "Pendentes"],
            values=[quesitos_respondidos, max(0, total_quesitos - quesitos_respondidos)],
            title="Progresso do Preenchimento",
            color_discrete_sequence=["#1e88e5", "#e0e0e0"]
        )
        st.plotly_chart(fig_pie, use_container_width=True)
        
    with col_g2:
        fig_bar = go.Figure(go.Bar(
            x=["Pontuação iEduc"],
            y=[total_pontos],
            marker_color="#28a745"
        ))
        fig_bar.update_layout(title="Total de Pontos Atingidos", yaxis=dict(range=[0, 100]))
        st.plotly_chart(fig_bar, use_container_width=True)

# =============================================================================
# 3. QUESITO 1.0 • INFRAESTRUTURA DA EDUCAÇÃO INFANTIL
# =============================================================================
def render_questao_1_0_ieduc(res_data: dict, ano_sel: str):
    """Renderiza a Questão 1.0 (Oferta de Creche)."""
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

            bloco_comentarios("1.0", res_data, ano_sel)

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

                if lnk_val != evidencia_10_salva and links_atuais and links_atuais != links_antigos:
                    st.session_state[f"links_pendentes_1_0_{ano_sel}"] = links_atuais
                    st.session_state[f"gatilho_modal_1_0_{ano_sel}"] = True

                st.cache_data.clear()
                st.toast("Resposta e histórico salvos no banco Neon com sucesso!", icon="✅")
                st.rerun()

            pts_atuais_10 = d10.get("pontos", 0.0)
            cor_txt_10 = "#28a745" if pts_atuais_10 > 0.0 else "#6c757d"

            st.markdown(
                f"<span style='color:{cor_txt_10}; font-weight:bold;'>"
                f"📊 Impacto de Pontuação no Quesito 1.0: +{pts_atuais_10:.1f} pontos</span>",
                unsafe_allow_html=True,
            )

    if st.session_state.get(f"gatilho_modal_1_0_{ano_sel}", False):
        modal_aviso_link("1.0", st.session_state.get(f"links_pendentes_1_0_{ano_sel}", []), ano_sel)

# =============================================================================
# 4. FUNÇÃO PRINCIPAL CHAMADA PELO MAIN.PY
# =============================================================================
def mostrar_formulario_educ():
    """Ponto de entrada do módulo iEduc."""
    st.title("🎓 iEduc — Índice de Educação")

    ano_sel = str(st.session_state.get("ano_referencia_ieduc", st.session_state.get("ano_referencia_igov", 2026)))

    # Carrega do banco Neon
    res_data = load_respostas_ieduc(int(ano_sel) if ano_sel.isdigit() else 2026) or {}
    if not isinstance(res_data, dict):
        res_data = {}

    tab_painel, tab_formulario = st.tabs(["📊 Painel de Desempenho", "📝 Formulario de Avaliacao"])

    with tab_painel:
        render_painel_ieduc(res_data, ano_sel)

    with tab_formulario:
        render_questao_1_0_ieduc(res_data, ano_sel)
