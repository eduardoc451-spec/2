import streamlit as st
import sqlite3
import json
import re
# Definição da regex no formato de tupla/grupo esperado pelo list comprehension do código
regex_pure_url = r'((https?://[^\s]+))'
from io import BytesIO
from datetime import datetime, date

# Bibliotecas para o PDF (Requer: pip install reportlab)
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle  # <-- Garanta que ele está aqui em cima!
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

# Bibliotecas para os Gráficos (Requer: pip install plotly)
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots

# =============================================================================
# CONSTANTES GLOBAIS - IAMB
# =============================================================================

PONTUACOES_MAX = {
    "1.1.2": 20,
    "1.1.3": 5,
    "1.2": 20,
    "2.0": 10,
    "2.1": 50,
    "3.0": 10,
    "3.1": 20,
    "4.0": 20,
    "5.2.1": 20,
    "6.0": 20,
    "6.1": 50,
    "6.2": 25,
    "7.2": 2,
    "7.3": 10,
    "7.3.1": 20,
    "7.4": 10,
    "7.4.1": 20,
    "7.5": 30,
    "7.7": 30,
    "7.8": 20,
    "7.8.1": 50,
    "7.9": 3,
    "8.2": 2,
    "8.3": 10,
    "8.4": 20,
    "8.4.1": 10,
    "8.4.2": 30,
    "8.4.3": 50,
    "9.2": 100,
    "9.3": 5,
    "9.3.1": 5,
    "11.2": 2,
    "11.3": 30,
    "11.3.2": 20,
    "11.3.3": 40,
    "11.5": 10,
    "12.1": 54,
    "14.3": 30,
    "15": 2,
    "15.1": 3,
    "A4.1.1": 90,
    "A4.1.2": 20,
    "A4.1.3": 22,
    "A6": 5
}

CATEGORIAS_MAP = {
    "planejamento":   {"label": "Planejamento",    "qids": ["1.1.2", "1.1.3", "1.2"]},
    "gestao_fiscal":  {"label": "Gestão Fiscal",   "qids": ["2.0", "2.1"]},
    "educacao":       {"label": "Educação",         "qids": ["3.0", "3.1"]},
    "saude":          {"label": "Saúde",            "qids": ["4.0"]},
    "meio_ambiente":  {"label": "Meio Ambiente",    "qids": ["5.2.1", "6.0", "6.1", "6.2", "14.3"]},
    "governanca_ti":  {"label": "Governança TI",    "qids": ["7.2", "7.3", "7.3.1", "7.4", "7.4.1", "7.5", "7.7", "7.8", "7.8.1", "7.9"]},
    "transparencia":  {"label": "Transparência",    "qids": ["8.2", "8.3", "8.4", "8.4.1", "8.4.2", "8.4.3", "9.2", "9.3", "9.3.1"]},
    "outros":         {"label": "Outros",           "qids": ["11.2", "11.3", "11.3.2", "11.3.3", "11.5", "12.1", "15", "15.1", "A4.1.1", "A4.1.2", "A4.1.3", "A6"]},
}

FAIXA_CORES = {"C": "#ef4444", "C+": "#f97316", "B": "#eab308", "B+": "#22c55e", "A": "#16a34a"}

# =============================================================================
# MODAL DE AVISO AUTOMÁTICO (CORRIGIDO PARA LINKS CLICÁVEIS)
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

# =============================================================================
# 1. FUNÇÕES DE APOIO E BANCO DE DADOS (IEGM - I-AMB)
# =============================================================================
import sqlite3
import json
import datetime
import re
import ast
import streamlit as st

def get_connection():
    # Conecta no banco de dados isolado e específico do I-AMB
    return sqlite3.connect("dados_iamb.db", check_same_thread=False)

def init_db():
    """Cria as tabelas do banco de dados com migração automática e suporte a comentários estruturados em JSON."""
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # 1. Cria a tabela base estruturada
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS respostas (
                id TEXT NOT NULL,
                ano INTEGER NOT NULL,
                valor TEXT,
                pontos REAL DEFAULT 0,
                link TEXT,
                criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (id, ano)
            )
        """)
        
        # 2. PRAGMA para checar quais colunas realmente existem no arquivo físico do banco do I-AMB
        cursor.execute("PRAGMA table_info(respostas)")
        colunas_existentes = [row[1] for row in cursor.fetchall()]
        
        # 3. Força a migração da coluna de comentários em JSON se não existir
        if "comentarios" not in colunas_existentes:
            try:
                cursor.execute("ALTER TABLE respostas ADD COLUMN comentarios TEXT")
            except sqlite3.OperationalError:
                pass
                
        # 4. Garante que a coluna 'atualizado_em' esteja com o nome perfeito
        if "atualizado_em" not in colunas_existentes:
            try:
                cursor.execute("ALTER TABLE respostas ADD COLUMN atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
            except sqlite3.OperationalError:
                pass
                
        # 5. Garante a coluna criado_em
        if "criado_em" not in colunas_existentes:
            try:
                cursor.execute("ALTER TABLE respostas ADD COLUMN criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
            except sqlite3.OperationalError:
                pass
                
        conn.commit()

def load_respostas(ano):
    dados_ano = {}
    try:
        with get_connection() as conn:
            cursor = conn.execute(
                "SELECT id, valor, pontos, link, comentarios FROM respostas WHERE ano = ?", (ano,)
            )
            for row in cursor.fetchall():
                comentarios_lista = []
                if row[4]:
                    try:
                        comentarios_lista = json.loads(row[4])
                    except Exception:
                        comentarios_lista = []
                        
                dados_ano[row[0]] = {
                    "valor": row[1], 
                    "pontos": row[2], 
                    "link": row[3],
                    "comentarios": comentarios_lista
                }
    except Exception:
        pass
    return dados_ano

def save_resp(qid, valor, pontos, link, comentarios=None):
    ano_sel = st.session_state.get("ano_referencia_global")
    if not ano_sel:
        return
    
    comentarios_json = None
    if comentarios is not None:
        comentarios_json = json.dumps(comentarios, ensure_ascii=False)
    else:
        dados_atuais = load_respostas(ano_sel)
        if qid in dados_atuais:
            comentarios_json = json.dumps(dados_atuais[qid].get("comentarios", []), ensure_ascii=False)

    try:
        timestamp_atual = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    except AttributeError:
        import datetime as dt_modulo
        timestamp_atual = dt_modulo.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        with get_connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO respostas (id, ano, valor, pontos, link, comentarios, atualizado_em) 
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (qid, ano_sel, str(valor), float(pontos), str(link), comentarios_json, timestamp_atual))
            conn.commit()
    except sqlite3.OperationalError as e:
        if "no column named atualizado_em" in str(e):
            try:
                with get_connection() as conn:
                    conn.execute("ALTER TABLE respostas ADD COLUMN atualizado_em TEXT")
                    conn.commit()
                save_resp(qid, valor, pontos, link, comentarios)
            except Exception as ex:
                st.error(f"Erro crítico ao tentar corrigir estrutura: {ex}")
        else:
            st.error(f"Erro operacional no banco do I-AMB: {e}")
    except Exception as e:
        st.error(f"Erro ao salvar {qid}: {e}")

def bloco_comentarios(questao_id, res_data, sufixo=None):
    """
    Gera o diálogo interno avançado com histórico retrátil, status em realtime
    e controle individual de remoção por lixeira para o módulo I-AMB.
    """
    ano_sel = st.session_state.get("ano_referencia_global", datetime.date.today().year)
    usuario_atual = st.session_state.get("username", st.session_state.get("usuario", "Usuário Anônimo"))
    
    id_chave = f"{questao_id}_{sufixo}" if sufixo else questao_id
    key_texto = f"v_txt_com_{id_chave}_{ano_sel}"
    key_estado_limpar = f"limpar_input_{id_chave}_{ano_sel}"
    
    if key_estado_limpar not in st.session_state:
        st.session_state[key_estado_limpar] = False
        
    st.markdown("---")
    
    dados_questao = res_data.get(questao_id, {})
    historico = dados_questao.get("comentarios", [])
    
    status_global = "Resolvido"
    for com in historico:
        if "status_definido" in com:
            status_global = com["status_definido"]
            
    badge_status = "🔴 PENDENTE" if status_global == "Pendente" else "🟢 RESOLVIDO"
    
    with st.expander(f"💬 Diálogo Interno {id_chave} | Status: {badge_status}", expanded=(status_global == "Pendente")):
        
        st.markdown("<b style='font-size: 13px;'>Status Atual do Quesito:</b>", unsafe_allow_html=True)
        opcoes_status = ["Resolvido", "Pendente"]
        idx_status_atual = opcoes_status.index(status_global)
        
        novo_status_clicado = st.radio(
            f"Definir status para {id_chave}:",
            options=opcoes_status,
            index=idx_status_atual,
            horizontal=True,
            key=f"rad_status_{id_chave}_{ano_sel}",
            label_visibility="collapsed"
        )
        
        if novo_status_clicado != status_global:
            log_mudanca = {
                "autor": "Sistema / " + usuario_atual,
                "data": datetime.datetime.now().strftime("%d/%m/%Y %H:%M"),
                "texto": f"ℹ️ Alterou o status do quesito para: **{novo_status_clicado.upper()}**.",
                "status_definido": novo_status_clicado
            }
            historico.append(log_mudanca)
            save_resp(
                qid=questao_id,
                valor=dados_questao.get("valor", ""),
                pontos=dados_questao.get("pontos", 0.0),
                link=dados_questao.get("link", ""),
                comentarios=historico
            )
            st.rerun()

        st.markdown("<div style='margin-bottom: 15px;'></div>", unsafe_allow_html=True)

        if historico:
            for idx, com in enumerate(historico):
                col_balao, col_lixeira = st.columns([11, 1])
                
                with col_balao:
                    if "Sistema /" in com['autor']:
                        st.markdown(
                            f"""
                            <div style="background-color: #f1f3f5; padding: 6px 12px; border-radius: 6px; margin-bottom: 4px; border-left: 3px solid #ced4da;">
                                <span style="font-size: 11px; color: #6c757d; font-style: italic;">{com['autor']} - {com['data']}</span>
                                <p style="margin: 2px 0 0 0; font-size: 12px; color: #495057; font-style: italic;">{com['texto']}</p>
                            </div>
                            """, 
                            unsafe_allow_html=True
                        )
                    else:
                        st.markdown(
                            f"""
                            <div style="background-color: #f8f9fa; padding: 10px 15px; border-radius: 8px; margin-bottom: 6px; border-left: 3px solid #1e88e5;">
                                <span style="font-size: 11px; color: #1e88e5; font-weight: bold;">{com['autor']}</span> 
                                <span style="font-size: 10px; color: #999; margin-left: 10px;">{com['data']}</span>
                                <p style="margin: 4px 0 0 0; font-size: 13px; color: #333;">{com['texto']}</p>
                            </div>
                            """, 
                            unsafe_allow_html=True
                        )
                
                with col_lixeira:
                    st.markdown("<div style='margin-top: 10px;'></div>", unsafe_allow_html=True)
                    if st.button("🗑️", key=f"btn_del_com_{id_chave}_{idx}_{ano_sel}", help="Excluir este comentário"):
                        historico.pop(idx)
                        save_resp(
                            qid=questao_id,
                            valor=dados_questao.get("valor", ""),
                            pontos=dados_questao.get("pontos", 0.0),
                            link=dados_questao.get("link", ""),
                            comentarios=historico
                        )
                        st.rerun()
                        
            st.markdown("<br>", unsafe_allow_html=True)
        else:
            st.markdown("<p style='font-size: 12px; color: #999; font-style: italic;'>Nenhum comentário enviado ainda.</p>", unsafe_allow_html=True)
            
        st.markdown("<b style='font-size: 13px;'>Adicionar Novo Comentário:</b>", unsafe_allow_html=True)
        
        if st.session_state[key_estado_limpar]:
            st.session_state[key_texto] = ""
            st.session_state[key_estado_limpar] = False
            
        novo_texto = st.text_area("Digite sua mensagem:", key=key_texto, height=80, label_visibility="collapsed")
        
        col_btn1, _ = st.columns([1, 3])
        with col_btn1:
            if st.button("Postar Comentário", key=f"btn_com_{id_chave}_{ano_sel}", type="primary"):
                if novo_texto.strip():
                    nova_mensagem = {
                        "autor": usuario_atual,
                        "data": datetime.datetime.now().strftime("%d/%m/%Y %H:%M"),
                        "texto": novo_texto.strip(),
                        "status_definido": status_global
                    }
                    historico.append(nova_mensagem)
                    save_resp(
                        qid=questao_id, 
                        valor=dados_questao.get("valor", ""), 
                        pontos=dados_questao.get("pontos", 0.0), 
                        link=dados_questao.get("link", ""),
                        comentarios=historico
                    )
                    st.session_state[key_estado_limpar] = True
                    st.rerun()

def get_all_years_data():
    all_data = {}
    with get_connection() as conn:
        cursor = conn.execute(
            "SELECT id, ano, valor, pontos, link, comentarios FROM respostas ORDER BY ano DESC"
        )
        for row in cursor.fetchall():
            qid, ano, valor, pontos, link, comentarios_raw = row
            
            comentarios_lista = []
            if comentarios_raw:
                try:
                    comentarios_lista = json.loads(comentarios_raw)
                except Exception:
                    comentarios_lista = []
                    
            if ano not in all_data:
                all_data[ano] = {}
            all_data[ano][qid] = {
                "valor": valor, 
                "pontos": pontos, 
                "link": link, 
                "comentarios": comentarios_lista
            }
    return all_data

# =============================================================================
# 2. INTERFACE E FORMULÁRIO (SIDEBAR E ESTRUTURA GLOBAL)
# =============================================================================

def render_sidebar():
    st.sidebar.title("🌿 Painel i-AMB")
    anos = [2023, 2024, 2025, 2026, 2027, 2028, 2029, 2030]
    ano_sel = st.sidebar.selectbox("Ano de Referência:", anos, key="ano_referencia_global")
    
    # Carrega dados do banco do ano selecionado
    res_data = load_respostas(ano_sel)
    
    # Soma os pontos de forma segura ignorando comentários
    total_pts = sum(float(item.get("pontos", 0)) for k, item in res_data.items() if not k.startswith("COM_"))
    total_pts = round(total_pts, 1)
    
    # 1. Nova Lógica de Faixas do i-AMB (Definição dos Limites)
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

    # 2. Regra Especial A2: Rebaixar 1 Faixa se condições inadequadas
    rebaixar = res_data.get("A2", {}).get("valor") == "Condições inadequadas"
    
    if rebaixar:
        if faixa == "A": 
            faixa, cor = "B+", "lightgreen"
        elif faixa == "B+": 
            faixa, cor = "B", "#d4d400"
        elif faixa == "B": 
            faixa, cor = "C+", "orange"
        elif faixa == "C+": 
            faixa, cor = "C", "red"

    # 3. Exibição das Métricas na Interface Lateral
    st.sidebar.metric("Pontuação Total", f"{total_pts:.1f} pts")
    st.sidebar.markdown(f"**Faixa:** <span style='color:{cor}; font-size:20px; font-weight:bold;'>{faixa}</span>", unsafe_allow_html=True)
    
    # Exibe o alerta caso a regra de rebaixamento tenha sido disparada
    if rebaixar:
        st.sidebar.warning("⚠️ Faixa rebaixada devido ao IQR (A2)")
        
    # -------------------------------------------------------------------------
    # 🔥 BOTÃO DE DOWNLOAD DO RELATÓRIO PDF INTEGRADO (COM HISTÓRICO TRATADO)
    # -------------------------------------------------------------------------
    st.sidebar.markdown("---")
    st.sidebar.subheader("📄 Relatórios")
    
    # 1. Busca os dados brutos de todos os anos no banco de dados para a série histórica
    try:
        dados_historicos_brutos = get_all_years_data()
    except Exception:
        dados_historicos_brutos = {}
        
    # 2. TRATAMENTO CRÍTICO: Garante que as chaves dos anos sejam inteiros
    historico_tratado = {}
    if isinstance(dados_historicos_brutos, dict):
        for ano_chave, valor_ano in dados_historicos_brutos.items():
            try:
                ano_int = int(str(ano_chave).strip()[:4])
                historico_tratado[ano_int] = valor_ano
            except (ValueError, TypeError):
                continue

    # 3. Alimenta o session_state como garantia extra para o componente do gráfico
    st.session_state.all_data = historico_tratado

    # 4. Gera o relatório passando o dicionário histórico tratado e captura o buffer do PDF
    try:
        pdf_buffer = gerar_relatorio_pdf(res_data, ano_sel, total_pts, faixa, historico_tratado)
        
        st.sidebar.download_button(
            label="📥 Baixar Relatório PDF",
            data=pdf_buffer.getvalue(),  # Extrai o valor binário correto do BytesIO
            file_name=f"Relatorio_i-AMB_{ano_sel}.pdf",
            mime="application/pdf"
        )
    except Exception as e:
        st.sidebar.error(f"Erro ao gerar o PDF: {e}")
        
    st.sidebar.markdown("---")
    
    # 5. Ação de Reset com Segurança no Banco de Dados e Interface
    if st.sidebar.button("🔄 Zerar Questionário"):
        # 1. Limpa o Banco de Dados para o ano selecionado
        with get_connection() as conn:
            conn.execute("DELETE FROM respostas WHERE ano = ?", (ano_sel,))
            conn.commit()
        
        # 2. Limpa apenas os widgets da interface
        prefixos_limpar = ("q", "l", "ext", "COM_")
        for key in list(st.session_state.keys()):
            if key.startswith(prefixos_limpar):
                del st.session_state[key]
                
        st.rerun()
        
    return total_pts, res_data, ano_sel

import io
from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

# =============================================================================
# 3. GERADOR DO RELATÓRIO PDF - i-AMB
# =============================================================================

def gerar_relatorio_pdf(dados, ano, total, faixa, all_data=None):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    elements = []
    
    # Inicializa os estilos padrões do ReportLab
    styles = getSampleStyleSheet()
    
    # Definição explícita dos estilos customizados da capa e tabelas
    style_titulo_capa = ParagraphStyle(
        'TituloCapa', 
        parent=styles['Normal'], 
        fontName='Helvetica-Bold', 
        fontSize=24, 
        leading=28, 
        textColor=colors.HexColor("#2e7d32"), 
        alignment=1
    )
    
    style_ano_capa = ParagraphStyle(
        'AnoCapa', 
        parent=styles['Normal'], 
        fontName='Helvetica', 
        fontSize=16, 
        leading=20,
        textColor=colors.HexColor("#7f8c8d"), 
        alignment=1
    )

    style_tabela_padrao = ParagraphStyle(
        'TextoTabela',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=12,
        alignment=0
    )

    style_tabela_centro = ParagraphStyle(
        'TextoTabelaCentro',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=12,
        alignment=1
    )

    # Função interna para limpar strings contra quebras no interpretador XML do ReportLab
    def limpar_xml(texto):
        return str(texto).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    if all_data is None:
        all_data = {}
        
    if 'PONTUACOES_MAX' not in globals():
        PONTUACOES_MAX = {
            "1.1.2": 20.0, "1.1.3": 10.0, "1.2": 20.0, "2.0": 10.0, "2.1": 50.0, "3.0": 10.0, "3.1": 20.0, "4.0": 20.0,
            "5.2.1": 20.0, "6.0": 20.0, "6.1": 50.0, "6.2": 25.0, "7.2": 2.0, "7.3": 10.0, "7.3.1": 20.0, "7.4": 10.0,
            "7.4.1": 20.0, "7.5": 30.0, "7.7": 30.0, "7.8": 20.0, "7.8.1": 50.0, "7.9": 3.0, "8.2": 2.0, "8.3": 10.0,
            "8.4": 20.0, "8.4.1": 10.0, "8.4.2": 30.0, "8.4.3": 50.0, "9.2": 100.0, "9.3": 5.0, "9.3.1": 5.0,
            "11.2": 2.0, "11.3": 30.0, "11.3.2": 20.0, "11.3.3": 40.0, "11.5": 10.0, "12.1": 54.0, "14.3": 30.0,
            "15": 2.0, "15.1": 3.0, "A4.1.1": 90.0, "A4.1.2": 20.0, "A4.1.3": 22.0, "A6": 5.0, "11": 10.0
        }
    else:
        PONTUACOES_MAX = globals()['PONTUACOES_MAX']

    # -------------------------------------------------------------------------
    # FOLHA 1: CAPA
    # -------------------------------------------------------------------------
    elements.append(Spacer(1, 100))
    
    try:
        logo = Image("iegm.png", width=380, height=180)
        logo.hAlign = 'CENTER'
        elements.append(logo)
    except Exception:
        elements.append(Paragraph("[Logo: iegm.png]", styles["Title"]))
        
    elements.append(Spacer(1, 50))
    elements.append(Paragraph("Relatório i-AMB", style_titulo_capa))
    elements.append(Spacer(1, 5))
    elements.append(Spacer(1, 15))
    
    elements.append(Paragraph(str(ano), style_ano_capa))
    elements.append(PageBreak())

    # -------------------------------------------------------------------------
    # FOLHA 2: SUMÁRIO
    # -------------------------------------------------------------------------
    elements.append(Paragraph("<b>SUMÁRIO</b>", styles["h1"]))
    elements.append(Spacer(1, 30))

    style_item_esquerda = ParagraphStyle('ItemEsq', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=11, leading=14, textColor=colors.HexColor("#2c3e50"))
    style_pag_direita = ParagraphStyle('PagDir', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=11, leading=14, textColor=colors.HexColor("#2e7d32"), alignment=2)

    dados_sumario = [
        [Paragraph("1. Resumo Executivo (Análise Comparativa)", style_item_esquerda), Paragraph("Pág. 3", style_pag_direita)],
        [Paragraph("2. Análise de Desempenho por Quesito i-AMB", style_item_esquerda), Paragraph("Pág. 3", style_pag_direita)],
        [Paragraph("3. Análise de Impacto e Penalidades", style_item_esquerda), Paragraph("Pág. 4", style_pag_direita)],
        [Paragraph("4. Diagnóstico de Reincidências", style_item_esquerda), Paragraph("Pág. 4", style_pag_direita)],
        [Paragraph("5. Alinhamento com a Agenda 2030", style_item_esquerda), Paragraph("Pág. 4", style_pag_direita)],
        [Paragraph("6. Série Histórica Ambiental", style_item_esquerda), Paragraph("Pág. 5", style_pag_direita)],
    ]
    
    tabela_sumario = Table(dados_sumario, colWidths=[400, 90])
    tabela_sumario.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
        ('TOPPADDING', (0, 0), (-1, -1), 12),
        ('LINEBELOW', (0, 0), (-1, -1), 0.5, colors.HexColor("#bdc3c7"), 1, (2, 4)), 
    ]))
    elements.append(tabela_sumario)
    elements.append(PageBreak())

    # -------------------------------------------------------------------------
    # FOLHA 3+: CONTEÚDO
    # -------------------------------------------------------------------------
    elements.append(Paragraph(f"RELATÓRIO DE AUDITORIA i-AMB (MEIO AMBIENTE) - {ano}", styles["Title"]))
    elements.append(Spacer(1, 12))

    elements.append(Paragraph("<b>1. RESUMO EXECUTIVO (ANÁLISE COMPARATIVA AMBIENTAL)</b>", styles["h2"]))
    elements.append(Spacer(1, 8))

    nota_atual = float(total)
    ano_atual = int(str(ano).strip()[:4])
    ano_ant = ano_atual - 1

    def converter_pontos_em_faixa_iamb(pontos):
        pts = float(pontos)
        if pts <= 500.0:             return "C"
        elif 501.0 <= pts <= 599.9:  return "C+"
        elif 600.0 <= pts <= 749.9:  return "B"
        elif 750.0 <= pts <= 899.9:  return "B+"
        else:                        return "A"

    dados_ano_anterior = all_data.get(ano_ant, {})
    nota_anterior = 0.0
    if ano_ant in all_data:
        nota_anterior = float(sum(
            info_ant.get("pontos", 0) 
            for qid_ant, info_ant in dados_ano_anterior.items() 
            if isinstance(info_ant, dict) and not qid_ant.startswith("COM_")
        ))

    faixa_anterior = converter_pontos_em_faixa_iamb(nota_anterior)
    faixa_real_atual = faixa if faixa else converter_pontos_em_faixa_iamb(nota_atual)

    variacao_pontos = nota_atual - nota_anterior
    if nota_anterior > 0:
        variacao_percentual = (variacao_pontos / nota_anterior) * 100
        texto_percentual = f"{variacao_percentual:+.2f}%"
    else:
        texto_percentual = "0.00%"

    if variacao_pontos > 0:
        cor_variacao = colors.HexColor("#28a745")
        seta_tendencia = "▲"
    elif variacao_pontos < 0:
        cor_variacao = colors.HexColor("#dc3545")
        seta_tendencia = "▼"
    else:
        cor_variacao = colors.HexColor("#6c757d")
        seta_tendencia = "■"

    style_th = ParagraphStyle('Th', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=10, leading=13, textColor=colors.whitesmoke, alignment=1)
    style_td_ano = ParagraphStyle('TdAno', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=10, leading=13, textColor=colors.HexColor("#2c3e50"), alignment=1)
    style_td_pts = ParagraphStyle('TdPts', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=12, leading=15, alignment=1)
    style_td_faixa = ParagraphStyle('TdFaixa', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=12, leading=15, textColor=colors.HexColor("#2e7d32"), alignment=1)
    style_td_var = ParagraphStyle('TdVar', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=12, leading=15, textColor=cor_variacao, alignment=1)

    dados_comparativos = [
        [Paragraph("Exercício", style_th), Paragraph("Pontuação Obtida", style_th), Paragraph("Faixa / Conceito", style_th), Paragraph("Variação Nominal", style_th), Paragraph("Variação Percentual", style_th)],
        [Paragraph(str(ano_ant), style_td_ano), Paragraph(f"{nota_anterior:.1f} pts", style_td_pts), Paragraph(str(faixa_anterior), style_td_faixa), Paragraph("-", style_td_var), Paragraph("-", style_td_var)],
        [Paragraph(str(ano_atual), style_td_ano), Paragraph(f"{nota_atual:.1f} pts", style_td_pts), Paragraph(str(faixa_real_atual), style_td_faixa), Paragraph(f"{seta_tendencia} {variacao_pontos:+.1f} pts", style_td_var), Paragraph(f"{seta_tendencia} {texto_percentual}", style_td_var)]
    ]

    tabela_comp = Table(dados_comparativos, colWidths=[80, 105, 95, 105, 105])
    tabela_comp.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c3e50")), ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#bdc3c7")), 
        ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#f8f9fa")), ("BACKGROUND", (0, 2), (-1, 2), colors.whitesmoke),                    
    ]))
    elements.append(tabela_comp)
    elements.append(Spacer(1, 12))

    style_analise = ParagraphStyle('Analise', parent=styles['Normal'], fontSize=10, leading=14)
    if variacao_pontos > 0:
        texto_analise = f"<b>Análise de Tendência:</b> O município registrou uma evolução de desempenho com incremento de <b>{texto_percentual}</b> na sua pontuação global socioambientais comparado ao exercício de {ano_ant}."
    elif variacao_pontos < 0:
        texto_analise = f"<b>Análise de Tendência:</b> <font color='#dc3545'><b>Alerta de Retrocesso:</b></font> Foi identificada uma redução de <b>{texto_percentual}</b> na eficiência dos indicadores de sustentabilidade e conservação em relação a {ano_ant}."
    else:
        texto_analise = f"<b>Análise de Tendência:</b> O município apresentou estagnação absoluta (0.00%) no seu índice geral de conformidade ambiental."

    elements.append(Paragraph(texto_analise, style_analise))
    elements.append(Spacer(1, 15))

    # =========================================================================
    # 2. ANÁLISE DE DESEMPENHO POR QUESITO
    # =========================================================================
    elements.append(Paragraph("<b>2. ANÁLISE DE DESEMPENHO POR QUESITO</b>", styles["h2"]))
    elements.append(Spacer(1, 6))

    lista_pontos_fortes = []
    lista_pontos_fracos = []
    dados_consolidados = {}

    subquestoes_11 = ["11.2", "11.3", "11.3.2", "11.3.3", "11.5"]
    resposta_11_nao = False
    if "11" in dados and isinstance(dados["11"], dict):
        if str(dados["11"].get("valor", "")).strip().lower() in ["não", "nao", "n"]:
            resposta_11_nao = True

    for sub_id in subquestoes_11:
        if resposta_11_nao or (sub_id not in dados):
            dados[sub_id] = {
                "pontos": 0.0,
                "valor": "Não aplicável / Não implantado (Mãe respondida como Não)",
                "link": ""
            }

    for qid, info in dados.items():
        if qid.startswith("COM_") or not isinstance(info, dict): 
            continue
        
        pts_obtidos = float(info.get("pontos", 0))
        valor_resposta = info.get("valor", "")
        link_evidencia = info.get("link", "")

        qid_str = str(qid).strip()
        
        if qid_str.startswith("A4.1.1_"):   chave_mae = "A4.1.1"
        elif qid_str.startswith("A4.1.2_"): chave_mae = "A4.1.2"
        elif qid_str.startswith("A4.1.3_"): chave_mae = "A4.1.3"
        elif qid_str == "11" or qid_str.startswith("11."):
            if qid_str in PONTUACOES_MAX:
                chave_mae = qid_str
            else:
                chave_mae = "11"
        else:
            chave_mae = qid_str

        if chave_mae not in PONTUACOES_MAX:
            continue

        if chave_mae not in dados_consolidados:
            dados_consolidados[chave_mae] = {"pts_obtidos": 0.0, "valores": [], "links": []}
        
        dados_consolidados[chave_mae]["pts_obtidos"] += pts_obtidos
        
        if valor_resposta:
            sub_nome = qid_str.split('_')[-1] if '_' in qid_str else qid_str
            dados_consolidados[chave_mae]["valores"].append(f"{sub_nome}: {limpar_xml(valor_resposta)}")
            
        if link_evidencia:
            link_limpo = limpar_xml(link_evidencia)
            if link_limpo not in dados_consolidados[chave_mae]["links"]:
                dados_consolidados[chave_mae]["links"].append(link_limpo)

    for qid, info in dados_consolidados.items():
        pts_maximo = float(PONTUACOES_MAX.get(qid, 10.0))
        if pts_maximo <= 0: pts_maximo = 10.0
            
        pts_obtidos = max(0.0, min(info["pts_obtidos"], pts_maximo))
        eficiencia = (pts_obtidos / pts_maximo) * 100
        
        respostas_unificadas = " | ".join(info["valores"]) if info["valores"] else "-"
        evidencias_unificadas = ", ".join(info["links"]) if info["links"] else ""

        item_data = {
            "qid": qid, 
            "pts_obtidos": pts_obtidos, 
            "pts_maximo": pts_maximo, 
            "eficiencia": eficiencia, 
            "valor": respostas_unificadas, 
            "link": evidencias_unificadas
        }

        if eficiencia >= 100.0: 
            lista_pontos_fortes.append(item_data)
        else:
            lista_pontos_fracos.append(item_data)

    if lista_pontos_fortes:
        elements.append(Paragraph("<b>✅ Pontos Fortes Ambientais:</b>", styles["h3"]))
        data_fortes = [[
            Paragraph("Quesito", style_th), 
            Paragraph("Nota / Teto", style_th), 
            Paragraph("Eficiência", style_th), 
            Paragraph("Resposta / Evidência", style_th)
        ]]
        for item in sorted(lista_pontos_fortes, key=lambda x: x["pts_obtidos"], reverse=True):
            texto_celula = f"<b>{item['valor']}</b>"
            if item['link']:
                texto_celula += f"<br/><font size=8 color='gray'>{item['link']}</font>"
            data_fortes.append([
                Paragraph(item['qid'], style_tabela_centro), 
                Paragraph(f"{item['pts_obtidos']:.1f} / {item['pts_maximo']:.1f}", style_tabela_centro), 
                Paragraph(f"{item['eficiencia']:.1f}%", style_tabela_centro), 
                Paragraph(texto_celula, style_tabela_padrao)
            ])
        
        tabela_fortes = Table(data_fortes, colWidths=[65, 75, 65, 285])
        tabela_fortes.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2e7d32")), 
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#2e7d32")), 
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        elements.append(tabela_fortes)
        elements.append(Spacer(1, 12))

    if lista_pontos_fracos:
        elements.append(Paragraph("<b>⚠️ Pontos Fracos / Oportunidades de Melhoria:</b>", styles["h3"]))
        data_fracos = [[
            Paragraph("Quesito", style_th), 
            Paragraph("Nota / Teto", style_th), 
            Paragraph("Eficiência", style_th), 
            Paragraph("Resposta / Evidência", style_th)
        ]]
        for item in sorted(lista_pontos_fracos, key=lambda x: x["eficiencia"]):
            texto_celula = f"<b>{item['valor']}</b>"
            if item['link']:
                texto_celula += f"<br/><font size=8 color='gray'>{item['link']}</font>"
            data_fracos.append([
                Paragraph(item['qid'], style_tabela_centro), 
                Paragraph(f"{item['pts_obtidos']:.1f} / {item['pts_maximo']:.1f}", style_tabela_centro), 
                Paragraph(f"{item['eficiencia']:.1f}%", style_tabela_centro), 
                Paragraph(texto_celula, style_tabela_padrao)
            ])
        
        tabela_fracos = Table(data_fracos, colWidths=[65, 75, 65, 285])
        tabela_fracos.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e67e22")), 
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e67e22")), 
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        elements.append(tabela_fracos)
        elements.append(Spacer(1, 15))

    # =========================================================================
    # 3. ANÁLISE DE IMPACTO E PENALIDADES (EFICIÊNCIA PREVENTIVA)
    # =========================================================================
    elements.append(Paragraph("<b>3. ANÁLISE DE IMPACTO E PENALIDADES (EFICIÊNCIA PREVENTIVA)</b>", styles["h2"]))
    elements.append(Spacer(1, 6))

    PENALIDADES_MAX = {
        "5.2": -15.0, "5.3": -10.0, "7.3.2": -5.0, "7.4.2": -5.0, "7.5.1": -5.0, 
        "8.4.4": -30.0, "9.1": -30.0, "10.0": -100.0, "10.1": -30.0, "14.0": -30.0, "A1": -200.0
    }

    dados_penalidades = dados.copy()
    reincidencias_detectadas = []

    # 🛠️ CORREÇÃO: Se não existir no dicionário, assume 0.0 pontos (não houve penalidade)
    for qid_pen, val_max in PENALIDADES_MAX.items():
        if qid_pen not in dados_penalidades:
            dados_penalidades[qid_pen] = {"pontos": 0.0, "valor": "Não aplicável / Ocultado por condicional", "link": ""}

    lista_penalidades = []
    
    for qid, pen_max in PENALIDADES_MAX.items():
        if qid in dados_penalidades:
            info = dados_penalidades[qid]
            nota_real = float(info.get("pontos", 0.0))
            
            # Garante que apenas valores negativos (penalidades reais) entrem no cálculo do risco
            nota_risco = nota_real if nota_real <= 0.0 else 0.0
            
            if pen_max != 0:
                eficiencia_preventiva = (1.0 - (nota_risco / pen_max)) * 100.0
            else:
                eficiencia_preventiva = 100.0
                
            eficiencia_preventiva = max(0.0, min(eficiencia_preventiva, 100.0))

            lista_penalidades.append({
                "qid": qid, "nota_real": nota_real, "pen_max": pen_max, "eficiencia": eficiencia_preventiva, 
                "valor": info.get("valor", ""), "link": info.get("link", "")
            })
            
            if eficiencia_preventiva < 100.0 and isinstance(dados_ano_anterior, dict) and qid in dados_ano_anterior:
                info_ant = dados_ano_anterior[qid]
                nota_real_ant = float(info_ant.get("pontos", 0.0)) if isinstance(info_ant, dict) else 0.0
                if nota_real == nota_real_ant:
                    reincidencias_detectadas.append({
                        "qid": qid, "tipo": "Penalidade Aplicada", 
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
            # Formatação para não exibir "-0.0 pts" caso o valor venha flutuante negativo zerado
            valor_nota = 0.0 if abs(item['nota_real']) < 0.01 else item['nota_real']
            
            nota_txt = f"{valor_nota:.1f} pts"
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
            
        tabela_pen = Table(data_penalidades, colWidths=[70, 110, 80, 115, 125])
        tabela_pen.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1b4f72")), 
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#1b4f72")), 
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        elements.append(tabela_pen)
        elements.append(Spacer(1, 15))

    # =========================================================================
    # 4. DIAGNÓSTICO DE REINCIDÊNCIAS 
    # =========================================================================
    elements.append(Paragraph("<b>4. DIAGNÓSTICO DE REINCIDÊNCIAS </b>", styles["h2"]))
    elements.append(Spacer(1, 6))
    
    TETOS_VALIDOS = {
        "1.1.2": 20, "1.1.3": 5, "1.2": 20, "2.0": 10, "2.1": 50, "3.0": 10, "3.1": 20, "4.0": 20,
        "5.2.1": 20, "6.0": 20, "6.1": 50, "6.2": 25, "7.2": 2, "7.3": 10, "7.3.1": 20, "7.4": 10,
        "7.4.1": 20, "7.5": 30, "7.7": 30, "7.8": 20, "7.8.1": 50, "7.9": 3, "8.2": 2, "8.3": 10,
        "8.4": 20, "8.4.1": 10, "8.4.2": 30, "8.4.3": 50, "9.2": 100, "9.3": 5, "9.3.1": 5,
        "11.2": 2, "11.3": 30, "11.3.2": 20, "11.3.3": 40, "11.5": 10, "12.1": 54, "14.3": 30,
        "15": 2, "15.1": 3, "A4.1.1": 90, "A4.1.2": 20, "A4.1.3": 22, "A6": 5
    }
    
    dados_analise_reinc = dados.copy()
    
    for sub_id in subquestoes_11:
        if resposta_11_nao or (sub_id not in dados_analise_reinc):
            dados_analise_reinc[sub_id] = {"pontos": 0.0, "valor": "Não", "link": ""}

    for qid, info_atual in dados_analise_reinc.items():
        if qid.startswith("COM_") or not isinstance(info_atual, dict): 
            continue
            
        qid_str = str(qid).strip()
        
        if qid_str.startswith("A4.1.1_"):   chave_mae = "A4.1.1"
        elif qid_str.startswith("A4.1.2_"): chave_mae = "A4.1.2"
        elif qid_str.startswith("A4.1.3_"): chave_mae = "A4.1.3"
        else:                               chave_mae = qid_str
            
        if chave_mae not in TETOS_VALIDOS:
            continue
            
        pts_maximo = float(TETOS_VALIDOS[chave_mae])
        pts_obtidos_atual = float(info_atual.get("pontos", 0.0))
        
        if pts_maximo > 0 and (pts_obtidos_atual / pts_maximo) * 100 < 50.0:
            info_ant = dados_ano_anterior.get(qid, {}) if isinstance(dados_ano_anterior, dict) else {}
            pts_obtidos_ant = float(info_ant.get("pontos", 0.0)) if isinstance(info_ant, dict) else 0.0
            
            if (pts_obtidos_ant / pts_maximo) * 100 < 50.0:
                origem = "Gestão Ambiental Geral"
                if 'CATEGORIAS_MAP' in globals():
                    for cat_chave, cat_info in CATEGORIAS_MAP.items():
                        if chave_mae in cat_info.get("qids", []):
                            origem = cat_info.get("label", "Outros")
                            break
                else:
                    if chave_mae.startswith("1.") or chave_mae.startswith("2.") or chave_mae.startswith("3."):
                        origem = "Planejamento e Infraestrutura"
                    elif chave_mae.startswith("7.") or chave_mae.startswith("8."):
                        origem = "Resíduos e Saneamento"
                    elif chave_mae.startswith("11.") or chave_mae.startswith("12."):
                        origem = "Biodiversidade e Água"
                    elif chave_mae.startswith("A4"):
                        origem = "Indicadores SINISA"
                            
                reincidencias_detectadas.append({
                    "qid": qid_str, 
                    "tipo": origem, 
                    "detalhe": "Ineficiência Crônica de Desempenho (Eficiência inferior a 50% por 2 anos)",
                    "ant": f"{pts_obtidos_ant:.1f} / {pts_maximo:.1f} pts", 
                    "atual": f"{pts_obtidos_atual:.1f} / {pts_maximo:.1f} pts"
                })

    if reincidencias_detectadas:
        data_reinc = [[
            Paragraph("Quesito", style_th), 
            Paragraph("Origem da Falha", style_th), 
            Paragraph("Impacto Histórico", style_th), 
            Paragraph("Exercício Anterior", style_th), 
            Paragraph("Exercício Atual", style_th)
        ]]
        
        def ordenacao_segura(x):
            limpo = ''.join(c for c in x["qid"].split('_')[0] if c.isdigit() or c == '.')
            partes = [int(i) for i in limpo.split('.') if i.isdigit()]
            return partes if partes else [999]

        for reinc in sorted(reincidencias_detectadas, key=ordenacao_segura): 
            data_reinc.append([
                Paragraph(reinc["qid"], style_tabela_centro), 
                Paragraph(reinc["tipo"], style_tabela_centro), 
                Paragraph(f"<b>{reinc['detalhe']}</b>", style_tabela_padrao), 
                Paragraph(reinc["ant"], style_tabela_centro), 
                Paragraph(reinc["atual"], style_tabela_centro)
            ])
            
        tabela_reinc = Table(data_reinc, colWidths=[65, 115, 170, 75, 65])
        tabela_reinc.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#c0392b")), 
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#c0392b")), 
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), 
            ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        elements.append(tabela_reinc)
    else: 
        elements.append(Paragraph("<font color='#2e7d32'><b>✅ Nenhuma reincidência ativa detectada. O município corrigiu ou mitigou as falhas do ano anterior.</b></font>", styles["Normal"]))
        
    elements.append(Spacer(1, 15))
        
    # -------------------------------------------------------------------------
    # 5. ALINHAMENTO COM A AGENDA 2030 (METAS ODS / ONU) - FORMATADO PADRÃO I-GOV
    # -------------------------------------------------------------------------
    import reportlab.lib.colors as rl_colors
    # Mudança radical no nome do import local para extinguir o erro de UnboundLocalError
    from reportlab.lib.styles import ParagraphStyle as Alias_Style

    elements.append(Paragraph("<b>5. ALINHAMENTO COM A AGENDA 2030 (METAS ODS / ONU)</b>", styles["h2"]))
    elements.append(Spacer(1, 6))
    
    def calcular_percentual_checklist(resposta_bruta, total_itens):
        if not resposta_bruta: return 0.0
        itens = [i.strip().lower() for i in str(resposta_bruta).split(",") if i.strip()]
        itens_validos = [i for i in itens if "outros" not in i and i != ""]
        if total_itens > 0:
            return min((len(itens_validos) / total_itens) * 100.0, 100.0)
        return 0.0

    analise_ods = []
    
    # Lista atualizada contendo todos os quesitos novos e existentes
    quesitos_validos_ods = [
        "1.0", "1.1", "1.1.2", "2.0", "3.0", "4.0", "5.0", "6.0", "6.2", "7.0", 
        "7.3", "7.4", "7.5", "7.7.1", "7.8", "7.8.1", "7.9", "8.0", "8.3", 
        "8.3.1", "8.4", "8.4.1", "9.0", "10.0", "10.1", "10.2", "10.3", "11.0", 
        "12.0", "13.0", "14.0", "15.0"
    ]

    for qid in quesitos_validos_ods:
        if qid not in dados: 
            continue
            
        info = dados[qid]
        if qid.startswith("COM_") or not isinstance(info, dict): 
            continue
            
        resp = str(info.get("valor", "")).strip()
        resp_l = resp.lower()
        
        if not resp or resp_l == "não respondido" or resp == "[]": 
            continue

        metas = ""
        status = "Não Atendido"

        # Lógica de Mapeamento do iAMB atualizada
        if qid in ["1.0", "1.1"]:
            metas = "12.2, 15.2, 16.6"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "1.1.2":
            metas = "12.8"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "2.0":
            metas = "4.7, 12.8, 15.1"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "3.0":
            metas = "12.2, 16.6, 17.14"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "4.0":
            metas = "12.4"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "5.0":
            metas = "5.0"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "6.0":
            metas = "6.4, 6.b, 16.6"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "6.2":
            metas = "6.4, 6.5, 6.b, 16.6"
            pct = calcular_percentual_checklist(resp, 3)
            status = f"{pct:.1f}% Atendido"
        elif qid == "7.0":
            metas = "6.0, 16.6"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "7.3":
            metas = "6.0, 16.6"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid in ["7.4", "7.5"]:
            metas = "6.2, 6.3"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "7.7.1":
            metas = "6.0, 16.6"
            pct = calcular_percentual_checklist(resp, 3)
            status = f"{pct:.1f}% Atendido"
        elif qid == "7.8":
            metas = "6.0, 16.6"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "7.8.1":
            metas = "6.2, 6.3"
            status = "Atendido" if "todas as metas foram cumpridas dentro do prazo" in resp_l else "Não Atendido"
        elif qid == "7.9":
            metas = "6.2, 6.3"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid in ["8.0", "8.3", "8.4", "9.0"]:
            metas = "11.6, 12.5"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "8.3.1":
            metas = "11.6, 12.5, 12.4"
            pct = calcular_percentual_checklist(resp, 3)
            status = f"{pct:.1f}% Atendido"
        elif qid == "8.4.1":
            metas = "11.6, 12.5, 12.4"
            pct = calcular_percentual_checklist(resp, 4)
            status = f"{pct:.1f}% Atendido"
        elif qid in ["10.0", "10.1"]:
            metas = "11.6, 12.5, 16.6"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "10.2":
            metas = "11.6, 12.5, 16.6"
            status = "Atendido" if "todos os bairros do município são atendidos" in resp_l else "Não Atendido"
        elif qid == "10.3":
            metas = "11.6, 12.5, 12.4, 16.6"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "11.0":
            metas = "11.6, 12.4, 12.5, 16.6"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "12.0":
            metas = "11.6, 12.5, 12.4"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "13.0":
            metas = "11.6, 12.4"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
        elif qid == "14.0":
            # 🔄 Lógica Inversa solicitada para o quesito 14.0
            metas = "11.6, 12.4"
            status = "Atendido" if "não" in resp_l else "Não Atendido"
        elif qid == "15.0":
            metas = "12.0, 16.6"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"

        # Trata tamanho da string da diretriz para não quebrar o layout
        exibicao_resp = limpar_xml(resp)
        if len(exibicao_resp) > 45:
            exibicao_resp = exibicao_resp[:45] + "..."

        analise_ods.append({
            "qid": qid,
            "metas": metas,
            "resp": exibicao_resp,
            "status": status
        })

    if analise_ods:
        data_ods = [["Quesito", "Diretriz Declarada", "Vínculo Metas ODS", "Status de Alinhamento"]]
        style_td_ods = Alias_Style('TdOds', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=9, alignment=1)
        
        # Ordenação correta dos quesitos (ex: 1.0, 1.1, 1.1.2, 2.0...)
        for item in sorted(analise_ods, key=lambda x: [float(i) if i.replace('.','',1).isdigit() else 999 for i in x['qid'].split('.')]):
            st_txt = item["status"]
            
            # Formatação de Cores Dinâmicas para o Status igual ao iGov
            if "Não Atendido" in st_txt:
                st_p = Paragraph(f"<font color='#dc3545'><b>{st_txt}</b></font>", style_td_ods)
            elif "Atendido" in st_txt and "%" not in st_txt:
                st_p = Paragraph(f"<font color='#28a745'><b>{st_txt}</b></font>", style_td_ods)
            else:
                st_p = Paragraph(f"<font color='#007bff'><b>{st_txt}</b></font>", style_td_ods)
                
            data_ods.append([
                Paragraph(f"<b>{item['qid']}</b>", style_tabela_centro), 
                Paragraph(item["resp"], style_tabela_padrao), 
                Paragraph(item["metas"], style_tabela_centro), 
                st_p
            ])
            
        tabela_ods = Table(data_ods, colWidths=[55, 210, 115, 110])
        tabela_ods.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), rl_colors.HexColor("#0f9d58")), # Verde institucional do iGov aplicado aqui
            ("TEXTCOLOR", (0, 0), (-1, 0), rl_colors.whitesmoke), 
            ("ALIGN", (0, 0), (0, -1), "CENTER"), 
            ("GRID", (0, 0), (-1, -1), 0.5, rl_colors.HexColor("#0f9d58")), 
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        elements.append(tabela_ods)
        elements.append(Spacer(1, 15))

    # -------------------------------------------------------------------------
    # 📊 6. SÉRIE HISTÓRICA DO IAMB (CONSOLIDADO FINAL)
    # -------------------------------------------------------------------------
    from reportlab.graphics.shapes import Drawing, String
    from reportlab.graphics.charts.barcharts import VerticalBarChart

    elements.append(Spacer(1, 10))
    elements.append(Paragraph("<b>6. SÉRIE HISTÓRICA DO IAMB (CONSOLIDADO FINAL)</b>", styles["h2"]))
    elements.append(Spacer(1, 10))

    anos_serie = [2023, 2024, 2025, 2026, 2027, 2028, 2029, 2030]
    valores_serie = []
    
    # Captura do ano atual de forma segura
    ano_reference = None
    for nome_var in ['ano_sel', 'ano_atual', 'ano', 'exercicio']:
        if nome_var in locals():
            ano_reference = locals()[nome_var]
            break
    if ano_reference is None:
        ano_reference = 2026

    # Captura da nota atual (calculada no início do seu compilador)
    nota_reference = 0.0
    for nome_var in ['total_pts', 'nota_atual', 'pontuacao_final', 'total']:
        if nome_var in locals():
            try:
                nota_reference = float(locals()[nome_var])
                break
            except (ValueError, TypeError):
                continue

    import streamlit as st
    
    # Captura segura da variável all_data sem disparar NameError
    var_all_data = locals().get('all_data', globals().get('all_data', None))

    # Montagem do array de dados para o Gráfico
    for a in anos_serie:
        if a == 0 or a == "0":
            valores_serie.append(0.0)
        elif a == ano_reference: 
            valores_serie.append(min(nota_reference, 100.0) if nota_reference <= 100.0 else min(nota_reference, 1000.0))
        elif var_all_data and a in var_all_data:
            dados_ano = var_all_data[a]
            if isinstance(dados_ano, dict):
                pontos_ano = float(sum(info_h.get("pontos", 0.0) for qid_h, info_h in dados_ano.items() if isinstance(info_h, dict) and not qid_h.startswith("COM_")))
                valores_serie.append(pontos_ano)
            else:
                valores_serie.append(float(dados_ano))
        elif hasattr(st, 'session_state') and 'all_data' in st.session_state and a in st.session_state.all_data:
            dados_ano = st.session_state.all_data[a]
            if isinstance(dados_ano, dict):
                pontos_ano = float(sum(info_h.get("pontos", 0.0) for qid_h, info_h in dados_ano.items() if isinstance(info_h, dict) and not qid_h.startswith("COM_")))
                valores_serie.append(pontos_ano)
            else:
                valores_serie.append(float(dados_ano))
        else: 
            valores_serie.append(0.0)

    # Identifica se a escala do iAMB é até 100 ou até 1000 para ajustar o gráfico dinamicamente
    max_escala = 1000 if any(v > 100 for v in valores_serie) else 100
    passo_escala = 200 if max_escala == 1000 else 20

    # Configuração e renderização do Gráfico do iAMB
    desenho_grafico = Drawing(480, 165)
    bc = VerticalBarChart()
    bc.x = 45
    bc.y = 25
    bc.height = 110
    bc.width = 410
    bc.data = [valores_serie]
    bc.categoryAxis.categoryNames = [str(a) for a in anos_serie]
    bc.categoryAxis.labels.fontSize = 9
    bc.categoryAxis.labels.fontName = 'Helvetica-Bold'
    bc.categoryAxis.labels.dy = -10
    
    bc.valueAxis.valueMin = 0
    bc.valueAxis.valueMax = max_escala
    bc.valueAxis.valueStep = passo_escala
    bc.valueAxis.labels.fontSize = 8
    
    # Ativação dos rótulos acima das barras
    bc.barLabels.nudge = 8
    bc.barLabels.fontSize = 8
    bc.barLabels.fontName = 'Helvetica-Bold'
    bc.barLabelFormat = '%.1f'
    
    # Customização de cor temática azul-escura/institucional
    bc.bars[0].fillColor = rl_colors.HexColor("#1b4f72")
    bc.bars[0].strokeColor = rl_colors.HexColor("#2c3e50")
    bc.bars[0].strokeWidth = 0.5

    desenho_grafico.add(String(240, 150, "Série Histórica de Evolução do iAMB", textAnchor='middle', fontName='Helvetica-Bold', fontSize=12, fillColor=rl_colors.HexColor("#2c3e50")))
    desenho_grafico.add(bc)
    
    elements.append(desenho_grafico)
    elements.append(Spacer(1, 15))

    # =========================================================================
    # FIM DA FUNÇÃO: GERAÇÃO E RETORNO SEGURO DO BUFFER
    # =========================================================================
    doc.build(elements)
    buffer.seek(0)
    return buffer

# =============================================================================
# 4. FORMULÁRIO PRINCIPAL E ABAS
# =============================================================================

def mostrar_formulario_amb():
    init_db()
    total_pts, res_data, ano_sel = render_sidebar()
    
    st.markdown("""
        <style>
        .quesito-card {
            background-color: #f0f4f0;
            padding: 20px;
            border-left: 6px solid #2e7d32;
            border-radius: 8px;
            margin-bottom: 20px;
            border: 1px solid #c8e6c9;
        }
        .externo-card {
            background-color: #f0f7ff;
            padding: 20px;
            border-left: 6px solid #007bff;
            border-radius: 8px;
            margin-bottom: 20px;
            border: 1px solid #cce5ff;
        }
        </style>
    """, unsafe_allow_html=True)

    st.title(f"🍃 Auditoria i-AMB (Meio Ambiente) - {ano_sel}")
    
    aba_quest, aba_ext, aba_graf = st.tabs(["📋 Questionário", "📊 Dados Externos", "📈 Gráficos"])
    
    with aba_quest:
        # --- SEÇÃO 1: ESTRUTURA ---
        st.header("1.0 Estrutura Organizacional")

        # =============================================================================
        # GATILHOS DOS MODAIS AUTOMÁTICOS (Colocar junto aos outros modais no topo)
        # =============================================================================
        if st.session_state.get(f"gatilho_modal_1_0_{ano_sel}", False):
                modal_aviso_link("1.0", st.session_state.get(f"links_pendentes_1_0_{ano_sel}", []))
                st.session_state[f"gatilho_modal_1_0_{ano_sel}"] = False


        # =============================================================================
        # QUESITO 1.0 • ESTRUTURA AMBIENTAL MUNICIPAL
        # =============================================================================
        with st.container(key=f"container_bloco_ambiental_1_0_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 1.0 - Estrutura Organizacional Ambiental", expanded=True):
                        st.subheader("1.0 • Estrutura Ambiental")
                        st.write("**A prefeitura possui alguma estrutura organizacional para tratar de assuntos ligados ao Meio Ambiente Municipal?**")
                        st.caption("ℹ *Atenção à consistência dos dados salvos no banco. Salvamento automático.*")

                        opc10 = ["Selecione...", "Sim", "Não"]
                        d10 = res_data.get("1.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        if d10 is None: d10 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                        v_salvo_10 = d10.get("valor", "Selecione...")
                        if v_salvo_10 not in opc10: v_salvo_10 = "Selecione..."
                        
                        evidencia_10_salva = d10.get("link", "")
                        chave_radio_10 = f"r_10_select_{ano_sel}"
                        chave_link_10 = f"l_10_txt_area_{ano_sel}"

                        def cb_processa_e_salva_10():
                                lnk_val = st.session_state.get(chave_link_10, evidencia_10_salva).strip()
                                val_salvar = st.session_state.get(chave_radio_10, v_salvo_10)
                                
                                save_resp("1.0", val_salvar, 0.0, lnk_val)
                                res_data["1.0"] = {"valor": val_salvar, "pontos": 0.0, "link": lnk_val}

                                # Ativação segura do modal para links novos detectados sem quebrar o fluxo
                                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk_val or "")]
                                links_antigos = [u[0] for u in re.findall(regex_pure_url, evidencia_10_salva or "")]
                                if lnk_val != evidencia_10_salva and links_atuais and links_atuais != links_antigos:
                                        st.session_state[f"links_pendentes_1_0_{ano_sel}"] = links_atuais
                                        st.session_state[f"gatilho_modal_1_0_{ano_sel}"] = True

                        col1, col2 = st.columns([1, 1])
                        with col1:
                                idx10 = opc10.index(v_salvo_10)
                                st.radio(
                                        "Selecione uma opção (1.0):",
                                        options=opc10,
                                        index=idx10,
                                        key=chave_radio_10,
                                        on_change=cb_processa_e_salva_10
                                )

                        with col2:
                                link_10 = st.text_area(
                                        "Link/Evidência (1.0):",
                                        value=evidencia_10_salva,
                                        key=chave_link_10,
                                        on_change=cb_processa_e_salva_10,
                                        placeholder="Insira o link oficial do organograma ou lei da estrutura ambiental...",
                                        height=110
                                )
                                placeholder_links_10 = st.empty()
                                links_10_visuais = [u[0] for u in re.findall(regex_pure_url, link_10 or "")]
                                if links_10_visuais:
                                        placeholder_links_10.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_10_visuais]))

                        v_atual_10 = st.session_state.get(chave_radio_10, v_salvo_10)
                        cor_txt_10 = "#28a745" if v_atual_10 == "Sim" else ("#dc3545" if v_atual_10 == "Não" else "#6c757d")
                        st.markdown(f"<span style='color:{cor_txt_10}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 1.0: +0.0 pontos</span>", unsafe_allow_html=True)
                        bloco_comentarios("1.0", res_data, ano_sel)


       # =============================================================================
        # GATILHOS DOS MODAIS AUTOMÁTICOS (Colocar no bloco de modais no topo)
        # =============================================================================
        if st.session_state.get(f"gatilho_modal_1_1_{ano_sel}", False):
                modal_aviso_link("1.1", st.session_state.get(f"links_pendentes_1_1_{ano_sel}", []))
                st.session_state[f"gatilho_modal_1_1_{ano_sel}"] = False

        if st.session_state.get(f"gatilho_modal_1_1_2_{ano_sel}", False):
                modal_aviso_link("1.1.2", st.session_state.get(f"links_pendentes_1_1_2_{ano_sel}", []))
                st.session_state[f"gatilho_modal_1_1_2_{ano_sel}"] = False

        if st.session_state.get(f"gatilho_modal_1_1_3_{ano_sel}", False):
                modal_aviso_link("1.1.3", st.session_state.get(f"links_pendentes_1_1_3_{ano_sel}", []))
                st.session_state[f"gatilho_modal_1_1_3_{ano_sel}"] = False

# =============================================================================
        # QUESITO 1.1 • DISPONIBILIDADE DE RECURSOS HUMANOS (CORRIGIDO)
        # =============================================================================
        with st.container(key=f"container_bloco_rh_1_1_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 1.1 - Recursos Humanos Operacionais", expanded=True):
                        st.subheader("1.1 • Recursos Humanos")
                        st.write("**A Prefeitura possui recursos humanos para operacionalização dos assuntos ligados ao Meio Ambiente?**")
                        st.caption("ℹ *Atenção à consistência dos dados salvos no banco. Salvamento automático.*")

                        opc11 = ["Selecione...", "Sim", "Não"]
                        d11 = res_data.get("1.1", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        if d11 is None: d11 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                        v_salvo_11 = d11.get("valor", "Selecione...")
                        if v_salvo_11 not in opc11: v_salvo_11 = "Selecione..."
                        
                        evidencia_11_salva = d11.get("link", "")
                        chave_radio_11 = f"r_11_select_{ano_sel}"
                        chave_link_11 = f"l_11_txt_area_{ano_sel}"

                        def cb_processa_e_salva_11():
                                lnk_val = st.session_state.get(chave_link_11, evidencia_11_salva).strip()
                                val_salvar = st.session_state.get(chave_radio_11, v_salvo_11)
                                
                                save_resp("1.1", val_salvar, 0.0, lnk_val)
                                res_data["1.1"] = {"valor": val_salvar, "pontos": 0.0, "link": lnk_val}

                                # CORREÇÃO AQUI: Alinhando os nomes das chaves com o gatilho do topo do script (1_1)
                                links_atuais = re.findall(r'(https?://[^\s]+)', lnk_val or "")
                                links_antigos = re.findall(r'(https?://[^\s]+)', evidencia_11_salva or "")
                                if lnk_val != evidencia_11_salva and links_atuais and links_atuais != links_antigos:
                                        st.session_state[f"links_pendentes_1_1_{ano_sel}"] = links_atuais
                                        st.session_state[f"gatilho_modal_1_1_{ano_sel}"] = True

                        col1, col2 = st.columns([1, 1])
                        with col1:
                                idx11 = opc11.index(v_salvo_11)
                                st.radio(
                                        "Selecione uma opção (1.1):",
                                        options=opc11,
                                        index=idx11,
                                        key=chave_radio_11,
                                        on_change=cb_processa_e_salva_11
                                )

                        with col2:
                                link_11 = st.text_area(
                                        "Link/Evidência (1.1):",
                                        value=evidencia_11_salva,
                                        key=chave_link_11,
                                        on_change=cb_processa_e_salva_11,
                                        placeholder="Insira o link com a relação de servidores, portarias de alocação, etc...",
                                        height=110
                                )
                                placeholder_links_11 = st.empty()
                                links_11_visuais = re.findall(r'(https?://[^\s]+)', link_11 or "")
                                if links_11_visuais:
                                        placeholder_links_11.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_11_visuais]))

                        v_atual_11 = st.session_state.get(chave_radio_11, v_salvo_11)
                        cor_txt_11 = "#28a745" if v_atual_11 == "Sim" else ("#dc3545" if v_atual_11 == "Não" else "#6c757d")
                        st.markdown(f"<span style='color:{cor_txt_11}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 1.1: +0.0 pontos</span>", unsafe_allow_html=True)
                        bloco_comentarios("1.1", res_data, ano_sel)
# =============================================================================
        # GATILHO DO MODAL AUTOMÁTICO DO QUESITO 1.1.1 (Colocar junto aos outros no topo)
        # =============================================================================
        if st.session_state.get(f"gatilho_modal_1_1_1_{ano_sel}", False):
                modal_aviso_link("1.1.1", st.session_state.get(f"links_pendentes_1_1_1_{ano_sel}", []))
                st.session_state[f"gatilho_modal_1_1_1_{ano_sel}"] = False


        # =============================================================================
        # QUESITO 1.1.1 • QUANTIDADE DE PESSOAL (RH) COM EVIDÊNCIA E MODAL
        # =============================================================================
        with st.container(key=f"container_bloco_rh_1_1_1_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 1.1.1 - Quadro Quantitativo de Servidores", expanded=True):
                        st.subheader("1.1.1 • Detalhamento Quantitativo de Pessoal")
                        st.write("**Informe a quantidade de pessoal alocado nas operações do Meio Ambiente:**")
                        st.caption("ℹ *Os dados são totalizados e estruturados automaticamente. Salvamento automático.*")

                        # Recupera o dicionário ou cria um padrão vazio estruturado
                        d111 = res_data.get("1.1.1", {"valor": "0", "pontos": 0.0, "link": "E:0, C:0, T:0 | Evidência: "})
                        if d111 is None: d111 = {"valor": "0", "pontos": 0.0, "link": "E:0, C:0, T:0 | Evidência: "}

                        # Faz o parse seguro dos valores numéricos salvos e do texto da evidência
                        string_banco = d111.get("link", "E:0, C:0, T:0 | Evidência: ")
                        try:
                                if " | Evidência: " in string_banco:
                                        parte_numeros, evidencia_111_salva = string_banco.split(" | Evidência: ", 1)
                                else:
                                        parte_numeros, evidencia_111_salva = string_banco, ""
                                
                                parts = parte_numeros.split(",")
                                v_efe = int(parts[0].split(":")[1])
                                v_com = int(parts[1].split(":")[1])
                                v_ter = int(parts[2].split(":")[1])
                        except:
                                v_efe, v_com, v_ter = 0, 0, 0
                                evidencia_111_salva = ""

                        chave_efe = f"q111_efe_num_{ano_sel}"
                        chave_com = f"q111_com_num_{ano_sel}"
                        chave_ter = f"q111_ter_num_{ano_sel}"
                        chave_link_111 = f"l_111_txt_area_{ano_sel}"

                        def cb_processa_e_salva_111():
                                n_efe = st.session_state.get(chave_efe, v_efe)
                                n_com = st.session_state.get(chave_com, v_com)
                                n_ter = st.session_state.get(chave_ter, v_ter)
                                lnk_val = st.session_state.get(chave_link_111, evidencia_111_salva).strip()
                                
                                total_rh = n_efe + n_com + n_ter
                                # Salva a estrutura de forma que não quebre os parses futuros
                                str_formatada_banco = f"E:{n_efe}, C:{n_com}, T:{n_ter} | Evidência: {lnk_val}"
                                
                                save_resp("1.1.1", str(total_rh), 0.0, str_formatada_banco)
                                res_data["1.1.1"] = {"valor": str(total_rh), "pontos": 0.0, "link": str_formatada_banco}

                                # Verificação e disparo do modal de link
                                links_atuais = re.findall(r'(https?://[^\s]+)', lnk_val or "")
                                links_antigos = re.findall(r'(https?://[^\s]+)', evidencia_111_salva or "")
                                if lnk_val != evidencia_111_salva and links_atuais and links_atuais != links_antigos:
                                        st.session_state[f"links_pendentes_1_1_1_{ano_sel}"] = links_atuais
                                        st.session_state[f"gatilho_modal_1_1_1_{ano_sel}"] = True

                        col1, col2 = st.columns([1, 1])
                        with col1:
                                st.number_input("Servidores Efetivos:", min_value=0, value=v_efe, key=chave_efe, on_change=cb_processa_e_salva_111)
                                st.number_input("Cargos Comissionados:", min_value=0, value=v_com, key=chave_com, on_change=cb_processa_e_salva_111)
                                st.number_input("Profissionais Terceirizados:", min_value=0, value=v_ter, key=chave_ter, on_change=cb_processa_e_salva_111)

                        with col2:
                                total_atual = st.session_state.get(chave_efe, v_efe) + st.session_state.get(chave_com, v_com) + st.session_state.get(chave_ter, v_ter)
                                st.info(f"👥 **Força de Trabalho Total Calculada:** {total_atual} colaboradores")
                                
                                link_111 = st.text_area(
                                        "Link/Evidência (1.1.1):",
                                        value=evidencia_111_salva,
                                        key=chave_link_111,
                                        on_change=cb_processa_e_salva_111,
                                        placeholder="Insira o link do diário oficial, portal da transparência ou documento comprobatório do quadro...",
                                        height=115
                                )
                                placeholder_links_111 = st.empty()
                                links_111_visuais = re.findall(r'(https?://[^\s]+)', link_111 or "")
                                if links_111_visuais:
                                        placeholder_links_111.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_111_visuais]))

                        st.markdown(f"<span style='color:#28a745; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 1.1.1: +0.0 pontos</span>", unsafe_allow_html=True)
                        bloco_comentarios("1.1.1", res_data, ano_sel)

        # =============================================================================
        # QUESITO 1.1.2 • TREINAMENTO ESPECÍFICO
        # =============================================================================
        with st.container(key=f"container_bloco_rh_1_1_2_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 1.1.2 - Capacitação da Equipe Técnica", expanded=True):
                        st.subheader("1.1.2 • Treinamiento Específico")
                        ano_anterior = int(ano_sel) - 1
                        st.write(f"**Os servidores responsáveis pelo Meio Ambiente receberam treinamento específico voltado ao Meio Ambiente em {ano_anterior}?**")
                        st.caption("ℹ *Atenção à consistência dos dados salvos no banco. Salvamento automático.*")

                        opc112 = ["Selecione...", "Sim – 20", "Não – 00"]
                        d112 = res_data.get("1.1.2", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        if d112 is None: d112 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                        v_salvo_112 = d112.get("valor", "Selecione...")
                        if v_salvo_112 not in opc112: v_salvo_112 = "Selecione..."

                        evidencia_112_salva = d112.get("link", "")
                        chave_radio_112 = f"r_112_select_{ano_sel}"
                        chave_link_112 = f"l_112_txt_area_{ano_sel}"

                        def cb_processa_e_salva_112():
                                lnk_val = st.session_state.get(chave_link_112, evidencia_112_salva).strip()
                                val_salvar = st.session_state.get(chave_radio_112, v_salvo_112)
                                
                                pts_calculados = 20.0 if "Sim" in str(val_salvar) else 0.0
                                save_resp("1.1.2", val_salvar, pts_calculados, lnk_val)
                                res_data["1.1.2"] = {"valor": val_salvar, "pontos": pts_calculados, "link": lnk_val}

                                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk_val or "")]
                                links_antigos = [u[0] for u in re.findall(regex_pure_url, evidencia_112_salva or "")]
                                if lnk_val != evidencia_112_salva and links_atuais and links_atuais != links_antigos:
                                        st.session_state[f"links_pendentes_1_1_2_{ano_sel}"] = links_atuais
                                        st.session_state[f"gatilho_modal_1_1_2_{ano_sel}"] = True

                        col1, col2 = st.columns([1, 1])
                        with col1:
                                idx112 = opc112.index(v_salvo_112)
                                st.radio(
                                        "Selecione uma opção (1.1.2):",
                                        options=opc112,
                                        index=idx112,
                                        key=chave_radio_112,
                                        on_change=cb_processa_e_salva_112
                                )

                        with col2:
                                link_112 = st.text_area(
                                        "Link/Evidência (1.1.2):",
                                        value=evidencia_112_salva,
                                        key=chave_link_112,
                                        on_change=cb_processa_e_salva_112,
                                        placeholder="Insira os certificados, portarias de cursos ou listas de presença...",
                                        height=110
                                )
                                placeholder_links_112 = st.empty()
                                links_112_visuais = [u[0] for u in re.findall(regex_pure_url, link_112 or "")]
                                if links_112_visuais:
                                        placeholder_links_112.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_112_visuais]))

                        v_atual_112 = st.session_state.get(chave_radio_112, v_salvo_112)
                        cor_txt_112 = "#28a745" if "Sim" in str(v_atual_112) else ("#dc3545" if "Não" in str(v_atual_112) else "#6c757d")
                        pts_atuais_112 = 20.0 if "Sim" in str(v_atual_112) else 0.0
                        st.markdown(f"<span style='color:{cor_txt_112}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 1.1.2: +{pts_atuais_112} pontos</span>", unsafe_allow_html=True)
                        bloco_comentarios("1.1.2", res_data, ano_sel)


        # =============================================================================
        # QUESITO 1.1.3 • CURSOS DE EDUCAÇÃO AMBIENTAL OFERECIDOS
        # =============================================================================
        with st.container(key=f"container_bloco_rh_1_1_3_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 1.1.3 - Cursos e Treinamentos Oferecidos à Comunidade", expanded=True):
                        st.subheader("1.1.3 • Educação Ambiental")
                        st.write("**A Secretaria Municipal de Meio Ambiente ou similar ofereceu cursos/treinamento sobre educação ambiental para qual público?**")
                        st.caption("ℹ *Marque todas as opções aplicáveis. Salvamento automático.*")

                        opts113 = {
                                "Para escolas – 05": 5.0, 
                                "Para outras secretarias / entidades municipais – 02": 2.0, 
                                "Para munícipes ou empresas – 03": 3.0, 
                                "Não ofereceu nenhum curso/treinamento no ano – 00": 0.0
                        }

                        d113 = res_data.get("1.1.3", {"valor": "[]", "pontos": 0.0, "link": ""})
                        if d113 is None: d113 = {"valor": "[]", "pontos": 0.0, "link": ""}

                        texto_seguro_113 = str(d113.get("valor", "[]"))
                        evidencia_113_salva = d113.get("link", "")
                        
                        chave_link_113 = f"l_113_txt_area_{ano_sel}"

                        def cb_processa_e_salva_113():
                                # Coleta os valores selecionados mapeando os checkboxes ativos da session_state
                                lista_selecionados = []
                                pts_totais = 0.0
                                for txt, pts in opts113.items():
                                        if st.session_state.get(f"ck_113_{txt}_{ano_sel}", False):
                                                lista_selecionados.append(txt)
                                                pts_totais += pts
                                
                                lnk_val = st.session_state.get(chave_link_113, evidencia_113_salva).strip()
                                val_salvar = str(lista_selecionados)
                                
                                save_resp("1.1.3", val_salvar, pts_totais, lnk_val)
                                res_data["1.1.3"] = {"valor": val_salvar, "pontos": pts_totais, "link": lnk_val}

                                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk_val or "")]
                                links_antigos = [u[0] for u in re.findall(regex_pure_url, evidencia_113_salva or "")]
                                if lnk_val != evidencia_113_salva and links_atuais and links_atuais != links_antigos:
                                        st.session_state[f"links_pendentes_1_1_3_{ano_sel}"] = links_atuais
                                        st.session_state[f"gatilho_modal_1_1_3_{ano_sel}"] = True

                        col1, col2 = st.columns([1, 1])
                        with col1:
                                st.write("*Selecione os públicos-alvo atendidos:*")
                                for txt, pts in opts113.items():
                                        marcado = (txt in texto_seguro_113) if texto_seguro_113 and texto_seguro_113 != "[]" else False
                                        st.checkbox(
                                                txt,
                                                value=marcado,
                                                key=f"ck_113_{txt}_{ano_sel}",
                                                on_change=cb_processa_e_salva_113
                                        )

                        with col2:
                                link_113 = st.text_area(
                                        "Link/Evidência (1.1.3):",
                                        value=evidencia_113_salva,
                                        key=chave_link_113,
                                        on_change=cb_processa_e_salva_113,
                                        placeholder="Links de fotos de divulgação, diário oficial, decretos ou notícias dos cursos...",
                                        height=150
                                )
                                placeholder_links_113 = st.empty()
                                links_113_visuais = [u[0] for u in re.findall(regex_pure_url, link_113 or "")]
                                if links_113_visuais:
                                        placeholder_links_113.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_113_visuais]))

                        # Calcula pontos em tempo real para feedback visual
                        pts_feedback = 0.0
                        for txt, pts in opts113.items():
                                if st.session_state.get(f"ck_113_{txt}_{ano_sel}", False):
                                        pts_feedback += pts

                        cor_txt_113 = "#28a745" if pts_feedback > 0 else "#6c757d"
                        st.markdown(f"<span style='color:{cor_txt_113}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 1.1.3: +{pts_feedback} pontos</span>", unsafe_allow_html=True)
                        bloco_comentarios("1.1.3", res_data, ano_sel)

        # =============================================================================
        # GATILHO DO MODAL AUTOMÁTICO DO QUESITO 1.2 (Colocar no bloco de modais no topo)
        # =============================================================================
        if st.session_state.get(f"gatilho_modal_1_2_{ano_sel}", False):
                modal_aviso_link("1.2", st.session_state.get(f"links_pendentes_1_2_{ano_sel}", []))
                st.session_state[f"gatilho_modal_1_2_{ano_sel}"] = False


        # =============================================================================
        # QUESITO 1.2 • RECURSOS DISPONIBILIZADOS (EXCETO RH E ESTRUTURA FÍSICA)
        # =============================================================================
        with st.container(key=f"container_bloco_recursos_1_2_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 1.2 - Recursos Disponibilizados Operacionais", expanded=True):
                        st.subheader("1.2 • Recursos Operacionais")
                        st.write("**Assinale os recursos disponibilizados para a operacionalização das atividades de meio ambiente: Não considerar Recursos Humanos e Estrutura Física nesta questão.**")
                        st.caption("ℹ *Marque todas as opções aplicáveis. Salvamento automático.*")

                        opts12 = ["Recursos Tecnológicos – 05", "Recursos Orçamentários – 05", "Recursos Materiais – 05", "Outros – 05"]

                        d12 = res_data.get("1.2", {"valor": "[]", "pontos": 0.0, "link": ""})
                        if d12 is None: d12 = {"valor": "[]", "pontos": 0.0, "link": ""}

                        texto_seguro_12 = str(d12.get("valor", "[]"))
                        evidencia_12_salva = d12.get("link", "")
                        
                        chave_link_12 = f"l_12_txt_area_{ano_sel}"

                        def cb_processa_e_salva_12():
                                # Coleta os estados dos checkboxes em tempo de execução
                                lista_selecionados = []
                                pts_totais = 0.0
                                for opt in opts12:
                                        if st.session_state.get(f"ck_12_{opt}_{ano_sel}", False):
                                                lista_selecionados.append(opt)
                                                pts_totais += 5.0
                                
                                lnk_val = st.session_state.get(chave_link_12, evidencia_12_salva).strip()
                                val_salvar = str(lista_selecionados)
                                
                                save_resp("1.2", val_salvar, pts_totais, lnk_val)
                                res_data["1.2"] = {"valor": val_salvar, "pontos": pts_totais, "link": lnk_val}

                                # Verificação do modal para novos links adicionados
                                links_atuais = re.findall(r'(https?://[^\s]+)', lnk_val or "")
                                links_antigos = re.findall(r'(https?://[^\s]+)', evidencia_12_salva or "")
                                if lnk_val != evidencia_12_salva and links_atuais and links_atuais != links_antigos:
                                        st.session_state[f"links_pendentes_1_2_{ano_sel}"] = links_atuais
                                        st.session_state[f"gatilho_modal_1_2_{ano_sel}"] = True

                        col1, col2 = st.columns([1, 1])
                        with col1:
                                st.write("*Selecione os recursos ativos:*")
                                for opt in opts12:
                                        marcado = (opt in texto_seguro_12) if texto_seguro_12 and texto_seguro_12 != "[]" else False
                                        st.checkbox(
                                                opt,
                                                value=marcado,
                                                key=f"ck_12_{opt}_{ano_sel}",
                                                on_change=cb_processa_e_salva_12
                                        )

                        with col2:
                                link_12 = st.text_area(
                                        "Link/Evidência (1.2):",
                                        value=evidencia_12_salva,
                                        key=chave_link_12,
                                        on_change=cb_processa_e_salva_12,
                                        placeholder="Links da LOA/QDD para orçamento, notas fiscais ou inventário de sistemas/materiais...",
                                        height=150
                                )
                                placeholder_links_12 = st.empty()
                                links_12_visuais = re.findall(r'(https?://[^\s]+)', link_12 or "")
                                if links_12_visuais:
                                        placeholder_links_12.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_12_visuais]))

                        # Calcula o feedback visual dos pontos baseado no estado atual da session_state
                        pts_feedback = 0.0
                        for opt in opts12:
                                if st.session_state.get(f"ck_12_{opt}_{ano_sel}", False):
                                        pts_feedback += 5.0

                        cor_txt_12 = "#28a745" if pts_feedback > 0 else "#6c757d"
                        st.markdown(f"<span style='color:{cor_txt_12}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 1.2: +{pts_feedback} pontos</span>", unsafe_allow_html=True)
                        bloco_comentarios("1.2", res_data, ano_sel)

        # --- SEÇÃO 2: EDUCAÇÃO AMBIENTAL ---
        st.divider()
        st.header("2.0 Educação Ambiental")
        
       # =============================================================================
        # GATILHOS DOS MODAIS AUTOMÁTICOS (Colocar no bloco de modais no topo do arquivo)
        # =============================================================================
        if st.session_state.get(f"gatilho_modal_2_0_{ano_sel}", False):
                modal_aviso_link("2.0", st.session_state.get(f"links_pendentes_2_0_{ano_sel}", []))
                st.session_state[f"gatilho_modal_2_0_{ano_sel}"] = False

        if st.session_state.get(f"gatilho_modal_2_1_{ano_sel}", False):
                modal_aviso_link("2.1", st.session_state.get(f"links_pendentes_2_1_{ano_sel}", []))
                st.session_state[f"gatilho_modal_2_1_{ano_sel}"] = False


        # =============================================================================
        # QUESITO 2.0 • PARTICIPAÇÃO EM PROGRAMA DE EDUCAÇÃO AMBIENTAL
        # =============================================================================
        with st.container(key=f"container_bloco_prog_2_0_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 2.0 - Programa de Educação Ambiental", expanded=True):
                        st.subheader("2.0 • Programa de Educação Ambiental")
                        st.write("**O Município participa de algum Programa de Educação Ambiental?**")
                        st.caption("ℹ *Atenção à consistência dos dados salvos no banco. Salvamento automático.*")

                        opc20 = ["Selecione...", "Sim – 10", "Não – 00"]
                        d20 = res_data.get("2.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        if d20 is None: d20 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                        v_salvo_20 = d20.get("valor", "Selecione...")
                        if v_salvo_20 not in opc20: v_salvo_20 = "Selecione..."
                        
                        evidencia_20_salva = d20.get("link", "")
                        chave_radio_20 = f"r_20_select_{ano_sel}"
                        chave_link_20 = f"l_20_txt_area_{ano_sel}"

                        def cb_processa_e_salva_20():
                                lnk_val = st.session_state.get(chave_link_20, evidencia_20_salva).strip()
                                val_salvar = st.session_state.get(chave_radio_20, v_salvo_20)
                                
                                pts_calculados = 10.0 if "Sim" in str(val_salvar) else 0.0
                                save_resp("2.0", val_salvar, pts_calculados, lnk_val)
                                res_data["2.0"] = {"valor": val_salvar, "pontos": pts_calculados, "link": lnk_val}

                                links_atuais = re.findall(r'(https?://[^\s]+)', lnk_val or "")
                                links_antigos = re.findall(r'(https?://[^\s]+)', evidencia_20_salva or "")
                                if lnk_val != evidencia_20_salva and links_atuais and links_atuais != links_antigos:
                                        st.session_state[f"links_pendentes_2_0_{ano_sel}"] = links_atuais
                                        st.session_state[f"gatilho_modal_2_0_{ano_sel}"] = True

                        col1, col2 = st.columns([1, 1])
                        with col1:
                                idx20 = opc20.index(v_salvo_20)
                                st.radio(
                                        "Selecione uma opção (2.0):",
                                        options=opc20,
                                        index=idx20,
                                        key=chave_radio_20,
                                        on_change=cb_processa_e_salva_20
                                )

                        with col2:
                                link_20 = st.text_area(
                                        "Link/Evidência (2.0):",
                                        value=evidencia_20_salva,
                                        key=chave_link_20,
                                        on_change=cb_processa_e_salva_20,
                                        placeholder="Insira o link oficial contendo o plano, adesão ou portaria do Programa...",
                                        height=110
                                )
                                placeholder_links_20 = st.empty()
                                links_20_visuais = re.findall(r'(https?://[^\s]+)', link_20 or "")
                                if links_20_visuais:
                                        placeholder_links_20.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_20_visuais]))

                        v_atual_20 = st.session_state.get(chave_radio_20, v_salvo_20)
                        cor_txt_20 = "#28a745" if "Sim" in str(v_atual_20) else ("#dc3545" if "Não" in str(v_atual_20) else "#6c757d")
                        pts_atuais_20 = 10.0 if "Sim" in str(v_atual_20) else 0.0
                        st.markdown(f"<span style='color:{cor_txt_20}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 2.0: +{pts_atuais_20} pontos</span>", unsafe_allow_html=True)
                        bloco_comentarios("2.0", res_data, ano_sel)


        # =============================================================================
        # QUESITO 2.1 • AÇÃO EM REDE ESCOLAR MUNICIPAL (CÁLCULO PROPORCIONAL)
        # =============================================================================
        with st.container(key=f"container_bloco_prog_2_1_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 2.1 - Cobertura de Educação Ambiental na Rede Escolar", expanded=True):
                        st.subheader("2.1 • Ação em Rede Escolar")
                        st.write("**Sobre programa ou ação de educação ambiental na rede escolar municipal, informe o número de escolas dos Anos Iniciais (1º ao 5º ano) que adotam o programa.**")
                        st.caption("ℹ *O cálculo de pontuação é dinâmico e proporcional ao universo de escolas informadas. Salvamento automático.*")

                        d21 = res_data.get("2.1", {"valor": "", "pontos": 0.0, "link": ""})
                        if d21 is None: d21 = {"valor": "", "pontos": 0.0, "link": ""}

                        try:
                                valores_salvos = json.loads(d21["valor"]) if d21["valor"] != "" else {"n_com_programa": 0, "n_total": 1}
                        except:
                                valores_salvos = {"n_com_programa": 0, "n_total": 1}

                        v_com_programa_salvo = int(valores_salvos.get("n_com_programa", 0))
                        v_total_salvo = int(valores_salvos.get("n_total", 1))
                        evidencia_21_salva = d21.get("link", "")

                        chave_com_prog = f"q21_com_prog_num_{ano_sel}"
                        chave_total_escolas = f"q21_total_num_{ano_sel}"
                        chave_link_21 = f"l_21_txt_area_{ano_sel}"

                        def cb_processa_e_salva_21():
                                n_com_prog = st.session_state.get(chave_com_prog, v_com_programa_salvo)
                                n_tot = st.session_state.get(chave_total_escolas, v_total_salvo)
                                lnk_val = st.session_state.get(chave_link_21, evidencia_21_salva).strip()
                                
                                # Evita divisão por zero se o usuário limpar o input para 0 temporariamente
                                den = n_tot if n_tot > 0 else 1
                                proporcao = n_com_prog / den
                                pts_calculados = min(proporcao * 50.0, 50.0)

                                valores_formatados = json.dumps({"n_com_programa": n_com_prog, "n_total": n_tot})
                                
                                save_resp("2.1", valores_formatados, float(pts_calculados), lnk_val)
                                res_data["2.1"] = {"valor": valores_formatados, "pontos": float(pts_calculados), "link": lnk_val}

                                links_atuais = re.findall(r'(https?://[^\s]+)', lnk_val or "")
                                links_antigos = re.findall(r'(https?://[^\s]+)', evidencia_21_salva or "")
                                if lnk_val != evidencia_21_salva and links_atuais and links_atuais != links_antigos:
                                        st.session_state[f"links_pendentes_2_1_{ano_sel}"] = links_atuais
                                        st.session_state[f"gatilho_modal_2_1_{ano_sel}"] = True

                        col1, col2 = st.columns([1, 1])
                        with col1:
                                st.markdown("**Métricas da Rede Pública:**")
                                st.number_input(
                                        "Nº de escolas com programa/ação ambiental:",
                                        min_value=0,
                                        value=v_com_programa_salvo,
                                        key=chave_com_prog,
                                        on_change=cb_processa_e_salva_21
                                )
                                st.number_input(
                                        "Nº total de escolas de Anos Iniciais no município (i-Educ = E3.3):",
                                        min_value=1,
                                        value=v_total_salvo,
                                        key=chave_total_escolas,
                                        on_change=cb_processa_e_salva_21
                                )

                        with col2:
                                link_21 = st.text_area(
                                        "Link/Evidência (2.1):",
                                        value=evidencia_21_salva,
                                        key=chave_link_21,
                                        on_change=cb_processa_e_salva_21,
                                        placeholder="Insira o link contendo o relatório pedagógico, censo escolar municipal ou portarias das ações nas escolas...",
                                        height=140
                                )
                                placeholder_links_21 = st.empty()
                                links_21_visuais = re.findall(r'(https?://[^\s]+)', link_21 or "")
                                if links_21_visuais:
                                        placeholder_links_21.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_21_visuais]))

                        # Recalcula e exibe o feedback visual baseado no estado em memória ativa
                        n_com_prog_atual = st.session_state.get(chave_com_prog, v_com_programa_salvo)
                        n_tot_atual = st.session_state.get(chave_total_escolas, v_total_salvo)
                        den_atual = n_tot_atual if n_tot_atual > 0 else 1
                        
                        pts_feedback = min((n_com_prog_atual / den_atual) * 50.0, 50.0)
                        cor_txt_21 = "#28a745" if pts_feedback > 0 else "#6c757d"
                        
                        st.markdown(f"<span style='color:{cor_txt_21}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 2.1: +{pts_feedback:.2f} pontos</span>", unsafe_allow_html=True)
                        bloco_comentarios("2.1", res_data, ano_sel)
  
        # --- SEÇÃO 3: USO DE RECURSOS ---
        st.divider()
        st.header("3.0 Uso de Recursos")
        
        # =============================================================================
        # GATILHOS DOS MODAIS AUTOMÁTICOS (Colocar no bloco de modais no topo do arquivo)
        # =============================================================================
        if st.session_state.get(f"gatilho_modal_3_0_{ano_sel}", False):
                modal_aviso_link("3.0", st.session_state.get(f"links_pendentes_3_0_{ano_sel}", []))
                st.session_state[f"gatilho_modal_3_0_{ano_sel}"] = False

        if st.session_state.get(f"gatilho_modal_3_1_{ano_sel}", False):
                modal_aviso_link("3.1", st.session_state.get(f"links_pendentes_3_1_{ano_sel}", []))
                st.session_state[f"gatilho_modal_3_1_{ano_sel}"] = False


        # =============================================================================
        # QUESITO 3.0 • ESTÍMULO AO USO RACIONAL DE RECURSOS NATURAIS
        # =============================================================================
        with st.container(key=f"container_bloco_recursos_3_0_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 3.0 - Estímulo ao Uso Racional de Recursos", expanded=True):
                        st.subheader("3.0 • Estímulo ao Uso Racional")
                        st.write("**A prefeitura municipal estimula entre seus órgãos e entidades de sua responsabilidade projetos e/ou ações que promovam o uso racional de recursos naturais? Ex.: implantação de dispositivos para uso racional da água, coleta seletiva, reuso ou reciclagem de material entre outros.**")
                        st.caption("ℹ *Atenção à consistência dos dados salvos no banco. Salvamento automático.*")

                        opc30 = ["Selecione...", "Sim, para todos os órgãos e entidades – 10", "Parcialmente - 3", "Não – 00"]
                        d30 = res_data.get("3.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        if d30 is None: d30 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                        v_salvo_30 = d30.get("valor", "Selecione...")
                        if v_salvo_30 not in opc30: v_salvo_30 = "Selecione..."
                        
                        evidencia_30_salva = d30.get("link", "")
                        chave_radio_30 = f"r_30_select_{ano_sel}"
                        chave_link_30 = f"l_30_txt_area_{ano_sel}"

                        def cb_processa_e_salva_30():
                                lnk_val = st.session_state.get(chave_link_30, evidencia_30_salva).strip()
                                val_salvar = st.session_state.get(chave_radio_30, v_salvo_30)
                                
                                pts_calculados = 10.0 if "todos" in str(val_salvar) else (3.0 if "Parcialmente" in str(val_salvar) else 0.0)
                                save_resp("3.0", val_salvar, pts_calculados, lnk_val)
                                res_data["3.0"] = {"valor": val_salvar, "pontos": pts_calculados, "link": lnk_val}

                                links_atuais = re.findall(r'(https?://[^\s]+)', lnk_val or "")
                                links_antigos = re.findall(r'(https?://[^\s]+)', evidencia_30_salva or "")
                                if lnk_val != evidencia_30_salva and links_atuais and links_atuais != links_antigos:
                                        st.session_state[f"links_pendentes_3_0_{ano_sel}"] = links_atuais
                                        st.session_state[f"gatilho_modal_3_0_{ano_sel}"] = True

                        col1, col2 = st.columns([1, 1])
                        with col1:
                                idx30 = opc30.index(v_salvo_30)
                                st.radio(
                                        "Selecione uma opção (3.0):",
                                        options=opc30,
                                        index=idx30,
                                        key=chave_radio_30,
                                        on_change=cb_processa_e_salva_30
                                )

                        with col2:
                                link_30 = st.text_area(
                                        "Link/Evidência (3.0):",
                                        value=evidencia_30_salva,
                                        key=chave_link_30,
                                        on_change=cb_processa_e_salva_30,
                                        placeholder="Insira o link de diretrizes, decretos de sustentabilidade institucional ou campanhas internas...",
                                        height=110
                                )
                                placeholder_links_30 = st.empty()
                                links_30_visuais = re.findall(r'(https?://[^\s]+)', link_30 or "")
                                if links_30_visuais:
                                        placeholder_links_30.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_30_visuais]))

                        v_atual_30 = st.session_state.get(chave_radio_30, v_salvo_30)
                        cor_txt_30 = "#28a745" if "Sim" in str(v_atual_30) else ("#ffc107" if "Parcialmente" in str(v_atual_30) else "#6c757d")
                        pts_atuais_30 = 10.0 if "Sim" in str(v_atual_30) else (3.0 if "Parcialmente" in str(v_atual_30) else 0.0)
                        st.markdown(f"<span style='color:{cor_txt_30}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 3.0: +{pts_atuais_30} pontos</span>", unsafe_allow_html=True)
                        bloco_comentarios("3.0", res_data, ano_sel)


        # =============================================================================
        # QUESITO 3.1 • AÇÕES REALIZADAS PELO MUNICÍPIO (MÚLTIPLA ESCOLHA)
        # =============================================================================
        with st.container(key=f"container_bloco_recursos_3_1_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 3.1 - Tipos de Ações de Uso Racional Praticadas", expanded=True):
                        st.subheader("3.1 • Ações Realizadas")
                        st.write("**Assinale quais tipos de ações realizadas pela Prefeitura para o uso racional de recursos naturais:**")
                        st.caption("ℹ *Marque todas as ações que a municipalidade comprove executar em seus prédios ou âmbitos. Salvamento automático.*")

                        opts31 = {
                                "Coleta seletiva – 1,5": 1.5,
                                "Uso racional da água – 1,5": 1.5,
                                "Uso racional de energia elétrica – 1,5": 1.5,
                                "Reúso de materiais – 1,5": 1.5,
                                "Horta coletiva – 1,5": 1.5,
                                "Compostagem – 1,5": 1.5,
                                "Instalação de bicicletários e vestiários para os servidores públicos – 1,5": 1.5,
                                "Implantação de caixas acopladas nos vasos sanitários – 1,5": 1.5,
                                "Substituição de lâmpadas fluorescentes por lâmpadas LED – 1,5": 1.5,
                                "Instalação de estruturas para a captação de água de chuva – 1,5": 1.5,
                                "Instalação de torneiras com redutores de pressão – 1,5": 1.5,
                                "Substituição de material descartável – 1,5": 1.5,
                                "Logística reversa de pilhas, baterias e eletrônicos – 1,5": 1.5,
                                "Outros – 0,5": 0.5
                        }

                        d31 = res_data.get("3.1", {"valor": "[]", "pontos": 0.0, "link": ""})
                        if d31 is None: d31 = {"valor": "[]", "pontos": 0.0, "link": ""}

                        texto_seguro_31 = str(d31.get("valor", "[]"))
                        evidencia_31_salva = d31.get("link", "")
                        
                        chave_link_31 = f"l_31_txt_area_{ano_sel}"

                        def cb_processa_e_salva_31():
                                # Processa dinamicamente a soma e as caixas ativas via session_state
                                lista_selecionados = []
                                pts_totais = 0.0
                                for idx, (txt, pts) in enumerate(opts31.items()):
                                        if st.session_state.get(f"ck_31_opt_{idx}_{ano_sel}", False):
                                                lista_selecionados.append(txt)
                                                pts_totais += pts
                                
                                lnk_val = st.session_state.get(chave_link_31, evidencia_31_salva).strip()
                                val_salvar = str(lista_selecionados)
                                
                                save_resp("3.1", val_salvar, pts_totais, lnk_val)
                                res_data["3.1"] = {"valor": val_salvar, "pontos": pts_totais, "link": lnk_val}

                                # Verificação para disparo do modal
                                links_atuais = re.findall(r'(https?://[^\s]+)', lnk_val or "")
                                links_antigos = re.findall(r'(https?://[^\s]+)', evidencia_31_salva or "")
                                if lnk_val != evidencia_31_salva and links_atuais and links_atuais != links_antigos:
                                        st.session_state[f"links_pendentes_3_1_{ano_sel}"] = links_atuais
                                        st.session_state[f"gatilho_modal_3_1_{ano_sel}"] = True

                        col1, col2 = st.columns([1, 1])
                        with col1:
                                st.write("*Selecione as iniciativas em execução:*")
                                for i, (txt, pts) in enumerate(opts31.items()):
                                        marcado = (txt in texto_seguro_31) if texto_seguro_31 and texto_seguro_31 != "[]" else False
                                        st.checkbox(
                                                txt,
                                                value=marcado,
                                                key=f"ck_31_opt_{i}_{ano_sel}",
                                                on_change=cb_processa_e_salva_31
                                        )

                        with col2:
                                link_31 = st.text_area(
                                        "Link/Evidência (3.1):",
                                        value=evidencia_31_salva,
                                        key=chave_link_31,
                                        on_change=cb_processa_e_salva_31,
                                        placeholder="Insira os links comprobatórios das iniciativas marcadas (contratos de LED, fotos de cisternas, etc)...",
                                        height=320
                                )
                                placeholder_links_31 = st.empty()
                                links_31_visuais = re.findall(r'(https?://[^\s]+)', link_31 or "")
                                if links_31_visuais:
                                        placeholder_links_31.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_31_visuais]))

                        # Recalcula feedback de pontuação baseado na memória das caixas de marcação atuais
                        pts_feedback = 0.0
                        for idx, (txt, pts) in enumerate(opts31.items()):
                                if st.session_state.get(f"ck_31_opt_{idx}_{ano_sel}", False):
                                        pts_feedback += pts

                        cor_txt_31 = "#28a745" if pts_feedback > 0 else "#6c757d"
                        st.markdown(f"<span style='color:{cor_txt_31}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 3.1: +{pts_feedback:.1f} pontos</span>", unsafe_allow_html=True)
                        bloco_comentarios("3.1", res_data, ano_sel)

        # --- SEÇÃO 4: CONTROLE DE POLUIÇÃO ---
        st.divider()
        st.header("4.0 Controle de Poluição")
        
       # =============================================================================
        # GATILHOS DOS MODAIS AUTOMÁTICOS (Colocar no bloco de modais no topo do arquivo)
        # =============================================================================
        if st.session_state.get(f"gatilho_modal_4_0_{ano_sel}", False):
                modal_aviso_link("4.0", st.session_state.get(f"links_pendentes_4_0_{ano_sel}", []))
                st.session_state[f"gatilho_modal_4_0_{ano_sel}"] = False

        if st.session_state.get(f"gatilho_modal_5_0_{ano_sel}", False):
                modal_aviso_link("5.0", st.session_state.get(f"links_pendentes_5_0_{ano_sel}", []))
                st.session_state[f"gatilho_modal_5_0_{ano_sel}"] = False


        # =============================================================================
        # QUESITO 4.0 • FISCALIZAÇÃO DE EMISSÃO DE POLUENTES (FROTA MUNICIPAL)
        # =============================================================================
        with st.container(key=f"container_bloco_poluentes_4_0_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 4.0 - Fiscalização de Emissões Veiculares", expanded=True):
                        st.subheader("4.0 • Emissão de Poluentes")
                        st.write("**O município fiscalizou a emissão de poluentes de combustíveis fósseis (diesel) na frota da Prefeitura Municipal?**")
                        st.caption("ℹ *Atenção à consistência dos dados salvos no banco. Salvamento automático.*")

                        opc40 = ["Selecione...", "Sim, com medição da densidade colorimétrica da Escala Ringelmann ou equivalente – 20", "Sim, através de outra forma de medição – 15", "Não – 00"]
                        d40 = res_data.get("4.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        if d40 is None: d40 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                        v_salvo_40 = d40.get("valor", "Selecione...")
                        if v_salvo_40 not in opc40: v_salvo_40 = "Selecione..."
                        
                        evidencia_40_salva = d40.get("link", "")
                        chave_radio_40 = f"r_40_select_{ano_sel}"
                        chave_link_40 = f"l_40_txt_area_{ano_sel}"

                        def cb_processa_e_salva_40():
                                lnk_val = st.session_state.get(chave_link_40, evidencia_40_salva).strip()
                                val_salvar = st.session_state.get(chave_radio_40, v_salvo_40)
                                
                                pts_calculados = 20.0 if "Ringelmann" in str(val_salvar) else (15.0 if "outra" in str(val_salvar) else 0.0)
                                save_resp("4.0", val_salvar, pts_calculados, lnk_val)
                                res_data["4.0"] = {"valor": val_salvar, "pontos": pts_calculados, "link": lnk_val}

                                links_atuais = re.findall(r'(https?://[^\s]+)', lnk_val or "")
                                links_antigos = re.findall(r'(https?://[^\s]+)', evidencia_40_salva or "")
                                if lnk_val != evidencia_40_salva and links_atuais and links_atuais != links_antigos:
                                        st.session_state[f"links_pendentes_4_0_{ano_sel}"] = links_atuais
                                        st.session_state[f"gatilho_modal_4_0_{ano_sel}"] = True

                        col1, col2 = st.columns([1, 1])
                        with col1:
                                idx40 = opc40.index(v_salvo_40)
                                st.radio(
                                        "Selecione uma opção (4.0):",
                                        options=opc40,
                                        index=idx40,
                                        key=chave_radio_40,
                                        on_change=cb_processa_e_salva_40
                                )

                        with col2:
                                link_40 = st.text_area(
                                        "Link/Evidência (4.0):",
                                        value=evidencia_40_salva,
                                        key=chave_link_40,
                                        on_change=cb_processa_e_salva_40,
                                        placeholder="Insira o link contendo relatórios de medição da frota, laudos da Escala Ringelmann, etc...",
                                        height=110
                                )
                                placeholder_links_40 = st.empty()
                                links_40_visuais = re.findall(r'(https?://[^\s]+)', link_40 or "")
                                if links_40_visuais:
                                        placeholder_links_40.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_40_visuais]))

                        v_atual_40 = st.session_state.get(chave_radio_40, v_salvo_40)
                        cor_txt_40 = "#28a745" if "Sim" in str(v_atual_40) else ("#dc3545" if "Não" in str(v_atual_40) else "#6c757d")
                        pts_atuais_40 = 20.0 if "Ringelmann" in str(v_atual_40) else (15.0 if "outra" in str(v_atual_40) else 0.0)
                        st.markdown(f"<span style='color:{cor_txt_40}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 4.0: +{pts_atuais_40} pontos</span>", unsafe_allow_html=True)
                        bloco_comentarios("4.0", res_data, ano_sel)


        # --- DIVISOR DE SEÇÃO ---
        st.divider()
        st.header("5.0 Arborização e Podas")


        # =============================================================================
        # QUESITO 5.0 • CONTRATO DE PRESTAÇÃO DE SERVIÇO DE PODA E CORTE
        # =============================================================================
        with st.container(key=f"container_bloco_arborizacao_5_0_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 5.0 - Contratos Vigentes para Podas e Cortes", expanded=True):
                        st.subheader("5.0 • Contrato de Prestação de Serviço")
                        st.write("**A Prefeitura Municipal possui contrato de prestação de serviço de poda e corte de árvores, arbustos e outras plantas lenhosas em áreas urbanas?**")
                        st.caption("ℹ *Atenção à consistência dos dados salvos no banco. Salvamento automático.*")

                        opc50 = ["Selecione...", "Sim", "Não"]
                        d50 = res_data.get("5.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        if d50 is None: d50 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                        v_salvo_50 = d50.get("valor", "Selecione...")
                        if v_salvo_50 not in opc50: v_salvo_50 = "Selecione..."
                        
                        evidencia_50_salva = d50.get("link", "")
                        chave_radio_50 = f"r_50_select_{ano_sel}"
                        chave_link_50 = f"l_50_txt_area_{ano_sel}"

                        def cb_processa_e_salva_50():
                                lnk_val = st.session_state.get(chave_link_50, evidencia_50_salva).strip()
                                val_salvar = st.session_state.get(chave_radio_50, v_salvo_50)
                                
                                # Salva com 0.0 pontos padrão conforme a regra do script original
                                save_resp("5.0", val_salvar, 0.0, lnk_val)
                                res_data["5.0"] = {"valor": val_salvar, "pontos": 0.0, "link": lnk_val}

                                links_atuais = re.findall(r'(https?://[^\s]+)', lnk_val or "")
                                links_antigos = re.findall(r'(https?://[^\s]+)', evidencia_50_salva or "")
                                if lnk_val != evidencia_50_salva and links_atuais and links_atuais != links_antigos:
                                        st.session_state[f"links_pendentes_5_0_{ano_sel}"] = links_atuais
                                        st.session_state[f"gatilho_modal_5_0_{ano_sel}"] = True

                        col1, col2 = st.columns([1, 1])
                        with col1:
                                idx50 = opc50.index(v_salvo_50)
                                st.radio(
                                        "Selecione uma opção (5.0):",
                                        options=opc50,
                                        index=idx50,
                                        key=chave_radio_50,
                                        on_change=cb_processa_e_salva_50
                                )

                        with col2:
                                link_50 = st.text_area(
                                        "Link/Evidência (5.0):",
                                        value=evidencia_50_salva,
                                        key=chave_link_50,
                                        on_change=cb_processa_e_salva_50,
                                        placeholder="Insira o link do contrato de prestação de serviços, publicação no Diário Oficial ou termo de licitação...",
                                        height=110
                                )
                                placeholder_links_50 = st.empty()
                                links_50_visuais = re.findall(r'(https?://[^\s]+)', link_50 or "")
                                if links_50_visuais:
                                        placeholder_links_50.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_50_visuais]))

                        v_atual_50 = st.session_state.get(chave_radio_50, v_salvo_50)
                        cor_txt_50 = "#28a745" if v_atual_50 == "Sim" else ("#dc3545" if v_atual_50 == "Não" else "#6c757d")
                        st.markdown(f"<span style='color:{cor_txt_50}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 5.0: +0.0 pontos</span>", unsafe_allow_html=True)
                        bloco_comentarios("5.0", res_data, ano_sel)

        # =============================================================================
        # GATILHOS DOS MODAIS AUTOMÁTICOS (Colocar no bloco de modais no topo do arquivo)
        # =============================================================================
        if st.session_state.get(f"gatilho_modal_5_1_{ano_sel}", False):
                modal_aviso_link("5.1", st.session_state.get(f"links_pendentes_5_1_{ano_sel}", []))
                st.session_state[f"gatilho_modal_5_1_{ano_sel}"] = False

        if st.session_state.get(f"gatilho_modal_5_2_{ano_sel}", False):
                modal_aviso_link("5.2", st.session_state.get(f"links_pendentes_5_2_{ano_sel}", []))
                st.session_state[f"gatilho_modal_5_2_{ano_sel}"] = False

        if st.session_state.get(f"gatilho_modal_5_2_1_{ano_sel}", False):
                modal_aviso_link("5.2.1", st.session_state.get(f"links_pendentes_5_2_1_{ano_sel}", []))
                st.session_state[f"gatilho_modal_5_2_1_{ano_sel}"] = False


        # =============================================================================
        # QUESITO 5.1 • NÚMERO DO CONTRATO E PRESTADOR DE SERVIÇO
        # =============================================================================
        with st.container(key=f"container_bloco_arborizacao_5_1_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 5.1 - Detalhes do Contrato de Poda", expanded=True):
                        st.subheader("5.1 • Identificação do Contrato")
                        st.write("**Informe o número do contrato e o prestador de serviço:**")
                        st.caption("ℹ *Dados estruturados textuais e associados à evidência. Salvamento automático.*")

                        d51 = res_data.get("5.1", {"valor": "", "pontos": 0.0, "link": ""})
                        if d51 is None: d51 = {"valor": "", "pontos": 0.0, "link": ""}

                        try:
                                parts = d51["valor"].split("|")
                                c_salvo = parts[0].split(":")[1].strip()
                                p_salvo = parts[1].split(":")[1].strip()
                        except:
                                c_salvo, p_salvo = "", ""

                        evidencia_51_salva = d51.get("link", "")
                        chave_num_cont = f"q51_cont_txt_{ano_sel}"
                        chave_prestador = f"q51_prest_txt_{ano_sel}"
                        chave_link_51 = f"l_51_txt_area_{ano_sel}"

                        def cb_processa_e_salva_51():
                                num_c = st.session_state.get(chave_num_cont, c_salvo).strip()
                                prest = st.session_state.get(chave_prestador, p_salvo).strip()
                                lnk_val = st.session_state.get(chave_link_51, evidencia_51_salva).strip()
                                
                                valor_ajustado = f"Contrato: {num_c} | Prestador: {prest}"
                                
                                save_resp("5.1", valor_ajustado, 0.0, lnk_val)
                                res_data["5.1"] = {"valor": valor_ajustado, "pontos": 0.0, "link": lnk_val}

                                links_atuais = re.findall(r'(https?://[^\s]+)', lnk_val or "")
                                links_antigos = re.findall(r'(https?://[^\s]+)', evidencia_51_salva or "")
                                if lnk_val != evidencia_51_salva and links_atuais and links_atuais != links_antigos:
                                        st.session_state[f"links_pendentes_5_1_{ano_sel}"] = links_atuais
                                        st.session_state[f"gatilho_modal_5_1_{ano_sel}"] = True

                        col1, col2 = st.columns([1, 1])
                        with col1:
                                st.text_input("Número do contrato:", value=c_salvo, key=chave_num_cont, on_change=cb_processa_e_salva_51)
                                st.text_input("Prestador de serviço:", value=p_salvo, key=chave_prestador, on_change=cb_processa_e_salva_51)

                        with col2:
                                link_51 = st.text_area(
                                        "Link/Evidência (5.1):",
                                        value=evidencia_51_salva,
                                        key=chave_link_51,
                                        on_change=cb_processa_e_salva_51,
                                        placeholder="Insira o link para a cópia digital do contrato ou termo de homologação...",
                                        height=140
                                )
                                placeholder_links_51 = st.empty()
                                links_51_visuais = re.findall(r'(https?://[^\s]+)', link_51 or "")
                                if links_51_visuais:
                                        placeholder_links_51.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_51_visuais]))

                        st.markdown(f"<span style='color:#6c757d; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 5.1: +0.0 pontos</span>", unsafe_allow_html=True)
                        bloco_comentarios("5.1", res_data, ano_sel)


        # =============================================================================
        # QUESITO 5.2 • PERIODICIDADE DE PODA/MANUTENÇÃO DAS ÁRVORES
        # =============================================================================
        with st.container(key=f"container_bloco_arborizacao_5_2_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 5.2 - Cronograma e Regularidade de Podas", expanded=True):
                        st.subheader("5.2 • Periodicidade de Manutenção")
                        st.write("**A Prefeitura mantém uma periodicidade de poda/manutenção das árvores?**")
                        st.caption("ℹ *Atenção: Opções incorretas geram impactos negativos/penalidades na nota total. Salvamento automático.*")

                        opts52 = {
                                "Selecione...": 0.0,
                                "Sim – 00": 0.0,
                                "Não tem uma periodicidade – -10": -10.0,
                                "Somente por solicitação – -10": -10.0,
                                "Não realiza poda e/ou corte de árvores – -15": -15.0
                        }
                        lista_opts = list(opts52.keys())

                        d52 = res_data.get("5.2", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        if d52 is None: d52 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                        v_salvo_52 = d52.get("valor", "Selecione...")
                        if v_salvo_52 not in lista_opts: v_salvo_52 = "Selecione..."

                        evidencia_52_salva = d52.get("link", "")
                        chave_radio_52 = f"r_52_select_{ano_sel}"
                        chave_link_52 = f"l_52_txt_area_{ano_sel}"

                        def cb_processa_e_salva_52():
                                lnk_val = st.session_state.get(chave_link_52, evidencia_52_salva).strip()
                                val_salvar = st.session_state.get(chave_radio_52, v_salvo_52)
                                
                                pts_calculados = opts52.get(val_salvar, 0.0)
                                save_resp("5.2", val_salvar, float(pts_calculados), lnk_val)
                                res_data["5.2"] = {"valor": val_salvar, "pontos": float(pts_calculados), "link": lnk_val}

                                links_atuais = re.findall(r'(https?://[^\s]+)', lnk_val or "")
                                links_antigos = re.findall(r'(https?://[^\s]+)', evidencia_52_salva or "")
                                if lnk_val != evidencia_52_salva and links_atuais and links_atuais != links_antigos:
                                        st.session_state[f"links_pendentes_5_2_{ano_sel}"] = links_atuais
                                        st.session_state[f"gatilho_modal_5_2_{ano_sel}"] = True

                        col1, col2 = st.columns([1, 1])
                        with col1:
                                idx52 = lista_opts.index(v_salvo_52)
                                st.radio(
                                        "Selecione uma opção (5.2):",
                                        options=lista_opts,
                                        index=idx52,
                                        key=chave_radio_52,
                                        on_change=cb_processa_e_salva_52
                                )

                        with col2:
                                link_52 = st.text_area(
                                        "Link/Evidência (5.2):",
                                        value=evidencia_52_salva,
                                        key=chave_link_52,
                                        on_change=cb_processa_e_salva_52,
                                        placeholder="Insira o link do cronograma oficial de podas, decretos ou relatórios de atendimento...",
                                        height=150
                                )
                                placeholder_links_52 = st.empty()
                                links_52_visuais = re.findall(r'(https?://[^\s]+)', link_52 or "")
                                if links_52_visuais:
                                        placeholder_links_52.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_52_visuais]))

                        v_atual_52 = st.session_state.get(chave_radio_52, v_salvo_52)
                        pts_atuais_52 = opts52.get(v_atual_52, 0.0)
                        cor_txt_52 = "#28a745" if pts_atuais_52 == 0.0 and v_atual_52 != "Selecione..." else ("#6c757d" if v_atual_52 == "Selecione..." else "#dc3545")
                        st.markdown(f"<span style='color:{cor_txt_52}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 5.2: {pts_atuais_52:.1f} pontos</span>", unsafe_allow_html=True)
                        bloco_comentarios("5.2", res_data, ano_sel)


        # =============================================================================
        # QUESITO 5.2.1 • DESTINAÇÃO DOS RESÍDUOS DE PODAS (MÚLTIPLA ESCOLHA)
        # =============================================================================
        with st.container(key=f"container_bloco_arborizacao_5_2_1_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 5.2.1 - Destinação Sustentável de Resíduos Verdes", expanded=True):
                        st.subheader("5.2.1 • Destinação dos Resíduos de Podas")
                        st.write("**Qual a destinação dos resíduos das podas de árvores?**")
                        st.caption("ℹ *A pontuação aumenta progressivamente com o número de destinações sustentáveis. Aterros aplicam penalidade.*")

                        opts_pontuam = [
                                "Reaproveitamento para produzir móveis, brinquedos, utensílios ou objetos de decoração",
                                "Compostagem para produção de mudas, na jardinagem e arborização da cidade",
                                "Queima para aquecimento e cocção",
                                "Geração de energia",
                                "Uso na construção civil"
                        ]
                        opt_aterro = "Envio para aterro sanitário – -05"
                        opt_armazenamento = "Armazenamento dos resíduos das podas"

                        d521 = res_data.get("5.2.1", {"valor": "[]", "pontos": 0.0, "link": ""})
                        if d521 is None: d521 = {"valor": "[]", "pontos": 0.0, "link": ""}

                        texto_seguro_521 = str(d521.get("valor", "[]"))
                        evidencia_521_salva = d521.get("link", "")
                        chave_link_521 = f"l_521_txt_area_{ano_sel}"

                        def cb_processa_e_salva_521():
                                # FIX: Captura o valor do link no início do escopo para evitar NameError
                                lnk_val = st.session_state.get(chave_link_521, evidencia_521_salva).strip()
                                
                                lista_selecionados = []
                                qtd_validas = 0
                                penalidade = 0.0
                                
                                # Varre e valida os checkboxes principais
                                for idx, opt in enumerate(opts_pontuam):
                                        if st.session_state.get(f"ck_521_pos_{idx}_{ano_sel}", False):
                                                lista_selecionados.append(opt)
                                                qtd_validas += 1
                                
                                # Valida o checkbox do aterro
                                if st.session_state.get(f"ck_521_aterro_{ano_sel}", False):
                                        lista_selecionados.append(opt_aterro)
                                        penalidade = -5.0
                                        
                                # Valida o checkbox de armazenamento
                                if st.session_state.get(f"ck_521_arm_{ano_sel}", False):
                                        lista_selecionados.append(opt_armazenamento)

                                if qtd_validas >= 3: pts_base = 20.0
                                elif qtd_validas == 2: pts_base = 10.0
                                elif qtd_validas == 1: pts_base = 5.0
                                else: pts_base = 0.0
                                
                                pts_totais = pts_base + penalidade
                                val_salvar = str(lista_selecionados)
                                
                                save_resp("5.2.1", val_salvar, float(pts_totais), lnk_val)
                                res_data["5.2.1"] = {"valor": val_salvar, "pontos": float(pts_totais), "link": lnk_val}

                                links_atuais = re.findall(r'(https?://[^\s]+)', lnk_val or "")
                                links_antigos = re.findall(r'(https?://[^\s]+)', evidencia_521_salva or "")
                                if lnk_val != evidencia_521_salva and links_atuais and links_atuais != links_antigos:
                                        st.session_state[f"links_pendentes_5_2_1_{ano_sel}"] = links_atuais
                                        st.session_state[f"gatilho_modal_5_2_1_{ano_sel}"] = True

                        col1, col2 = st.columns([1, 1])
                        with col1:
                                st.write("*Selecione os destinos comprovados:*")
                                for i, opt in enumerate(opts_pontuam):
                                        marcado = (opt in texto_seguro_521) if texto_seguro_521 and texto_seguro_521 != "[]" else False
                                        st.checkbox(
                                                opt, 
                                                value=marcado, 
                                                key=f"ck_521_pos_{i}_{ano_sel}", 
                                                on_change=cb_processa_e_salva_521
                                        )
                                
                                marcado_aterro = (opt_aterro in texto_seguro_521) if texto_seguro_521 and texto_seguro_521 != "[]" else False
                                st.checkbox(
                                        opt_aterro, 
                                        value=marcado_aterro, 
                                        key=f"ck_521_aterro_{ano_sel}", 
                                        on_change=cb_processa_e_salva_521
                                )
                                
                                marcado_arm = (opt_armazenamento in texto_seguro_521) if texto_seguro_521 and texto_seguro_521 != "[]" else False
                                st.checkbox(
                                        opt_armazenamento, 
                                        value=marcado_arm, 
                                        key=f"ck_521_arm_{ano_sel}", 
                                        on_change=cb_processa_e_salva_521
                                )

                        with col2:
                                link_521 = st.text_area(
                                        "Link/Evidência (5.2.1):",
                                        value=evidencia_521_salva,
                                        key=chave_link_521,
                                        on_change=cb_processa_e_salva_521,
                                        placeholder="Insira links do pátio de compostagem, contratos de doação de biomassa ou controle de resíduos...",
                                        height=240
                                )
                                placeholder_links_521 = st.empty()
                                links_521_visuais = re.findall(r'(https?://[^\s]+)', link_521 or "")
                                if links_521_visuais:
                                        placeholder_links_521.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_521_visuais]))

                        # Recalcula feedback visual de pontos baseando-se no session_state atual
                        fb_validas = sum([1 for idx in range(len(opts_pontuam)) if st.session_state.get(f"ck_521_pos_{idx}_{ano_sel}", False)])
                        fb_penalidade = -5.0 if st.session_state.get(f"ck_521_aterro_{ano_sel}", False) else 0.0
                        fb_base = 20.0 if fb_validas >= 3 else (10.0 if fb_validas == 2 else (5.0 if fb_validas == 1 else 0.0))
                        
                        pts_feedback = fb_base + fb_penalidade
                        cor_txt_521 = "#28a745" if pts_feedback > 0 else ("#dc3545" if pts_feedback < 0 else "#6c757d")
                        st.markdown(f"<span style='color:{cor_txt_521}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 5.2.1: +{pts_feedback:.1f} pontos</span>", unsafe_allow_html=True)
                        bloco_comentarios("5.2.1", res_data, ano_sel)

        # =============================================================================
        # GATILHOS DOS MODAIS AUTOMÁTICOS (Colocar no bloco de modais no topo do arquivo)
        # =============================================================================
        if st.session_state.get(f"gatilho_modal_5_3_{ano_sel}", False):
                modal_aviso_link("5.3", st.session_state.get(f"links_pendentes_5_3_{ano_sel}", []))
                st.session_state[f"gatilho_modal_5_3_{ano_sel}"] = False


        # =============================================================================
        # QUESITO 5.3 • ORIENTAÇÃO/TREINAMENTO DE EQUIPE DE MANUTENÇÃO
        # =============================================================================
        with st.container(key=f"container_bloco_arborizacao_5_3_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 5.3 - Capacitação e Treinamento da Equipe", expanded=True):
                        st.subheader("5.3 • Treinamento de Equipe")
                        st.write("**O pessoal da prefeitura responsável por manutenção das árvores é devidamente orientado/treinado para realizar a poda de maneira correta?**")
                        st.caption("ℹ *Atenção: A ausência de treinamento formalizado gera penalidade direta de pontuação. Salvamento automático.*")

                        opts53 = {
                                "Selecione...": 0.0,
                                "Sim – 00": 0.0,
                                "Não – -10": -10.0
                        }
                        lista_opts53 = list(opts53.keys())

                        d53 = res_data.get("5.3", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        if d53 is None: d53 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                        v_salvo_53 = d53.get("valor", "Selecione...")
                        if v_salvo_53 not in lista_opts53: v_salvo_53 = "Selecione..."

                        evidencia_53_salva = d53.get("link", "")
                        chave_radio_53 = f"r_53_select_{ano_sel}"
                        chave_link_53 = f"l_53_txt_area_{ano_sel}"

                        def cb_processa_e_salva_53():
                                lnk_val = st.session_state.get(chave_link_53, evidencia_53_salva).strip()
                                val_salvar = st.session_state.get(chave_radio_53, v_salvo_53)
                                
                                pts_calculados = opts53.get(val_salvar, 0.0)
                                save_resp("5.3", val_salvar, float(pts_calculados), lnk_val)
                                res_data["5.3"] = {"valor": val_salvar, "pontos": float(pts_calculados), "link": lnk_val}

                                links_atuais = re.findall(r'(https?://[^\s]+)', lnk_val or "")
                                links_antigos = re.findall(r'(https?://[^\s]+)', evidencia_53_salva or "")
                                if lnk_val != evidencia_53_salva and links_atuais and links_atuais != links_antigos:
                                        st.session_state[f"links_pendentes_5_3_{ano_sel}"] = links_atuais
                                        st.session_state[f"gatilho_modal_5_3_{ano_sel}"] = True

                        col1, col2 = st.columns([1, 1])
                        with col1:
                                idx_salvo53 = lista_opts53.index(v_salvo_53)
                                st.radio(
                                        "Selecione uma opção (5.3):",
                                        options=lista_opts53,
                                        index=idx_salvo53,
                                        key=chave_radio_53,
                                        on_change=cb_processa_e_salva_53
                                )

                        with col2:
                                link_53 = st.text_area(
                                        "Link/Evidência (5.3):",
                                        value=evidencia_53_salva,
                                        key=chave_link_53,
                                        on_change=cb_processa_e_salva_53,
                                        placeholder="Insira o link contendo certificados de treinamento, listas de presença ou editais de capacitação...",
                                        height=110
                                )
                                placeholder_links_53 = st.empty()
                                links_53_visuais = re.findall(r'(https?://[^\s]+)', link_53 or "")
                                if links_53_visuais:
                                        placeholder_links_53.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_53_visuais]))

                        v_atual_53 = st.session_state.get(chave_radio_53, v_salvo_53)
                        pts_atuais_53 = opts53.get(v_atual_53, 0.0)
                        cor_txt_53 = "#28a745" if pts_atuais_53 == 0.0 and v_atual_53 != "Selecione..." else ("#6c757d" if v_atual_53 == "Selecione..." else "#dc3545")
                        st.markdown(f"<span style='color:{cor_txt_53}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 5.3: {pts_atuais_53:.1f} pontos</span>", unsafe_allow_html=True)
                        bloco_comentarios("5.3", res_data, ano_sel)

        # --- SEÇÃO 6: ESTIAGEM ---
        st.divider()
        st.header("6.0 Medidas para Estiagem")
        
       # =============================================================================
        # GATILHOS DOS MODAIS AUTOMÁTICOS (Colocar no bloco de modais no topo do arquivo)
        # =============================================================================
        if st.session_state.get(f"gatilho_modal_6_0_{ano_sel}", False):
                modal_aviso_link("6.0", st.session_state.get(f"links_pendentes_6_0_{ano_sel}", []))
                st.session_state[f"gatilho_modal_6_0_{ano_sel}"] = False

        if st.session_state.get(f"gatilho_modal_6_1_{ano_sel}", False):
                modal_aviso_link("6.1", st.session_state.get(f"links_pendentes_6_1_{ano_sel}", []))
                st.session_state[f"gatilho_modal_6_1_{ano_sel}"] = False

        if st.session_state.get(f"gatilho_modal_6_2_{ano_sel}", False):
                modal_aviso_link("6.2", st.session_state.get(f"links_pendentes_6_2_{ano_sel}", []))
                st.session_state[f"gatilho_modal_6_2_{ano_sel}"] = False


        # =============================================================================
        # QUESITO 6.0 • AÇÕES PREVENTIVAS DE ESTIAGEM
        # =============================================================================
        with st.container(key=f"container_bloco_estiagem_6_0_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 6.0 - Plano de Contingência para Estiagem", expanded=True):
                        st.subheader("6.0 • Medidas Contra Estiagem")
                        st.write("**Existem ações e medidas preventivas de contingenciamento para os períodos de estiagem executados pela Prefeitura?**")
                        st.caption("*Estiagem é um período prolongado de baixa pluviosidade, ou sua ausência, na qual a perda de umidade do solo é superior à sua reposição.*")

                        opc60 = ["Selecione...", "Sim – 20", "Não – 00"]
                        d60 = res_data.get("6.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        if d60 is None: d60 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                        v_salvo_60 = d60.get("valor", "Selecione...")
                        if v_salvo_60 not in opc60: v_salvo_60 = "Selecione..."

                        evidencia_60_salva = d60.get("link", "")
                        chave_radio_60 = f"r_60_select_{ano_sel}"
                        chave_link_60 = f"l_60_txt_area_{ano_sel}"

                        def cb_processa_e_salva_60():
                                lnk_val = st.session_state.get(chave_link_60, evidencia_60_salva).strip()
                                val_salvar = st.session_state.get(chave_radio_60, v_salvo_60)
                                
                                pts_calculados = 20.0 if "Sim" in str(val_salvar) else 0.0
                                save_resp("6.0", val_salvar, pts_calculados, lnk_val)
                                res_data["6.0"] = {"valor": val_salvar, "pontos": pts_calculados, "link": lnk_val}

                                links_atuais = re.findall(r'(https?://[^\s]+)', lnk_val or "")
                                links_antigos = re.findall(r'(https?://[^\s]+)', evidencia_60_salva or "")
                                if lnk_val != evidencia_60_salva and links_atuais and links_atuais != links_antigos:
                                        st.session_state[f"links_pendentes_6_0_{ano_sel}"] = links_atuais
                                        st.session_state[f"gatilho_modal_6_0_{ano_sel}"] = True

                        col1, col2 = st.columns([1, 1])
                        with col1:
                                idx60 = opc60.index(v_salvo_60)
                                st.radio(
                                        "Selecione uma opção (6.0):",
                                        options=opc60,
                                        index=idx60,
                                        key=chave_radio_60,
                                        on_change=cb_processa_e_salva_60
                                )

                        with col2:
                                link_60 = st.text_area(
                                        "Link/Evidência (6.0):",
                                        value=evidencia_60_salva,
                                        key=chave_link_60,
                                        on_change=cb_processa_e_salva_60,
                                        placeholder="Insira o link contendo o decreto de contingenciamento, plano de metas de estiagem, etc...",
                                        height=110
                                )
                                placeholder_links_60 = st.empty()
                                links_60_visuais = re.findall(r'(https?://[^\s]+)', link_60 or "")
                                if links_60_visuais:
                                        placeholder_links_60.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_60_visuais]))

                        v_atual_60 = st.session_state.get(chave_radio_60, v_salvo_60)
                        pts_atuais_60 = 20.0 if "Sim" in str(v_atual_60) else 0.0
                        cor_txt_60 = "#28a745" if pts_atuais_60 > 0 else ("#6c757d" if v_atual_60 == "Selecione..." else "#dc3545")
                        st.markdown(f"<span style='color:{cor_txt_60}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 6.0: +{pts_atuais_60:.1f} pontos</span>", unsafe_allow_html=True)
                        bloco_comentarios("6.0", res_data, ano_sel)


        # =============================================================================
        # QUESITO 6.1 • DETALHAMENTO DAS MEDIDAS DE ESTIAGEM (MÚLTIPLA ESCOLHA)
        # =============================================================================
        with st.container(key=f"container_bloco_estiagem_6_1_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 6.1 - Ações de Enfrentamento Executadas", expanded=True):
                        st.subheader("6.1 • Detalhamento das Medidas")
                        st.write("**Assinale as ações e medidas preventivas de contingenciamento para os períodos de estiagem executados pela Prefeitura:**")
                        st.caption("ℹ *A pontuação deste quesito é cumulativa baseada nas diretrizes assinaladas. Salvamento automático.*")

                        opts61 = {
                                "Plano emergencial ou de contingenciamento sobre abastecimento de água no caso de sua escassez – 30": 30.0,
                                "Manejo/manobras de água entre os reservatórios – 00": 0.0,
                                "Campanha de conscientização da população – 05": 5.0,
                                "Busca de fontes alternativas de abastecimento, como: poços artesianos – 00": 0.0,
                                "Uso racional da distribuição de água (racionamento) – 00": 0.0,
                                "Implantação de rodízio de fornecimento de água – 00": 0.0,
                                "Redução da pressão no abastecimento de água – 00": 0.0,
                                "Multa em caso de desperdício de água – 00": 0.0,
                                "Tarifa/taxa diferenciada para o aumento de consumo de água – 00": 0.0,
                                "Fornecimento de caminhões pipa – 00": 0.0,
                                "Drenagem pluvial – 00": 0.0,
                                "Incentivo à instalação de sistema para água de reúso – 05": 5.0,
                                "Redução das perdas na distribuição de água – 00": 0.0,
                                "Desassoreamento – 00": 0.0,
                                "Divulgação dos resultados obtidos com o contingenciamento, situação dos mananciais/represas/ETAs – 10": 10.0
                        }

                        d61 = res_data.get("6.1", {"valor": "[]", "pontos": 0.0, "link": ""})
                        if d61 is None: d61 = {"valor": "[]", "pontos": 0.0, "link": ""}

                        texto_seguro_61 = str(d61.get("valor", "[]"))
                        evidencia_61_salva = d61.get("link", "")
                        chave_link_61 = f"l_61_txt_area_{ano_sel}"

                        def cb_processa_e_salva_61():
                                lnk_val = st.session_state.get(chave_link_61, evidencia_61_salva).strip()
                                lista_selecionados = []
                                pts_totais = 0.0
                                
                                for idx, (txt, pts) in enumerate(opts61.items()):
                                        if st.session_state.get(f"ck_61_opt_{idx}_{ano_sel}", False):
                                                lista_selecionados.append(txt)
                                                pts_totais += pts

                                val_salvar = str(lista_selecionados)
                                save_resp("6.1", val_salvar, float(pts_totais), lnk_val)
                                res_data["6.1"] = {"valor": val_salvar, "pontos": float(pts_totais), "link": lnk_val}

                                links_atuais = re.findall(r'(https?://[^\s]+)', lnk_val or "")
                                links_antigos = re.findall(r'(https?://[^\s]+)', evidencia_61_salva or "")
                                if lnk_val != evidencia_61_salva and links_atuais and links_atuais != links_antigos:
                                        st.session_state[f"links_pendentes_6_1_{ano_sel}"] = links_atuais
                                        st.session_state[f"gatilho_modal_6_1_{ano_sel}"] = True

                        col1, col2 = st.columns([1, 1])
                        with col1:
                                st.write("*Selecione as ações válidas:*")
                                for i, (txt, pts) in enumerate(opts61.items()):
                                        marcado = (txt in texto_seguro_61) if texto_seguro_61 and texto_seguro_61 != "[]" else False
                                        st.checkbox(
                                                txt,
                                                value=marcado,
                                                key=f"ck_61_opt_{i}_{ano_sel}",
                                                on_change=cb_processa_e_salva_61
                                        )

                        with col2:
                                link_61 = st.text_area(
                                        "Link/Evidência (6.1):",
                                        value=evidencia_61_salva,
                                        key=chave_link_61,
                                        on_change=cb_processa_e_salva_61,
                                        placeholder="Insira links de diários oficiais, campanhas institucionais ou legislações tarifárias aplicadas...",
                                        height=340
                                )
                                placeholder_links_61 = st.empty()
                                links_61_visuais = re.findall(r'(https?://[^\s]+)', link_61 or "")
                                if links_61_visuais:
                                        placeholder_links_61.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_61_visuais]))

                        # Recalculo do feedback de pontos em tempo de execução
                        fb_pts_61 = sum([pts for idx, (txt, pts) in enumerate(opts61.items()) if st.session_state.get(f"ck_61_opt_{idx}_{ano_sel}", False)])
                        cor_txt_61 = "#28a745" if fb_pts_61 > 0 else "#6c757d"
                        st.markdown(f"<span style='color:{cor_txt_61}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 6.1: +{fb_pts_61:.1f} pontos</span>", unsafe_allow_html=True)
                        bloco_comentarios("6.1", res_data, ano_sel)


        # =============================================================================
        # QUESITO 6.2 • SETORES ATENDIDOS POR AÇÕES ESPECÍFICAS (MÚLTIPLA ESCOLHA)
        # =============================================================================
        with st.container(key=f"container_bloco_estiagem_6_2_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 6.2 - Setores Estratégicos com Provisão Assegurada", expanded=True):
                        st.subheader("6.2 • Setores Atendidos")
                        st.write("**Em quais setores existem ações e medidas de contingenciamento específicos para provisão de água potável?**")
                        st.caption("ℹ *Ações voltadas às frentes públicas de saúde e ensino. Salvamento automático.*")

                        opts62 = {
                                "Rede Municipal de Educação – 10": 10.0,
                                "Rede Municipal da Atenção Básica da Saúde – 10": 10.0,
                                "Outro – 05": 5.0
                        }

                        d62 = res_data.get("6.2", {"valor": "[]", "pontos": 0.0, "link": ""})
                        if d62 is None: d62 = {"valor": "[]", "pontos": 0.0, "link": ""}

                        texto_seguro_62 = str(d62.get("valor", "[]"))
                        evidencia_62_salva = d62.get("link", "")
                        chave_link_62 = f"l_62_txt_area_{ano_sel}"

                        def cb_processa_e_salva_62():
                                lnk_val = st.session_state.get(chave_link_62, evidencia_62_salva).strip()
                                lista_selecionados = []
                                pts_totais = 0.0
                                
                                for idx, (txt, pts) in enumerate(opts62.items()):
                                        if st.session_state.get(f"ck_62_opt_{idx}_{ano_sel}", False):
                                                lista_selecionados.append(txt)
                                                pts_totais += pts

                                val_salvar = str(lista_selecionados)
                                save_resp("6.2", val_salvar, float(pts_totais), lnk_val)
                                res_data["6.2"] = {"valor": val_salvar, "pontos": float(pts_totais), "link": lnk_val}

                                links_atuais = re.findall(r'(https?://[^\s]+)', lnk_val or "")
                                links_antigos = re.findall(r'(https?://[^\s]+)', evidencia_62_salva or "")
                                if lnk_val != evidencia_62_salva and links_atuais and links_atuais != links_antigos:
                                        st.session_state[f"links_pendentes_6_2_{ano_sel}"] = links_atuais
                                        st.session_state[f"gatilho_modal_6_2_{ano_sel}"] = True

                        col1, col2 = st.columns([1, 1])
                        with col1:
                                st.write("*Selecione os setores cobertos:*")
                                for i, (txt, pts) in enumerate(opts62.items()):
                                        marcado = (txt in texto_seguro_62) if texto_seguro_62 and texto_seguro_62 != "[]" else False
                                        st.checkbox(
                                                txt,
                                                value=marcado,
                                                key=f"ck_62_opt_{i}_{ano_sel}",
                                                on_change=cb_processa_e_salva_62
                                        )

                        with col2:
                                link_62 = st.text_area(
                                        "Link/Evidência (6.2):",
                                        value=evidencia_62_salva,
                                        key=chave_link_62,
                                        on_change=cb_processa_e_salva_62,
                                        placeholder="Insira links de termos de cooperação, contratos de abastecimento complementar dedicados a postos ou escolas...",
                                        height=130
                                )
                                placeholder_links_62 = st.empty()
                                links_62_visuais = re.findall(r'(https?://[^\s]+)', link_62 or "")
                                if links_62_visuais:
                                        placeholder_links_62.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_62_visuais]))

                        # Recalculo do feedback de pontos em tempo de execução
                        fb_pts_62 = sum([pts for idx, (txt, pts) in enumerate(opts62.items()) if st.session_state.get(f"ck_62_opt_{idx}_{ano_sel}", False)])
                        cor_txt_62 = "#28a745" if fb_pts_62 > 0 else "#6c757d"
                        st.markdown(f"<span style='color:{cor_txt_62}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 6.2: +{fb_pts_62:.1f} pontos</span>", unsafe_allow_html=True)
                        bloco_comentarios("6.2", res_data, ano_sel)

        # --- SEÇÃO 7: SANEAMENTO ---
        st.divider()
        st.header("7.0 Saneamento Básico")
        
        # =============================================================================
        # GATILHOS DOS MODAIS AUTOMÁTICOS (Colocar no bloco de modais no topo do arquivo)
        # =============================================================================
        if st.session_state.get(f"gatilho_modal_7_0_{ano_sel}", False):
                modal_aviso_link("7.0", st.session_state.get(f"links_pendentes_7_0_{ano_sel}", []))
                st.session_state[f"gatilho_modal_7_0_{ano_sel}"] = False


        # =============================================================================
        # QUESITO 7.0 • INSTITUIÇÃO DO PLANO DE SANEAMENTO BÁSICO
        # =============================================================================
        with st.container(key=f"container_bloco_saneamento_7_0_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 7.0 - Plano Municipal/Regional de Saneamento", expanded=True):
                        st.subheader("7.0 • Plano de Saneamento Básico")
                        st.write("**O município possui seu Plano Municipal ou Regional de Saneamento Básico instituído?**")
                        st.caption("ℹ *O plano instituído orienta as diretrizes de infraestrutura urbana. Salvamento automático.*")

                        opc70 = ["Selecione...", "Sim", "Não"]
                        d70 = res_data.get("7.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        if d70 is None: d70 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                        v_salvo_70 = d70.get("valor", "Selecione...")
                        if v_salvo_70 not in opc70: v_salvo_70 = "Selecione..."

                        evidencia_70_salva = d70.get("link", "")
                        chave_radio_70 = f"r_70_select_{ano_sel}"
                        chave_link_70 = f"l_70_txt_area_{ano_sel}"

                        def cb_processa_e_salva_70():
                                lnk_val = st.session_state.get(chave_link_70, evidencia_70_salva).strip()
                                val_salvar = st.session_state.get(chave_radio_70, v_salvo_70)
                                
                                # Quesito informativo/condicional, sem pontuação direta mapeada na opção
                                save_resp("7.0", val_salvar, 0.0, lnk_val)
                                res_data["7.0"] = {"valor": val_salvar, "pontos": 0.0, "link": lnk_val}

                                links_atuais = re.findall(r'(https?://[^\s]+)', lnk_val or "")
                                links_antigos = re.findall(r'(https?://[^\s]+)', evidencia_70_salva or "")
                                if lnk_val != evidencia_70_salva and links_atuais and links_atuais != links_antigos:
                                        st.session_state[f"links_pendentes_7_0_{ano_sel}"] = links_atuais
                                        st.session_state[f"gatilho_modal_7_0_{ano_sel}"] = True

                        col1, col2 = st.columns([1, 1])
                        with col1:
                                idx70 = opc70.index(v_salvo_70)
                                st.radio(
                                        "Selecione uma opção (7.0):",
                                        options=opc70,
                                        index=idx70,
                                        key=chave_radio_70,
                                        on_change=cb_processa_e_salva_70
                                )

                        with col2:
                                link_70 = st.text_area(
                                        "Link/Evidência (7.0):",
                                        value=evidencia_70_salva,
                                        key=chave_link_70,
                                        on_change=cb_processa_e_salva_70,
                                        placeholder="Insira o link para o decreto, lei municipal ou ato regulamentar de instituição do plano...",
                                        height=110
                                )
                                placeholder_links_70 = st.empty()
                                links_70_visuais = re.findall(r'(https?://[^\s]+)', link_70 or "")
                                if links_70_visuais:
                                        placeholder_links_70.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_70_visuais]))

                        st.markdown(f"<span style='color:#6c757d; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 7.0: +0.0 pontos (Informativo)</span>", unsafe_allow_html=True)
                        bloco_comentarios("7.0", res_data, ano_sel)

        # =============================================================================
        # GATILHOS DOS MODAIS AUTOMÁTICOS (Colocar no bloco de modais no topo do arquivo)
        # =============================================================================
        for q_id in ["7_1", "7_2", "7_3", "7_3_1", "7_3_2"]:
                if st.session_state.get(f"gatilho_modal_{q_id}_{ano_sel}", False):
                        modal_aviso_link(q_id.replace("_", "."), st.session_state.get(f"links_pendentes_{q_id}_{ano_sel}", []))
                        st.session_state[f"gatilho_modal_{q_id}_{ano_sel}"] = False


        # =============================================================================
        # QUESITO 7.1 • INSTRUMENTO NORMATIVO DO PLANO
        # =============================================================================
        with st.container(key=f"container_bloco_saneamento_7_1_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 7.1 - Atos de Regulamentação Normativa", expanded=True):
                        st.subheader("7.1 • Instrumento Normativo")
                        st.write("**Informe o Instrumento normativo, Número e Data da publicação:**")

                        d71 = res_data.get("7.1", {"valor": "Inst:  | Nº:  | Data: ", "pontos": 0.0, "link": ""})
                        if d71 is None: d71 = {"valor": "Inst:  | Nº:  | Data: ", "pontos": 0.0, "link": ""}

                        try:
                                parts = d71["valor"].split("|")
                                inst_salvo = parts[0].split(":")[1].strip()
                                num_salvo = parts[1].split(":")[1].strip()
                                data_salvo = parts[2].split(":")[1].strip()
                        except:
                                inst_salvo, num_salvo, data_salvo = "", "", ""

                        evidencia_71_salva = d71.get("link", "")
                        chave_inst = f"q71_inst_txt_{ano_sel}"
                        chave_num = f"q71_num_txt_{ano_sel}"
                        chave_data = f"q71_data_txt_{ano_sel}"
                        chave_link_71 = f"l_71_txt_area_{ano_sel}"

                        def cb_processa_e_salva_71():
                                lnk_val = st.session_state.get(chave_link_71, evidencia_71_salva).strip()
                                inst_v = st.session_state.get(chave_inst, inst_salvo).strip()
                                num_v = st.session_state.get(chave_num, num_salvo).strip()
                                dt_v = st.session_state.get(chave_data, data_salvo).strip()
                                
                                val_salvar = f"Inst: {inst_v} | Nº: {num_v} | Data: {dt_v}"
                                save_resp("7.1", val_salvar, 0.0, lnk_val)
                                res_data["7.1"] = {"valor": val_salvar, "pontos": 0.0, "link": lnk_val}

                                links_atuais = re.findall(r'(https?://[^\s]+)', lnk_val or "")
                                links_antigos = re.findall(r'(https?://[^\s]+)', evidencia_71_salva or "")
                                if lnk_val != evidencia_71_salva and links_atuais and links_atuais != links_antigos:
                                        st.session_state[f"links_pendentes_7_1_{ano_sel}"] = links_atuais
                                        st.session_state[f"gatilho_modal_7_1_{ano_sel}"] = True

                        col1, col2 = st.columns([1, 1])
                        with col1:
                                st.text_input("Instrumento normativo:", value=inst_salvo, key=chave_inst, on_change=cb_processa_e_salva_71)
                                st.text_input("Número:", value=num_salvo, key=chave_num, on_change=cb_processa_e_salva_71)
                                st.text_input("Data da publicação:", value=data_salvo, key=chave_data, on_change=cb_processa_e_salva_71)

                        with col2:
                                link_71 = st.text_area(
                                        "Link/Evidência (7.1):",
                                        value=evidencia_71_salva,
                                        key=chave_link_71,
                                        on_change=cb_processa_e_salva_71,
                                        placeholder="Link para o Diário Oficial contendo a publicação da portaria, decreto ou lei...",
                                        height=220
                                )
                                placeholder_links_71 = st.empty()
                                links_71_visuais = re.findall(r'(https?://[^\s]+)', link_71 or "")
                                if links_71_visuais:
                                        placeholder_links_71.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_71_visuais]))

                        st.markdown(f"<span style='color:#6c757d; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 7.1: +0.0 pontos (Informativo)</span>", unsafe_allow_html=True)
                        bloco_comentarios("7.1", res_data, ano_sel)


        # =============================================================================
        # QUESITO 7.2 • PÁGINA ELETRÔNICA DO PLANO
        # =============================================================================
        with st.container(key=f"container_bloco_saneamento_7_2_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 7.2 - Transparência Pública e Acesso ao Plano", expanded=True):
                        st.subheader("7.2 • Página Eletrônica do Plano")
                        st.write("**Informe a página eletrônica (link na internet) do Plano Municipal ou Regional de Saneamento Básico:**")
                        st.caption("ℹ *Se não estiver disponível na internet, insira o texto **XYZ** no campo de resposta para fins de auditoria.*")

                        d72 = res_data.get("7.2", {"valor": "", "pontos": 0.0, "link": ""})
                        if d72 is None: d72 = {"valor": "", "pontos": 0.0, "link": ""}

                        v_salvo_72 = d72.get("valor", "")
                        evidencia_72_salva = d72.get("link", "")
                        chave_val_72 = f"q72_link_val_{ano_sel}"
                        chave_link_72 = f"l_72_txt_area_{ano_sel}"

                        def cb_processa_e_salva_72():
                                lnk_val = st.session_state.get(chave_link_72, evidencia_72_salva).strip()
                                txt_val = st.session_state.get(chave_val_72, v_salvo_72).strip()
                                
                                pts_calculados = 0.0 if txt_val.upper() in ["XYZ", ""] else 2.0
                                save_resp("7.2", txt_val, pts_calculados, lnk_val)
                                res_data["7.2"] = {"valor": txt_val, "pontos": pts_calculados, "link": lnk_val}

                                links_atuais = re.findall(r'(https?://[^\s]+)', lnk_val or "")
                                links_antigos = re.findall(r'(https?://[^\s]+)', evidencia_72_salva or "")
                                if lnk_val != evidencia_72_salva and links_atuais and links_atuais != links_antigos:
                                        st.session_state[f"links_pendentes_7_2_{ano_sel}"] = links_atuais
                                        st.session_state[f"gatilho_modal_7_2_{ano_sel}"] = True

                        col1, col2 = st.columns([1, 1])
                        with col1:
                                st.text_input(
                                        "Link do Plano ou XYZ:",
                                        value=v_salvo_72,
                                        key=chave_val_72,
                                        on_change=cb_processa_e_salva_72,
                                        placeholder="http://www... ou XYZ"
                                )
                                current_txt_72 = st.session_state.get(chave_val_72, v_salvo_72).strip().upper()
                                fb_pts_72 = 0.0 if current_txt_72 in ["XYZ", ""] else 2.0
                                st.metric(label="Pontuação do Quesito", value=f"{fb_pts_72:.1f} pts")

                        with col2:
                                link_72 = st.text_area(
                                        "Link/Evidência (7.2):",
                                        value=evidencia_72_salva,
                                        key=chave_link_72,
                                        on_change=cb_processa_e_salva_72,
                                        placeholder="Link da transparência, site da agência reguladora ou portal do município...",
                                        height=130
                                )
                                placeholder_links_72 = st.empty()
                                links_72_visuais = re.findall(r'(https?://[^\s]+)', link_72 or "")
                                if links_72_visuais:
                                        placeholder_links_72.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_72_visuais]))

                        cor_txt_72 = "#28a745" if fb_pts_72 > 0 else "#6c757d"
                        st.markdown(f"<span style='color:{cor_txt_72}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 7.2: +{fb_pts_72:.1f} pontos</span>", unsafe_allow_html=True)
                        bloco_comentarios("7.2", res_data, ano_sel)


        # =============================================================================
        # QUESITO 7.3 • METAS DE ABASTECIMENTO DE ÁGUA
        # =============================================================================
        with st.container(key=f"container_bloco_saneamento_7_3_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 7.3 - Fixação de Metas de Distribuição de Água", expanded=True):
                        st.subheader("7.3 • Metas de Abastecimento de Água")
                        st.write("**O Plano Municipal ou Regional de Saneamento Básico possui metas de abastecimento de água potável?**")

                        opts73 = {"Selecione...": 0.0, "Sim – 10": 10.0, "Não – 00": 0.0}
                        lista_opts73 = list(opts73.keys())

                        d73 = res_data.get("7.3", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        if d73 is None: d73 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                        v_salvo_73 = d73.get("valor", "Selecione...")
                        if v_salvo_73 not in lista_opts73: v_salvo_73 = "Selecione..."

                        evidencia_73_salva = d73.get("link", "")
                        chave_radio_73 = f"r_73_select_{ano_sel}"
                        chave_link_73 = f"l_73_txt_area_{ano_sel}"

                        def cb_processa_e_salva_73():
                                lnk_val = st.session_state.get(chave_link_73, evidencia_73_salva).strip()
                                val_salvar = st.session_state.get(chave_radio_73, v_salvo_73)
                                
                                pts_calculados = opts73.get(val_salvar, 0.0)
                                save_resp("7.3", val_salvar, float(pts_calculados), lnk_val)
                                res_data["7.3"] = {"valor": val_salvar, "pontos": float(pts_calculados), "link": lnk_val}

                                links_atuais = re.findall(r'(https?://[^\s]+)', lnk_val or "")
                                links_antigos = re.findall(r'(https?://[^\s]+)', evidencia_73_salva or "")
                                if lnk_val != evidencia_73_salva and links_atuais and links_atuais != links_antigos:
                                        st.session_state[f"links_pendentes_7_3_{ano_sel}"] = links_atuais
                                        st.session_state[f"gatilho_modal_7_3_{ano_sel}"] = True

                        col1, col2 = st.columns([1, 1])
                        with col1:
                                idx_salvo73 = lista_opts73.index(v_salvo_73)
                                st.radio(
                                        "Selecione uma opção (7.3):",
                                        options=lista_opts73,
                                        index=idx_salvo73,
                                        key=chave_radio_73,
                                        on_change=cb_processa_e_salva_73
                                )

                        with col2:
                                link_73 = st.text_area(
                                        "Link/Evidência (7.3):",
                                        value=evidencia_73_salva,
                                        key=chave_link_73,
                                        on_change=cb_processa_e_salva_73,
                                        placeholder="Páginas específicas do plano contendo o capítulo de metas físicas e cronogramas de água...",
                                        height=110
                                )
                                placeholder_links_73 = st.empty()
                                links_73_visuais = re.findall(r'(https?://[^\s]+)', link_73 or "")
                                if links_73_visuais:
                                        placeholder_links_73.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_73_visuais]))

                        v_atual_73 = st.session_state.get(chave_radio_73, v_salvo_73)
                        pts_atuais_73 = opts73.get(v_atual_73, 0.0)
                        cor_txt_73 = "#28a745" if pts_atuais_73 > 0 else ("#6c757d" if v_atual_73 == "Selecione..." else "#dc3545")
                        st.markdown(f"<span style='color:{cor_txt_73}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 7.3: +{pts_atuais_73:.1f} pontos</span>", unsafe_allow_html=True)
                        bloco_comentarios("7.3", res_data, ano_sel)


        # =============================================================================
        # QUESITO 7.3.1 • DETALHAMENTO DAS METAS (MÚLTIPLA ESCOLHA)
        # =============================================================================
        with st.container(key=f"container_bloco_saneamento_7_3_1_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 7.3.1 - Detalhamento das Metas Estabelecidas", expanded=True):
                        st.subheader("7.3.1 • Metas de Qualidade e Eficiência")
                        st.write("**Assinale quais as metas estabelecidas sobre abastecimento de água potável:**")

                        opts731 = {
                                "Metas de expansão do serviço de abastecimento de água – 00": 0.0,
                                "Metas de redução de perdas na distribuição de água tratada – 2,5": 2.5,
                                "Metas de qualidade na prestação do serviço de abastecimento de água – 2,5": 2.5,
                                "Metas de eficiência e de uso racional da água – 2,5": 2.5,
                                "Estabelecimento de volume mínimo de abastecimento de água per capita – 2,5": 2.5,
                                "Estabelecimento de direitos e deveres dos usuários – 2,5": 2.5,
                                "Meta de universalização do abastecimento de água potável até 31 de dezembro de 2033 – 2,5": 2.5,
                                "Estabelecimento de cronograma para o atingimento das metas assinaladas acima – 05": 5.0
                        }

                        d731 = res_data.get("7.3.1", {"valor": "[]", "pontos": 0.0, "link": ""})
                        if d731 is None: d731 = {"valor": "[]", "pontos": 0.0, "link": ""}

                        texto_seguro_731 = str(d731.get("valor", "[]"))
                        evidencia_731_salva = d731.get("link", "")
                        chave_link_731 = f"l_731_txt_area_{ano_sel}"

                        def cb_processa_e_salva_731():
                                lnk_val = st.session_state.get(chave_link_731, evidencia_731_salva).strip()
                                lista_selecionados = []
                                pts_totais = 0.0
                                
                                for idx, (txt, pts) in enumerate(opts731.items()):
                                        if st.session_state.get(f"ck_731_opt_{idx}_{ano_sel}", False):
                                                lista_selecionados.append(txt)
                                                pts_totais += pts

                                val_salvar = str(lista_selecionados)
                                save_resp("7.3.1", val_salvar, float(pts_totais), lnk_val)
                                res_data["7.3.1"] = {"valor": val_salvar, "pontos": float(pts_totais), "link": lnk_val}

                                links_atuais = re.findall(r'(https?://[^\s]+)', lnk_val or "")
                                links_antigos = re.findall(r'(https?://[^\s]+)', evidencia_731_salva or "")
                                if lnk_val != evidencia_731_salva and links_atuais and links_atuais != links_antigos:
                                        st.session_state[f"links_pendentes_7_3_1_{ano_sel}"] = links_atuais
                                        st.session_state[f"gatilho_modal_7_3_1_{ano_sel}"] = True

                        col1, col2 = st.columns([1, 1])
                        with col1:
                                st.write("*Selecione os parâmetros contemplados:*")
                                for i, (txt, pts) in enumerate(opts731.items()):
                                        marcado = (txt in texto_seguro_731) if texto_seguro_731 and texto_seguro_731 != "[]" else False
                                        st.checkbox(
                                                txt,
                                                value=marcado,
                                                key=f"ck_731_opt_{i}_{ano_sel}",
                                                on_change=cb_processa_e_salva_731
                                        )

                        with col2:
                                link_731 = st.text_area(
                                        "Link/Evidência (7.3.1):",
                                        value=evidencia_731_salva,
                                        key=chave_link_731,
                                        on_change=cb_processa_e_salva_731,
                                        placeholder="Links para anexos de engenharia municipal ou relatórios oficiais da regulação setorial...",
                                        height=280
                                )
                                placeholder_links_731 = st.empty()
                                links_731_visuais = re.findall(r'(https?://[^\s]+)', link_731 or "")
                                if links_731_visuais:
                                        placeholder_links_731.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_731_visuais]))

                        fb_pts_731 = sum([pts for idx, (txt, pts) in enumerate(opts731.items()) if st.session_state.get(f"ck_731_opt_{idx}_{ano_sel}", False)])
                        cor_txt_731 = "#28a745" if fb_pts_731 > 0 else "#6c757d"
                        st.markdown(f"<span style='color:{cor_txt_731}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 7.3.1: +{fb_pts_731:.1f} pontos</span>", unsafe_allow_html=True)
                        bloco_comentarios("7.3.1", res_data, ano_sel)


        # =============================================================================
        # QUESITO 7.3.2 • DATA DE UNIVERSALIZAÇÃO
        # =============================================================================
        with st.container(key=f"container_bloco_saneamento_7_3_2_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 7.3.2 - Prazo Limite do Marco Legal do Saneamento", expanded=True):
                        st.subheader("7.3.2 • Data Limite de Universalização")
                        st.write("**Qual a data prevista para universalização do abastecimento de água potável no município?**")
                        st.caption("ℹ *Caso já tenha sido universalizado por completo, configure a data regulamentar padrão **01/01/2001**.*")

                        d732 = res_data.get("7.3.2", {"valor": "31/12/2033", "pontos": 0.0, "link": ""})
                        if d732 is None: d732 = {"valor": "31/12/2033", "pontos": 0.0, "link": ""}

                        try:
                                dia_salvo, mes_salvo, ano_salvo = map(int, d732["valor"].split("/"))
                        except:
                                dia_salvo, mes_salvo, ano_salvo = 31, 12, 2033

                        evidencia_732_salva = d732.get("link", "")
                        chave_d = f"q732_d_num_{ano_sel}"
                        chave_m = f"q732_m_num_{ano_sel}"
                        chave_a = f"q732_a_num_{ano_sel}"
                        chave_link_732 = f"l_732_txt_area_{ano_sel}"

                        def cb_processa_e_salva_732():
                                lnk_val = st.session_state.get(chave_link_732, evidencia_732_salva).strip()
                                d_v = st.session_state.get(chave_d, dia_salvo)
                                m_v = st.session_state.get(chave_m, mes_salvo)
                                a_v = st.session_state.get(chave_a, ano_salvo)
                                
                                # Regra de corte baseada nas diretrizes federais (31/12/2033)
                                if a_v > 2033 or (a_v == 2033 and m_v == 12 and d_v > 31) or (a_v == 2033 and m_v > 12):
                                        pts_calculados = -5.0
                                else:
                                        pts_calculados = 0.0
                                        
                                val_salvar = f"{d_v:02d}/{m_v:02d}/{a_v}"
                                save_resp("7.3.2", val_salvar, float(pts_calculados), lnk_val)
                                res_data["7.3.2"] = {"valor": val_salvar, "pontos": float(pts_calculados), "link": lnk_val}

                                links_atuais = re.findall(r'(https?://[^\s]+)', lnk_val or "")
                                links_antigos = re.findall(r'(https?://[^\s]+)', evidencia_732_salva or "")
                                if lnk_val != evidencia_732_salva and links_atuais and links_atuais != links_antigos:
                                        st.session_state[f"links_pendentes_7_3_2_{ano_sel}"] = links_atuais
                                        st.session_state[f"gatilho_modal_7_3_2_{ano_sel}"] = True

                        col1, col2 = st.columns([1, 1])
                        with col1:
                                c_dia, c_mes, c_ano = st.columns(3)
                                with c_dia:
                                        st.number_input("Dia", min_value=1, max_value=31, value=dia_salvo, key=chave_d, on_change=cb_processa_e_salva_732)
                                with c_mes:
                                        st.number_input("Mês", min_value=1, max_value=12, value=mes_salvo, key=chave_m, on_change=cb_processa_e_salva_732)
                                with c_ano:
                                        st.number_input("Ano", min_value=2000, max_value=2100, value=ano_salvo, key=chave_a, on_change=cb_processa_e_salva_732)

                                cur_d = st.session_state.get(chave_d, dia_salvo)
                                cur_m = st.session_state.get(chave_m, mes_salvo)
                                cur_a = st.session_state.get(chave_a, ano_salvo)
                                if cur_a > 2033 or (cur_a == 2033 and cur_m == 12 and cur_d > 31) or (cur_a == 2033 and cur_m > 12):
                                        fb_pts_732 = -5.0
                                else:
                                        fb_pts_732 = 0.0
                                st.metric(label="Penalização por Atraso", value=f"{fb_pts_732:.1f} pts")

                        with col2:
                                link_732 = st.text_area(
                                        "Link/Evidência (7.3.2):",
                                        value=evidencia_732_salva,
                                        key=chave_link_732,
                                        on_change=cb_processa_e_salva_732,
                                        placeholder="Seção específica contendo o plano de metas consolidadas de universalização de recursos hídricos...",
                                        height=140
                                )
                                placeholder_links_732 = st.empty()
                                links_732_visuais = re.findall(r'(https?://[^\s]+)', link_732 or "")
                                if links_732_visuais:
                                        placeholder_links_732.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_732_visuais]))

                        cor_txt_732 = "#28a745" if fb_pts_732 == 0.0 else "#`dc3545"
                        st.markdown(f"<span style='color:{cor_txt_732}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 7.3.2: {fb_pts_732:.1f} pontos</span>", unsafe_allow_html=True)
                        bloco_comentarios("7.3.2", res_data, ano_sel)

        # =============================================================================
        # GATILHOS DOS MODAIS AUTOMÁTICOS (Colocar no bloco de modais no topo do arquivo)
        # =============================================================================
        for q_id in ["7_4", "7_4_1", "7_4_2"]:
                if st.session_state.get(f"gatilho_modal_{q_id}_{ano_sel}", False):
                        modal_aviso_link(q_id.replace("_", "."), st.session_state.get(f"links_pendentes_{q_id}_{ano_sel}", []))
                        st.session_state[f"gatilho_modal_{q_id}_{ano_sel}"] = False


        # =============================================================================
        # QUESITO 7.4 • METAS DE COLETA DE ESGOTO
        # =============================================================================
        with st.container(key=f"container_bloco_saneamento_7_4_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 7.4 - Fixação de Metas de Esgotamento Sanitário", expanded=True):
                        st.subheader("7.4 • Metas de Coleta de Esgoto")
                        st.write("**O Plano Municipal ou Regional de Saneamento Básico possui metas de coleta de esgoto?**")

                        opts74 = {"Selecione...": 0.0, "Sim – 10": 10.0, "Não – 00": 0.0}
                        lista_opts74 = list(opts74.keys())

                        d74 = res_data.get("7.4", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        if d74 is None: d74 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                        v_salvo_74 = d74.get("valor", "Selecione...")
                        if v_salvo_74 not in lista_opts74: v_salvo_74 = "Selecione..."

                        evidencia_74_salva = d74.get("link", "")
                        chave_radio_74 = f"r_74_select_{ano_sel}"
                        chave_link_74 = f"l_74_txt_area_{ano_sel}"

                        def cb_processa_e_salva_74():
                                lnk_val = st.session_state.get(chave_link_74, evidencia_74_salva).strip()
                                val_salvar = st.session_state.get(chave_radio_74, v_salvo_74)
                                
                                pts_calculados = opts74.get(val_salvar, 0.0)
                                save_resp("7.4", val_salvar, float(pts_calculados), lnk_val)
                                res_data["7.4"] = {"valor": val_salvar, "pontos": float(pts_calculados), "link": lnk_val}

                                links_atuais = re.findall(r'(https?://[^\s]+)', lnk_val or "")
                                links_antigos = re.findall(r'(https?://[^\s]+)', evidencia_74_salva or "")
                                if lnk_val != evidencia_74_salva and links_atuais and links_atuais != links_antigos:
                                        st.session_state[f"links_pendentes_7_4_{ano_sel}"] = links_atuais
                                        st.session_state[f"gatilho_modal_7_4_{ano_sel}"] = True

                        col1, col2 = st.columns([1, 1])
                        with col1:
                                idx_salvo74 = lista_opts74.index(v_salvo_74)
                                st.radio(
                                        "Selecione uma opção (7.4):",
                                        options=lista_opts74,
                                        index=idx_salvo74,
                                        key=chave_radio_74,
                                        on_change=cb_processa_e_salva_74
                                )

                        with col2:
                                link_74 = st.text_area(
                                        "Link/Evidência (7.4):",
                                        value=evidencia_74_salva,
                                        key=chave_link_74,
                                        on_change=cb_processa_e_salva_74,
                                        placeholder="Páginas do plano que estipulam as metas físicas estruturais para coleta de efluentes...",
                                        height=110
                                )
                                placeholder_links_74 = st.empty()
                                links_74_visuais = re.findall(r'(https?://[^\s]+)', link_74 or "")
                                if links_74_visuais:
                                        placeholder_links_74.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_74_visuais]))

                        v_atual_74 = st.session_state.get(chave_radio_74, v_salvo_74)
                        pts_atuais_74 = opts74.get(v_atual_74, 0.0)
                        cor_txt_74 = "#28a745" if pts_atuais_74 > 0 else ("#6c757d" if v_atual_74 == "Selecione..." else "#dc3545")
                        st.markdown(f"<span style='color:{cor_txt_74}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 7.4: +{pts_atuais_74:.1f} pontos</span>", unsafe_allow_html=True)
                        bloco_comentarios("7.4", res_data, ano_sel)


        # =============================================================================
        # QUESITO 7.4.1 • DETALHAMENTO DAS METAS DE ESGOTO (MÚLTIPLA ESCOLHA)
        # =============================================================================
        with st.container(key=f"container_bloco_saneamento_7_4_1_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 7.4.1 - Detalhamento das Metas de Esgoto Assinaladas", expanded=True):
                        st.subheader("7.4.1 • Parâmetros e Diretrizes do Esgotamento")
                        st.write("**Assinale quais as metas estabelecidas sobre coleta de esgoto:**")

                        opts741 = {
                                "Metas de expansão do serviço de coleta de esgoto – 00": 0.0,
                                "Metas de qualidade na prestação do serviço de coleta de esgoto – 3,5": 3.5,
                                "Meta do reúso de efluentes sanitários – 3,5": 3.5,
                                "Estabelecimento de direitos e deveres dos usuários – 3,5": 3.5,
                                "Meta de universalização da coleta de esgoto até 31 de dezembro de 2033 – 3,5": 3.5,
                                "Estabelecimento de cronograma para o atingimento das metas assinaladas acima – 06": 6.0
                        }

                        d741 = res_data.get("7.4.1", {"valor": "[]", "pontos": 0.0, "link": ""})
                        if d741 is None: d741 = {"valor": "[]", "pontos": 0.0, "link": ""}

                        texto_seguro_741 = str(d741.get("valor", "[]"))
                        evidencia_741_salva = d741.get("link", "")
                        chave_link_741 = f"l_741_txt_area_{ano_sel}"

                        def cb_processa_e_salva_741():
                                lnk_val = st.session_state.get(chave_link_741, evidencia_741_salva).strip()
                                lista_selecionados = []
                                pts_totais = 0.0
                                
                                for idx, (txt, pts) in enumerate(opts741.items()):
                                        if st.session_state.get(f"ck_741_opt_{idx}_{ano_sel}", False):
                                                lista_selecionados.append(txt)
                                                pts_totais += pts

                                val_salvar = str(lista_selecionados)
                                save_resp("7.4.1", val_salvar, float(pts_totais), lnk_val)
                                res_data["7.4.1"] = {"valor": val_salvar, "pontos": float(pts_totais), "link": lnk_val}

                                links_atuais = re.findall(r'(https?://[^\s]+)', lnk_val or "")
                                links_antigos = re.findall(r'(https?://[^\s]+)', evidencia_741_salva or "")
                                if lnk_val != evidencia_741_salva and links_atuais and links_atuais != links_antigos:
                                        st.session_state[f"links_pendentes_7_4_1_{ano_sel}"] = links_atuais
                                        st.session_state[f"gatilho_modal_7_4_1_{ano_sel}"] = True

                        col1, col2 = st.columns([1, 1])
                        with col1:
                                st.write("*Selecione os parâmetros contemplados:*")
                                for i, (txt, pts) in enumerate(opts741.items()):
                                        marcado = (txt in texto_seguro_741) if texto_seguro_741 and texto_seguro_741 != "[]" else False
                                        st.checkbox(
                                                txt,
                                                value=marcado,
                                                key=f"ck_741_opt_{i}_{ano_sel}",
                                                on_change=cb_processa_e_salva_741
                                        )

                        with col2:
                                link_741 = st.text_area(
                                        "Link/Evidência (7.4.1):",
                                        value=evidencia_741_salva,
                                        key=chave_link_741,
                                        on_change=cb_processa_e_salva_741,
                                        placeholder="Anexos técnicos do Plano Municipal ou relatórios da concessionária local...",
                                        height=240
                                )
                                placeholder_links_741 = st.empty()
                                links_741_visuais = re.findall(r'(https?://[^\s]+)', link_741 or "")
                                if links_741_visuais:
                                        placeholder_links_741.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_741_visuais]))

                        fb_pts_741 = sum([pts for idx, (txt, pts) in enumerate(opts741.items()) if st.session_state.get(f"ck_741_opt_{idx}_{ano_sel}", False)])
                        cor_txt_741 = "#28a745" if fb_pts_741 > 0 else "#6c757d"
                        st.markdown(f"<span style='color:{cor_txt_741}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 7.41: +{fb_pts_741:.1f} pontos</span>", unsafe_allow_html=True)
                        bloco_comentarios("7.4.1", res_data, ano_sel)


        # =============================================================================
        # QUESITO 7.4.2 • DATA DE UNIVERSALIZAÇÃO DO ESGOTO
        # =============================================================================
        with st.container(key=f"container_bloco_saneamento_7_4_2_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 7.4.2 - Prazo Limite do Marco Regulatório de Esgoto", expanded=True):
                        st.subheader("7.4.2 • Data Limite de Universalização de Esgoto")
                        st.write("**Qual a data prevista para universalização da coleta de esgoto no município?**")
                        st.caption("ℹ *Caso já tenha sido universalizado por completo, configure a data regulamentar padrão **01/01/2001**.*")

                        d742 = res_data.get("7.4.2", {"valor": "31/12/2033", "pontos": 0.0, "link": ""})
                        if d742 is None: d742 = {"valor": "31/12/2033", "pontos": 0.0, "link": ""}

                        try:
                                dia_salvo, mes_salvo, ano_salvo = map(int, d742["valor"].split("/"))
                        except:
                                dia_salvo, mes_salvo, ano_salvo = 31, 12, 2033

                        evidencia_742_salva = d742.get("link", "")
                        chave_d = f"q742_d_num_{ano_sel}"
                        chave_m = f"q742_m_num_{ano_sel}"
                        chave_a = f"q742_a_num_{ano_sel}"
                        chave_link_742 = f"l_742_txt_area_{ano_sel}"

                        def cb_processa_e_salva_742():
                                lnk_val = st.session_state.get(chave_link_742, evidencia_742_salva).strip()
                                d_v = st.session_state.get(chave_d, dia_salvo)
                                m_v = st.session_state.get(chave_m, mes_salvo)
                                a_v = st.session_state.get(chave_a, ano_salvo)
                                
                                # Regra federal de penalização do Marco Legal do Saneamento (31/12/2033)
                                if a_v > 2033 or (a_v == 2033 and m_v == 12 and d_v > 31) or (a_v == 2033 and m_v > 12):
                                        pts_calculados = -5.0
                                else:
                                        pts_calculados = 0.0
                                        
                                val_salvar = f"{d_v:02d}/{m_v:02d}/{a_v}"
                                save_resp("7.4.2", val_salvar, float(pts_calculados), lnk_val)
                                res_data["7.4.2"] = {"valor": val_salvar, "pontos": float(pts_calculados), "link": lnk_val}

                                links_atuais = re.findall(r'(https?://[^\s]+)', lnk_val or "")
                                links_antigos = re.findall(r'(https?://[^\s]+)', evidencia_742_salva or "")
                                if lnk_val != evidencia_742_salva and links_atuais and links_atuais != links_antigos:
                                        st.session_state[f"links_pendentes_7_4_2_{ano_sel}"] = links_atuais
                                        st.session_state[f"gatilho_modal_7_4_2_{ano_sel}"] = True

                        col1, col2 = st.columns([1, 1])
                        with col1:
                                c_dia, c_mes, c_ano = st.columns(3)
                                with c_dia:
                                        st.number_input("Dia", min_value=1, max_value=31, value=dia_salvo, key=chave_d, on_change=cb_processa_e_salva_742)
                                with c_mes:
                                        st.number_input("Mês", min_value=1, max_value=12, value=mes_salvo, key=chave_m, on_change=cb_processa_e_salva_742)
                                with c_ano:
                                        st.number_input("Ano", min_value=2000, max_value=2100, value=ano_salvo, key=chave_a, on_change=cb_processa_e_salva_742)

                                cur_d = st.session_state.get(chave_d, dia_salvo)
                                cur_m = st.session_state.get(chave_m, mes_salvo)
                                cur_a = st.session_state.get(chave_a, ano_salvo)
                                if cur_a > 2033 or (cur_a == 2033 and cur_m == 12 and cur_d > 31) or (cur_a == 2033 and cur_m > 12):
                                        fb_pts_742 = -5.0
                                else:
                                        fb_pts_742 = 0.0
                                st.metric(label="Penalização por Atraso", value=f"{fb_pts_742:.1f} pts")

                        with col2:
                                link_742 = st.text_area(
                                        "Link/Evidência (7.4.2):",
                                        value=evidencia_742_salva,
                                        key=chave_link_742,
                                        on_change=cb_processa_e_salva_742,
                                        placeholder="Seção contendo o planejamento cronológico de obras e metas de universalização de esgoto...",
                                        height=140
                                )
                                placeholder_links_742 = st.empty()
                                links_742_visuais = re.findall(r'(https?://[^\s]+)', link_742 or "")
                                if links_742_visuais:
                                        placeholder_links_742.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_742_visuais]))

                        cor_txt_742 = "#28a745" if fb_pts_742 == 0.0 else "#dc3545"
                        st.markdown(f"<span style='color:{cor_txt_742}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 7.4.2: {fb_pts_742:.1f} pontos</span>", unsafe_allow_html=True)
                        bloco_comentarios("7.4.2", res_data, ano_sel)

        # =============================================================================
        # GATILHOS DOS MODAIS AUTOMÁTICOS (Colocar no bloco de modais no topo do arquivo)
        # =============================================================================
        for q_id in ["7_5", "7_5_1", "7_6", "7_6_1"]:
                if st.session_state.get(f"gatilho_modal_{q_id}_{ano_sel}", False):
                        modal_aviso_link(q_id.replace("_", "."), st.session_state.get(f"links_pendentes_{q_id}_{ano_sel}", []))
                        st.session_state[f"gatilho_modal_{q_id}_{ano_sel}"] = False


        # =============================================================================
        # QUESITO 7.5 • METAS DE TRATAMENTO DE ESGOTO
        # =============================================================================
        with st.container(key=f"container_bloco_saneamento_7_5_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 7.5 - Planejamento e Tratamento de Efluentes", expanded=True):
                        st.subheader("7.5 • Metas de Tratamento de Esgoto")
                        st.write("**O Plano Municipal ou Regional de Saneamento Básico possui metas de tratamento de esgoto?**")

                        opts75 = {"Selecione...": 0.0, "Sim – 30": 30.0, "Não – 00": 0.0}
                        lista_opts75 = list(opts75.keys())

                        d75 = res_data.get("7.5", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        if d75 is None: d75 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                        v_salvo_75 = d75.get("valor", "Selecione...")
                        if v_salvo_75 not in lista_opts75: v_salvo_75 = "Selecione..."

                        evidencia_75_salva = d75.get("link", "")
                        chave_radio_75 = f"r_75_select_{ano_sel}"
                        chave_link_75 = f"l_75_txt_area_{ano_sel}"

                        def cb_processa_e_salva_75():
                                lnk_val = st.session_state.get(chave_link_75, evidencia_75_salva).strip()
                                val_salvar = st.session_state.get(chave_radio_75, v_salvo_75)
                                
                                pts_calculados = opts75.get(val_salvar, 0.0)
                                save_resp("7.5", val_salvar, float(pts_calculados), lnk_val)
                                res_data["7.5"] = {"valor": val_salvar, "pontos": float(pts_calculados), "link": lnk_val}

                                links_atuais = re.findall(r'(https?://[^\s]+)', lnk_val or "")
                                links_antigos = re.findall(r'(https?://[^\s]+)', evidencia_75_salva or "")
                                if lnk_val != evidencia_75_salva and links_atuais and links_atuais != links_antigos:
                                        st.session_state[f"links_pendentes_7_5_{ano_sel}"] = links_atuais
                                        st.session_state[f"gatilho_modal_7_5_{ano_sel}"] = True

                        col1, col2 = st.columns([1, 1])
                        with col1:
                                idx_salvo75 = lista_opts75.index(v_salvo_75)
                                st.radio(
                                        "Selecione uma opção (7.5):",
                                        options=lista_opts75,
                                        index=idx_salvo75,
                                        key=chave_radio_75,
                                        on_change=cb_processa_e_salva_75
                                )

                        with col2:
                                link_75 = st.text_area(
                                        "Link/Evidência (7.5):",
                                        value=evidencia_75_salva,
                                        key=chave_link_75,
                                        on_change=cb_processa_e_salva_75,
                                        placeholder="Páginas do plano contendo os compromissos de evolução do tratamento de esgoto...",
                                        height=110
                                )
                                placeholder_links_75 = st.empty()
                                links_75_visuais = re.findall(r'(https?://[^\s]+)', link_75 or "")
                                if links_75_visuais:
                                        placeholder_links_75.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_75_visuais]))

                        v_atual_75 = st.session_state.get(chave_radio_75, v_salvo_75)
                        pts_atuais_75 = opts75.get(v_atual_75, 0.0)
                        cor_txt_75 = "#28a745" if pts_atuais_75 > 0 else ("#6c757d" if v_atual_75 == "Selecione..." else "#dc3545")
                        st.markdown(f"<span style='color:{cor_txt_75}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 7.5: +{pts_atuais_75:.1f} pontos</span>", unsafe_allow_html=True)
                        bloco_comentarios("7.5", res_data, ano_sel)


        # =============================================================================
        # QUESITO 7.5.1 • DATA DE UNIVERSALIZAÇÃO DO TRATAMENTO
        # =============================================================================
        with st.container(key=f"container_bloco_saneamento_7_5_1_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 7.5.1 - Prazo Limite do Marco Legal do Tratamento de Esgoto", expanded=True):
                        st.subheader("7.5.1 • Data de Universalização do Tratamento")
                        st.write("**Qual a data prevista para universalização do tratamento de esgoto no município?**")
                        st.caption("ℹ *Caso já tenha sido universalizado por completo, configure a data regulamentar padrão **01/01/2001**.*")

                        d751 = res_data.get("7.5.1", {"valor": "31/12/2033", "pontos": 0.0, "link": ""})
                        if d751 is None: d751 = {"valor": "31/12/2033", "pontos": 0.0, "link": ""}

                        try:
                                dia_salvo, mes_salvo, ano_salvo = map(int, d751["valor"].split("/"))
                        except:
                                dia_salvo, mes_salvo, ano_salvo = 31, 12, 2033

                        evidencia_751_salva = d751.get("link", "")
                        chave_d = f"q751_d_num_{ano_sel}"
                        chave_m = f"q751_m_num_{ano_sel}"
                        chave_a = f"q751_a_num_{ano_sel}"
                        chave_link_751 = f"l_751_txt_area_{ano_sel}"

                        def cb_processa_e_salva_751():
                                lnk_val = st.session_state.get(chave_link_751, evidencia_751_salva).strip()
                                d_v = st.session_state.get(chave_d, dia_salvo)
                                m_v = st.session_state.get(chave_m, mes_salvo)
                                a_v = st.session_state.get(chave_a, ano_salvo)
                                
                                if a_v > 2033 or (a_v == 2033 and m_v == 12 and d_v > 31) or (a_v == 2033 and m_v > 12):
                                        pts_calculados = -5.0
                                else:
                                        pts_calculados = 0.0
                                        
                                val_salvar = f"{d_v:02d}/{m_v:02d}/{a_v}"
                                save_resp("7.5.1", val_salvar, float(pts_calculados), lnk_val)
                                res_data["7.5.1"] = {"valor": val_salvar, "pontos": float(pts_calculados), "link": lnk_val}

                                links_atuais = re.findall(r'(https?://[^\s]+)', lnk_val or "")
                                links_antigos = re.findall(r'(https?://[^\s]+)', evidencia_751_salva or "")
                                if lnk_val != evidencia_751_salva and links_atuais and links_atuais != links_antigos:
                                        st.session_state[f"links_pendentes_7_5_1_{ano_sel}"] = links_atuais
                                        st.session_state[f"gatilho_modal_7_5_1_{ano_sel}"] = True

                        col1, col2 = st.columns([1, 1])
                        with col1:
                                c_dia, c_mes, c_ano = st.columns(3)
                                with c_dia:
                                        st.number_input("Dia", min_value=1, max_value=31, value=dia_salvo, key=chave_d, on_change=cb_processa_e_salva_751)
                                with c_mes:
                                        st.number_input("Mês", min_value=1, max_value=12, value=mes_salvo, key=chave_m, on_change=cb_processa_e_salva_751)
                                with c_ano:
                                        st.number_input("Ano", min_value=2000, max_value=2100, value=ano_salvo, key=chave_a, on_change=cb_processa_e_salva_751)

                                cur_d = st.session_state.get(chave_d, dia_salvo)
                                cur_m = st.session_state.get(chave_m, mes_salvo)
                                cur_a = st.session_state.get(chave_a, ano_salvo)
                                if cur_a > 2033 or (cur_a == 2033 and cur_m == 12 and cur_d > 31) or (cur_a == 2033 and cur_m > 12):
                                        fb_pts_751 = -5.0
                                else:
                                        fb_pts_751 = 0.0
                                st.metric(label="Penalização por Atraso", value=f"{fb_pts_751:.1f} pts")

                        with col2:
                                link_751 = st.text_area(
                                        "Link/Evidência (7.5.1):",
                                        value=evidencia_751_salva,
                                        key=chave_link_751,
                                        on_change=cb_processa_e_salva_751,
                                        placeholder="Páginas do cronograma físico-financeiro de expansão de tratamento...",
                                        height=140
                                )
                                placeholder_links_751 = st.empty()
                                links_751_visuais = re.findall(r'(https?://[^\s]+)', link_751 or "")
                                if links_751_visuais:
                                        placeholder_links_751.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_751_visuais]))

                        cor_txt_751 = "#28a745" if fb_pts_751 == 0.0 else "#dc3545"
                        st.markdown(f"<span style='color:{cor_txt_751}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 7.5.1: {fb_pts_751:.1f} pontos</span>", unsafe_allow_html=True)
                        bloco_comentarios("7.5.1", res_data, ano_sel)


        # =============================================================================
        # QUESITO 7.6 • METAS DE DRENAGEM URBANAS
        # =============================================================================
        with st.container(key=f"container_bloco_saneamento_7_6_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 7.6 - Diretrizes de Drenagem e Águas Pluviais", expanded=True):
                        st.subheader("7.6 • Metas de Drenagem Urbana")
                        st.write("**O Plano Municipal ou Regional de Saneamento Básico possui metas de drenagem e manejo de águas pluviais urbanas?**")

                        opts76 = {"Selecione...": 0.0, "Sim": 0.0, "Não": 0.0}
                        lista_opts76 = list(opts76.keys())

                        d76 = res_data.get("7.6", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        if d76 is None: d76 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                        v_salvo_76 = d76.get("valor", "Selecione...")
                        if v_salvo_76 not in lista_opts76: v_salvo_76 = "Selecione..."

                        evidencia_76_salva = d76.get("link", "")
                        chave_radio_76 = f"r_76_select_{ano_sel}"
                        chave_link_76 = f"l_76_txt_area_{ano_sel}"

                        def cb_processa_e_salva_76():
                                lnk_val = st.session_state.get(chave_link_76, evidencia_76_salva).strip()
                                val_salvar = st.session_state.get(chave_radio_76, v_salvo_76)
                                
                                pts_calculados = opts76.get(val_salvar, 0.0)
                                save_resp("7.6", val_salvar, float(pts_calculados), lnk_val)
                                res_data["7.6"] = {"valor": val_salvar, "pontos": float(pts_calculados), "link": lnk_val}

                                links_atuais = re.findall(r'(https?://[^\s]+)', lnk_val or "")
                                links_antigos = re.findall(r'(https?://[^\s]+)', evidencia_76_salva or "")
                                if lnk_val != evidencia_76_salva and links_atuais and links_atuais != links_antigos:
                                        st.session_state[f"links_pendentes_7_6_{ano_sel}"] = links_atuais
                                        st.session_state[f"gatilho_modal_7_6_{ano_sel}"] = True

                        col1, col2 = st.columns([1, 1])
                        with col1:
                                idx_salvo76 = lista_opts76.index(v_salvo_76)
                                st.radio(
                                        "Selecione uma opção (7.6):",
                                        options=lista_opts76,
                                        index=idx_salvo76,
                                        key=chave_radio_76,
                                        on_change=cb_processa_e_salva_76
                                )

                        with col2:
                                link_76 = st.text_area(
                                        "Link/Evidência (7.6):",
                                        value=evidencia_76_salva,
                                        key=chave_link_76,
                                        on_change=cb_processa_e_salva_76,
                                        placeholder="Seções ou anexos voltados ao gerenciamento de águas pluviais...",
                                        height=110
                                )
                                placeholder_links_76 = st.empty()
                                links_76_visuais = re.findall(r'(https?://[^\s]+)', link_76 or "")
                                if links_76_visuais:
                                        placeholder_links_76.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_76_visuais]))

                        st.markdown(f"<span style='color:#6c757d; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 7.6: +0.0 pontos (Informativo)</span>", unsafe_allow_html=True)
                        bloco_comentarios("7.6", res_data, ano_sel)


        # =============================================================================
        # QUESITO 7.6.1 • DETALHAMENTO DAS METAS DE DRENAGEM (MÚLTIPLA ESCOLHA)
        # =============================================================================
        with st.container(key=f"container_bloco_saneamento_7_6_1_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 7.6.1 - Detalhes do Escopo de Manejo Pluvial", expanded=True):
                        st.subheader("7.6.1 • Escopo e Cronogramas de Drenagem")
                        st.write("**Assinale quais as metas estabelecidas sobre drenagem e manejo de águas pluviais urbanas:**")

                        opts761 = {
                                "Metas de expansão do serviço de drenagem e manejo de águas pluviais urbanas": 0.0,
                                "Metas de qualidade na prestação do serviço de drenagem e manejo de águas pluviais urbanas": 0.0,
                                "Metas de aproveitamento de águas da chuva": 0.0,
                                "Estabelecimento de direitos e deveres dos usuários": 0.0,
                                "Estabelecimento de cronograma para o atingimento das metas assinaladas acima": 0.0
                        }

                        d761 = res_data.get("7.6.1", {"valor": "[]", "pontos": 0.0, "link": ""})
                        if d761 is None: d761 = {"valor": "[]", "pontos": 0.0, "link": ""}

                        texto_seguro_761 = str(d761.get("valor", "[]"))
                        evidencia_761_salva = d761.get("link", "")
                        chave_link_761 = f"l_761_txt_area_{ano_sel}"

                        def cb_processa_e_salva_761():
                                lnk_val = st.session_state.get(chave_link_761, evidencia_761_salva).strip()
                                lista_selecionados = []
                                pts_totais = 0.0
                                
                                for idx, (txt, pts) in enumerate(opts761.items()):
                                        if st.session_state.get(f"ck_761_opt_{idx}_{ano_sel}", False):
                                                lista_selecionados.append(txt)
                                                pts_totais += pts

                                val_salvar = str(lista_selecionados)
                                save_resp("7.6.1", val_salvar, float(pts_totais), lnk_val)
                                res_data["7.6.1"] = {"valor": val_salvar, "pontos": float(pts_totais), "link": lnk_val}

                                links_atuais = re.findall(r'(https?://[^\s]+)', lnk_val or "")
                                links_antigos = re.findall(r'(https?://[^\s]+)', evidencia_761_salva or "")
                                if lnk_val != evidencia_761_salva and links_atuais and links_atuais != links_antigos:
                                        st.session_state[f"links_pendentes_7_6_1_{ano_sel}"] = links_atuais
                                        st.session_state[f"gatilho_modal_7_6_1_{ano_sel}"] = True

                        col1, col2 = st.columns([1, 1])
                        with col1:
                                st.write("*Selecione os parâmetros contemplados:*")
                                for i, (txt, pts) in enumerate(opts761.items()):
                                        marcado = (txt in texto_seguro_761) if texto_seguro_761 and texto_seguro_761 != "[]" else False
                                        st.checkbox(
                                                txt,
                                                value=marcado,
                                                key=f"ck_761_opt_{i}_{ano_sel}",
                                                on_change=cb_processa_e_salva_761
                                        )

                        with col2:
                                link_761 = st.text_area(
                                        "Link/Evidência (7.6.1):",
                                        value=evidencia_761_salva,
                                        key=chave_link_761,
                                        on_change=cb_processa_e_salva_761,
                                        placeholder="Páginas do plano que comprovem os eixos de macrodrenagem e diretrizes sustentáveis...",
                                        height=220
                                )
                                placeholder_links_761 = st.empty()
                                links_761_visuais = re.findall(r'(https?://[^\s]+)', link_761 or "")
                                if links_761_visuais:
                                        placeholder_links_761.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_761_visuais]))

                        st.markdown(f"<span style='color:#6c757d; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 7.6.1: +0.0 pontos (Informativo)</span>", unsafe_allow_html=True)
                        bloco_comentarios("7.6.1", res_data, ano_sel)

       # =============================================================================
        # GATILHOS DOS MODAIS AUTOMÁTICOS (Colocar no bloco de modais no topo do arquivo)
        # =============================================================================
        for q_id in ["7_7", "7_7_1", "7_8", "7_8_1", "7_8_1_1"]:
                if st.session_state.get(f"gatilho_modal_{q_id}_{ano_sel}", False):
                        modal_aviso_link(q_id.replace("_", "."), st.session_state.get(f"links_pendentes_{q_id}_{ano_sel}", []))
                        st.session_state[f"gatilho_modal_{q_id}_{ano_sel}"] = False


        # =============================================================================
        # QUESITO 7.7 • MONITORAMENTO DE ÁGUA E ESGOTO
        # =============================================================================
        with st.container(key=f"container_bloco_saneamento_7_7_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 7.7 - Monitoramento e Avaliação das Ações e Metas", expanded=True):
                        st.subheader("7.7 • Monitoramento de Água e Esgoto")
                        st.write("**Realiza monitoramento e avaliação das ações e metas relacionadas ao abastecimento de água potável e esgotamento sanitário?**")

                        opts77 = {"Selecione...": 0.0, "Sim – 30": 30.0, "Não – 00": 0.0}
                        lista_opts77 = list(opts77.keys())

                        d77 = res_data.get("7.7", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        if d77 is None: d77 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                        v_salvo_77 = d77.get("valor", "Selecione...")
                        if v_salvo_77 not in lista_opts77: v_salvo_77 = "Selecione..."

                        evidencia_77_salva = d77.get("link", "")
                        chave_radio_77 = f"r_77_select_{ano_sel}"
                        chave_link_77 = f"l_77_txt_area_{ano_sel}"

                        def cb_processa_e_salva_77():
                                lnk_val = st.session_state.get(chave_link_77, evidencia_77_salva).strip()
                                val_salvar = st.session_state.get(chave_radio_77, v_salvo_77)
                                
                                pts_calculados = opts77.get(val_salvar, 0.0)
                                save_resp("7.7", val_salvar, float(pts_calculados), lnk_val)
                                res_data["7.7"] = {"valor": val_salvar, "pontos": float(pts_calculados), "link": lnk_val}

                                links_atuais = re.findall(r'(https?://[^\s]+)', lnk_val or "")
                                links_antigos = re.findall(r'(https?://[^\s]+)', evidencia_77_salva or "")
                                if lnk_val != evidencia_77_salva and links_atuais and links_atuais != links_antigos:
                                        st.session_state[f"links_pendentes_7_7_{ano_sel}"] = links_atuais
                                        st.session_state[f"gatilho_modal_7_7_{ano_sel}"] = True

                        col1, col2 = st.columns([1, 1])
                        with col1:
                                idx_salvo77 = lista_opts77.index(v_salvo_77)
                                st.radio(
                                        "Selecione uma opção (7.7):",
                                        options=lista_opts77,
                                        index=idx_salvo77,
                                        key=chave_radio_77,
                                        on_change=cb_processa_e_salva_77
                                )

                        with col2:
                                link_77 = st.text_area(
                                        "Link/Evidência (7.7):",
                                        value=evidencia_77_salva,
                                        key=chave_link_77,
                                        on_change=cb_processa_e_salva_77,
                                        placeholder="Insira as evidências do monitoramento sistemático...",
                                        height=110
                                )
                                placeholder_links_77 = st.empty()
                                links_77_visuais = re.findall(r'(https?://[^\s]+)', link_77 or "")
                                if links_77_visuais:
                                        placeholder_links_77.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_77_visuais]))

                        v_atual_77 = st.session_state.get(chave_radio_77, v_salvo_77)
                        pts_atuais_77 = opts77.get(v_atual_77, 0.0)
                        cor_txt_77 = "#28a745" if pts_atuais_77 > 0 else ("#6c757d" if v_atual_77 == "Selecione..." else "#dc3545")
                        st.markdown(f"<span style='color:{cor_txt_77}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 7.7: +{pts_atuais_77:.1f} pontos</span>", unsafe_allow_html=True)
                        bloco_comentarios("7.7", res_data, ano_sel)


        # =============================================================================
        # QUESITO 7.7.1 • FORMA DE MONITORAMENTO (MÚLTIPLA ESCOLHA)
        # =============================================================================
        with st.container(key=f"container_bloco_saneamento_7_7_1_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 7.7.1 - Metodologia e Instrumentos de Controle", expanded=True):
                        st.subheader("7.7.1 • Forma de Monitoramento")
                        st.write("**De que forma é realizado o monitoramento e avaliação relacionadas ao abastecimento de água potável e esgotamento sanitário?**")

                        opts771 = {
                                "Relatórios anuais discutidos e/ou publicados": 0.0,
                                "Indicadores de eficácia e eficiência": 0.0,
                                "Avaliação de recursos aplicados": 0.0,
                                "Outro": 0.0
                        }

                        d771 = res_data.get("7.7.1", {"valor": "[]", "pontos": 0.0, "link": ""})
                        if d771 is None: d771 = {"valor": "[]", "pontos": 0.0, "link": ""}

                        texto_seguro_771 = str(d771.get("valor", "[]"))
                        evidencia_771_salva = d771.get("link", "")
                        chave_link_771 = f"l_771_txt_area_{ano_sel}"

                        def cb_processa_e_salva_771():
                                lnk_val = st.session_state.get(chave_link_771, evidencia_771_salva).strip()
                                lista_selecionados = []
                                pts_totais = 0.0
                                
                                for idx, (txt, pts) in enumerate(opts771.items()):
                                        if st.session_state.get(f"ck_771_opt_{idx}_{ano_sel}", False):
                                                lista_selecionados.append(txt)
                                                pts_totais += pts

                                val_salvar = str(lista_selecionados)
                                save_resp("7.7.1", val_salvar, float(pts_totais), lnk_val)
                                res_data["7.7.1"] = {"valor": val_salvar, "pontos": float(pts_totais), "link": lnk_val}

                                links_atuais = re.findall(r'(https?://[^\s]+)', lnk_val or "")
                                links_antigos = re.findall(r'(https?://[^\s]+)', evidencia_771_salva or "")
                                if lnk_val != evidencia_771_salva and links_atuais and links_atuais != links_antigos:
                                        st.session_state[f"links_pendentes_7_7_1_{ano_sel}"] = links_atuais
                                        st.session_state[f"gatilho_modal_7_7_1_{ano_sel}"] = True

                        col1, col2 = st.columns([1, 1])
                        with col1:
                                st.write("*Selecione as opções aplicáveis:*")
                                for i, (txt, pts) in enumerate(opts771.items()):
                                        marcado = (txt in texto_seguro_771) if texto_seguro_771 and texto_seguro_771 != "[]" else False
                                        st.checkbox(
                                                txt,
                                                value=marcado,
                                                key=f"ck_771_opt_{i}_{ano_sel}",
                                                on_change=cb_processa_e_salva_771
                                        )

                        with col2:
                                link_771 = st.text_area(
                                        "Link/Evidência (7.7.1):",
                                        value=evidencia_771_salva,
                                        key=chave_link_771,
                                        on_change=cb_processa_e_salva_771,
                                        placeholder="Links para atas do conselho municipal, painéis SNIS ou relatórios públicos...",
                                        height=180
                                )
                                placeholder_links_771 = st.empty()
                                links_771_visuais = re.findall(r'(https?://[^\s]+)', link_771 or "")
                                if links_771_visuais:
                                        placeholder_links_771.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_771_visuais]))

                        st.markdown(f"<span style='color:#6c757d; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 7.7.1: +0.0 pontos (Informativo)</span>", unsafe_allow_html=True)
                        bloco_comentarios("7.7.1", res_data, ano_sel)


        # =============================================================================
        # QUESITO 7.8 • CRONOGRAMA DE METAS
        # =============================================================================
        with st.container(key=f"container_bloco_saneamento_7_8_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 7.8 - Linha do Tempo e Escalonamento do Plano", expanded=True):
                        st.subheader("7.8 • Cronograma de Metas")
                        st.write("**O Plano Municipal ou Regional de Saneamento Básico possui cronograma com as metas a serem cumpridas?**")

                        opts78 = {"Selecione...": 0.0, "Sim – 20": 20.0, "Não – 00": 0.0}
                        lista_opts78 = list(opts78.keys())

                        d78 = res_data.get("7.8", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        if d78 is None: d78 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                        v_salvo_78 = d78.get("valor", "Selecione...")
                        if v_salvo_78 not in lista_opts78: v_salvo_78 = "Selecione..."

                        evidencia_78_salva = d78.get("link", "")
                        chave_radio_78 = f"r_78_select_{ano_sel}"
                        chave_link_78 = f"l_78_txt_area_{ano_sel}"

                        def cb_processa_e_salva_78():
                                lnk_val = st.session_state.get(chave_link_78, evidencia_78_salva).strip()
                                val_salvar = st.session_state.get(chave_radio_78, v_salvo_78)
                                
                                pts_calculados = opts78.get(val_salvar, 0.0)
                                save_resp("7.8", val_salvar, float(pts_calculados), lnk_val)
                                res_data["7.8"] = {"valor": val_salvar, "pontos": float(pts_calculados), "link": lnk_val}

                                links_atuais = re.findall(r'(https?://[^\s]+)', lnk_val or "")
                                links_antigos = re.findall(r'(https?://[^\s]+)', evidencia_78_salva or "")
                                if lnk_val != evidencia_78_salva and links_atuais and links_atuais != links_antigos:
                                        st.session_state[f"links_pendentes_7_8_{ano_sel}"] = links_atuais
                                        st.session_state[f"gatilho_modal_7_8_{ano_sel}"] = True

                        col1, col2 = st.columns([1, 1])
                        with col1:
                                idx_salvo78 = lista_opts78.index(v_salvo_78)
                                st.radio(
                                        "Selecione uma opção (7.8):",
                                        options=lista_opts78,
                                        index=idx_salvo78,
                                        key=chave_radio_78,
                                        on_change=cb_processa_e_salva_78
                                )

                        with col2:
                                link_78 = st.text_area(
                                        "Link/Evidência (7.8):",
                                        value=evidencia_78_salva,
                                        key=chave_link_78,
                                        on_change=cb_processa_e_salva_78,
                                        placeholder="Páginas do cronograma físico-financeiro quadrienal ou anual...",
                                        height=110
                                )
                                placeholder_links_78 = st.empty()
                                links_78_visuais = re.findall(r'(https?://[^\s]+)', link_78 or "")
                                if links_78_visuais:
                                        placeholder_links_78.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_78_visuais]))

                        v_atual_78 = st.session_state.get(chave_radio_78, v_salvo_78)
                        pts_atuais_78 = opts78.get(v_atual_78, 0.0)
                        cor_txt_78 = "#28a745" if pts_atuais_78 > 0 else ("#6c757d" if v_atual_78 == "Selecione..." else "#dc3545")
                        st.markdown(f"<span style='color:{cor_txt_78}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 7.8: +{pts_atuais_78:.1f} pontos</span>", unsafe_allow_html=True)
                        bloco_comentarios("7.8", res_data, ano_sel)


        # =============================================================================
        # QUESITO 7.8.1 • CUMPRIMENTO DOS PRAZOS ESTIPULADOS
        # =============================================================================
        with st.container(key=f"container_bloco_saneamento_7_8_1_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 7.8.1 - Grau de Adimplemento das Metas e Prazos", expanded=True):
                        st.subheader("7.8.1 • Cumprimento dos Prazos Estipulados")
                        st.write("**As metas do Plano relacionadas ao abastecimento de água potável e esgotamento sanitário estão sendo cumpridas no prazo estipulado?**")

                        opts781 = {
                                "Selecione...": 0.0,
                                "Todas as metas foram cumpridas dentro do prazo – 50": 50.0,
                                "A maior parte das metas foram cumpridas dentro do prazo – 30": 30.0,
                                "A menor parte das metas foram cumpridas dentro do prazo – 10": 10.0,
                                "As metas não foram cumpridas dentro do prazo – 00": 0.0
                        }
                        lista_opts781 = list(opts781.keys())

                        d781 = res_data.get("7.8.1", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        if d781 is None: d781 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                        v_salvo_781 = d781.get("valor", "Selecione...")
                        if v_salvo_781 not in lista_opts781: v_salvo_781 = "Selecione..."

                        evidencia_781_salva = d781.get("link", "")
                        chave_radio_781 = f"r_781_select_{ano_sel}"
                        chave_link_781 = f"l_781_txt_area_{ano_sel}"

                        def cb_processa_e_salva_781():
                                lnk_val = st.session_state.get(chave_link_781, evidencia_781_salva).strip()
                                val_salvar = st.session_state.get(chave_radio_781, v_salvo_781)
                                
                                pts_calculados = opts781.get(val_salvar, 0.0)
                                save_resp("7.8.1", val_salvar, float(pts_calculados), lnk_val)
                                res_data["7.8.1"] = {"valor": val_salvar, "pontos": float(pts_calculados), "link": lnk_val}

                                links_atuais = re.findall(r'(https?://[^\s]+)', lnk_val or "")
                                links_antigos = re.findall(r'(https?://[^\s]+)', evidencia_781_salva or "")
                                if lnk_val != evidencia_781_salva and links_atuais and links_atuais != links_antigos:
                                        st.session_state[f"links_pendentes_7_8_1_{ano_sel}"] = links_atuais
                                        st.session_state[f"gatilho_modal_7_8_1_{ano_sel}"] = True

                        col1, col2 = st.columns([1, 1])
                        with col1:
                                idx_salvo781 = lista_opts781.index(v_salvo_781)
                                st.radio(
                                        "Selecione uma opção (7.8.1):",
                                        options=lista_opts781,
                                        index=idx_salvo781,
                                        key=chave_radio_781,
                                        on_change=cb_processa_e_salva_781
                                )

                        with col2:
                                link_781 = st.text_area(
                                        "Link/Evidência (7.8.1):",
                                        value=evidencia_781_salva,
                                        key=chave_link_781,
                                        on_change=cb_processa_e_salva_781,
                                        placeholder="Relatórios de auditoria da agência reguladora local ou balanço de metas...",
                                        height=130
                                )
                                placeholder_links_781 = st.empty()
                                links_781_visuais = re.findall(r'(https?://[^\s]+)', link_781 or "")
                                if links_781_visuais:
                                        placeholder_links_781.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_781_visuais]))

                        v_atual_781 = st.session_state.get(chave_radio_781, v_salvo_781)
                        pts_atuais_781 = opts781.get(v_atual_781, 0.0)
                        cor_txt_781 = "#28a745" if pts_atuais_781 > 10 else ("#6c757d" if v_atual_781 == "Selecione..." else "#dc3545")
                        st.markdown(f"<span style='color:{cor_txt_781}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 7.8.1: +{pts_atuais_781:.1f} pontos</span>", unsafe_allow_html=True)
                        bloco_comentarios("7.8.1", res_data, ano_sel)


        # =============================================================================
        # QUESITO 7.8.1.1 • MOTIVOS DO NÃO CUMPRIMENTO (MÚLTIPLA ESCOLHA)
        # =============================================================================
        with st.container(key=f"container_bloco_saneamento_7_8_1_1_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 7.8.1.1 - Fatores de Restrição e Descumprimento de Metas", expanded=True):
                        st.subheader("7.8.1.1 • Motivos do Não Cumprimento")
                        st.write("**Assinale os motivos pelos quais as metas relacionadas ao abastecimento de água potável e esgotamento sanitário não estão sendo cumpridas:**")

                        opts7811 = {
                                "Falta de recursos orçamentários": 0.0,
                                "Falta de aprovação legislativa": 0.0,
                                "Atraso na licitação": 0.0,
                                "Não realizou licitação necessária": 0.0,
                                "Falta de pessoal qualificado": 0.0,
                                "Falta de consenso no consórcio intermunicipal": 0.0,
                                "Outros": 0.0
                        }

                        d7811 = res_data.get("7.8.1.1", {"valor": "[]", "pontos": 0.0, "link": ""})
                        if d7811 is None: d7811 = {"valor": "[]", "pontos": 0.0, "link": ""}

                        texto_seguro_7811 = str(d7811.get("valor", "[]"))
                        evidencia_7811_salva = d7811.get("link", "")
                        chave_link_7811 = f"l_7811_txt_area_{ano_sel}"

                        def cb_processa_e_salva_7811():
                                lnk_val = st.session_state.get(chave_link_7811, evidencia_7811_salva).strip()
                                lista_selecionados = []
                                pts_totais = 0.0
                                
                                for idx, (txt, pts) in enumerate(opts7811.items()):
                                        if st.session_state.get(f"ck_7811_opt_{idx}_{ano_sel}", False):
                                                lista_selecionados.append(txt)
                                                pts_totais += pts

                                val_salvar = str(lista_selecionados)
                                save_resp("7.8.1.1", val_salvar, float(pts_totais), lnk_val)
                                res_data["7.8.1.1"] = {"valor": val_salvar, "pontos": float(pts_totais), "link": lnk_val}

                                links_atuais = re.findall(r'(https?://[^\s]+)', lnk_val or "")
                                links_antigos = re.findall(r'(https?://[^\s]+)', evidencia_7811_salva or "")
                                if lnk_val != evidencia_7811_salva and links_atuais and links_atuais != links_antigos:
                                        st.session_state[f"links_pendentes_7_8_1_1_{ano_sel}"] = links_atuais
                                        st.session_state[f"gatilho_modal_7_8_1_1_{ano_sel}"] = True

                        col1, col2 = st.columns([1, 1])
                        with col1:
                                st.write("*Selecione as justificativas apresentadas:*")
                                for i, (txt, pts) in enumerate(opts7811.items()):
                                        marcado = (txt in texto_seguro_7811) if texto_seguro_7811 and texto_seguro_7811 != "[]" else False
                                        st.checkbox(
                                                txt,
                                                value=marcado,
                                                key=f"ck_7811_opt_{i}_{ano_sel}",
                                                on_change=cb_processa_e_salva_7811
                                        )

                        with col2:
                                link_7811 = st.text_area(
                                        "Link/Evidência (7.8.1.1):",
                                        value=evidencia_7811_salva,
                                        key=chave_link_7811,
                                        on_change=cb_processa_e_salva_7811,
                                        placeholder="Páginas de justificativas oficiais, pareceres do comitê técnico ou notificações...",
                                        height=240
                                )
                                placeholder_links_7811 = st.empty()
                                links_7811_visuais = re.findall(r'(https?://[^\s]+)', link_7811 or "")
                                if links_7811_visuais:
                                        placeholder_links_7811.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_7811_visuais]))

                        st.markdown(f"<span style='color:#6c757d; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 7.8.1.1: +0.0 pontos (Informativo)</span>", unsafe_allow_html=True)
                        bloco_comentarios("7.8.1.1", res_data, ano_sel)

        # =============================================================================
        # GATILHOS DOS MODAIS AUTOMÁTICOS (Colocar no bloco de modais no topo do arquivo)
        # =============================================================================
        for q_id in ["7_9", "7_10"]:
                if st.session_state.get(f"gatilho_modal_{q_id}_{ano_sel}", False):
                        modal_aviso_link(q_id.replace("_", "."), st.session_state.get(f"links_pendentes_{q_id}_{ano_sel}", []))
                        st.session_state[f"gatilho_modal_{q_id}_{ano_sel}"] = False


        # =============================================================================
        # QUESITO 7.9 • ÁREAS PRIORITÁRIAS / CRÍTICAS
        # =============================================================================
        with st.container(key=f"container_bloco_saneamento_7_9_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 7.9 - Identificação de Vulnerabilidades Setoriais", expanded=True):
                        st.subheader("7.9 • Áreas Prioritárias / Críticas")
                        st.write("**Possui previsão para áreas prioritárias/críticas de abastecimento de água potável e esgotamento sanitário do município?**")
                        st.caption("ℹ *Ex.: Áreas com assentamentos habitacionais precários, corpos de água degradados (em especial nas regiões de mananciais) ou áreas vulneráveis quanto aos indicadores de saúde pública.*")

                        opts79 = {
                                "Selecione...": 0.0,
                                "Sim – 03": 3.0,
                                "Não – 00": 0.0,
                                "Não há áreas prioritárias/críticas no município – 03": 3.0
                        }
                        lista_opts79 = list(opts79.keys())

                        d79 = res_data.get("7.9", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        if d79 is None: d79 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                        v_salvo_79 = d79.get("valor", "Selecione...")
                        if v_salvo_79 not in lista_opts79: v_salvo_79 = "Selecione..."

                        evidencia_79_salva = d79.get("link", "")
                        chave_radio_79 = f"r_79_select_{ano_sel}"
                        chave_link_79 = f"l_79_txt_area_{ano_sel}"

                        def cb_processa_e_salva_79():
                                lnk_val = st.session_state.get(chave_link_79, evidencia_79_salva).strip()
                                val_salvar = st.session_state.get(chave_radio_79, v_salvo_79)
                                
                                pts_calculados = opts79.get(val_salvar, 0.0)
                                save_resp("7.9", val_salvar, float(pts_calculados), lnk_val)
                                res_data["7.9"] = {"valor": val_salvar, "pontos": float(pts_calculados), "link": lnk_val}

                                links_atuais = re.findall(r'(https?://[^\s]+)', lnk_val or "")
                                links_antigos = re.findall(r'(https?://[^\s]+)', evidencia_79_salva or "")
                                if lnk_val != evidencia_79_salva and links_atuais and links_atuais != links_antigos:
                                        st.session_state[f"links_pendentes_7_9_{ano_sel}"] = links_atuais
                                        st.session_state[f"gatilho_modal_7_9_{ano_sel}"] = True

                        col1, col2 = st.columns([1, 1])
                        with col1:
                                idx_salvo79 = lista_opts79.index(v_salvo_79)
                                st.radio(
                                        "Selecione uma opção (7.9):",
                                        options=lista_opts79,
                                        index=idx_salvo79,
                                        key=chave_radio_79,
                                        on_change=cb_processa_e_salva_79
                                )

                        with col2:
                                link_79 = st.text_area(
                                        "Link/Evidência (7.9):",
                                        value=evidencia_79_salva,
                                        key=chave_link_79,
                                        on_change=cb_processa_e_salva_79,
                                        placeholder="Seção mapeada no Plano Municipal ou relatórios de vulnerabilidade social...",
                                        height=120
                                )
                                placeholder_links_79 = st.empty()
                                links_79_visuais = re.findall(r'(https?://[^\s]+)', link_79 or "")
                                if links_79_visuais:
                                        placeholder_links_79.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_79_visuais]))

                        v_atual_79 = st.session_state.get(chave_radio_79, v_salvo_79)
                        pts_atuais_79 = opts79.get(v_atual_79, 0.0)
                        cor_txt_79 = "#28a745" if pts_atuais_79 > 0 else ("#6c757d" if v_atual_79 == "Selecione..." else "#dc3545")
                        st.markdown(f"<span style='color:{cor_txt_79}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 7.9: +{pts_atuais_79:.1f} pontos</span>", unsafe_allow_html=True)
                        bloco_comentarios("7.9", res_data, ano_sel)


        # =============================================================================
        # QUESITO 7.10 • ÚLTIMA REVISÃO DO PLANO
        # =============================================================================
        with st.container(key=f"container_bloco_saneamento_7_10_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 7.10 - Vigência e Atualização Tempestiva do Plano", expanded=True):
                        st.subheader("7.10 • Última Revisão do Plano")
                        st.write("**Qual a data da última revisão do Plano Municipal ou Regional de Saneamento Básico?**")
                        st.caption("ℹ *Se não houve revisão do plano de saneamento básico, informe a data de início de vigência original dele.*")

                        d710 = res_data.get("7.10", {"valor": "01/01/2015", "pontos": 0.0, "link": ""})
                        if d710 is None: d710 = {"valor": "01/01/2015", "pontos": 0.0, "link": ""}

                        try:
                                dia_salvo, mes_salvo, ano_salvo = map(int, d710["valor"].split("/"))
                        except:
                                dia_salvo, mes_salvo, ano_salvo = 1, 1, 2015

                        evidencia_710_salva = d710.get("link", "")
                        chave_d_710 = f"q710_d_num_{ano_sel}"
                        chave_m_710 = f"q710_m_num_{ano_sel}"
                        chave_a_710 = f"q710_a_num_{ano_sel}"
                        chave_link_710 = f"l_710_txt_area_{ano_sel}"

                        def cb_processa_e_salva_710():
                                lnk_val = st.session_state.get(chave_link_710, evidencia_710_salva).strip()
                                d_v = st.session_state.get(chave_d_710, dia_salvo)
                                m_v = st.session_state.get(chave_m_710, mes_salvo)
                                a_v = st.session_state.get(chave_a_710, ano_salvo)
                                
                                if a_v < 2014 or (a_v == 2014 and m_v < 12) or (a_v == 2014 and m_v == 12 and d_v <= 31):
                                        pts_calculados = -30.0
                                else:
                                        pts_calculados = 0.0
                                        
                                val_salvar = f"{d_v:02d}/{m_v:02d}/{a_v}"
                                save_resp("7.10", val_salvar, float(pts_calculados), lnk_val)
                                res_data["7.10"] = {"valor": val_salvar, "pontos": float(pts_calculados), "link": lnk_val}

                                links_atuais = re.findall(r'(https?://[^\s]+)', lnk_val or "")
                                links_antigos = re.findall(r'(https?://[^\s]+)', evidencia_710_salva or "")
                                if lnk_val != evidencia_710_salva and links_atuais and links_atuais != links_antigos:
                                        st.session_state[f"links_pendentes_7_10_{ano_sel}"] = links_atuais
                                        st.session_state[f"gatilho_modal_7_10_{ano_sel}"] = True

                        col1, col2 = st.columns([1, 1])
                        with col1:
                                c_dia, c_mes, c_ano = st.columns(3)
                                with c_dia:
                                        st.number_input("Dia", min_value=1, max_value=31, value=dia_salvo, key=chave_d_710, on_change=cb_processa_e_salva_710)
                                with c_mes:
                                        st.number_input("Mês", min_value=1, max_value=12, value=mes_salvo, key=chave_m_710, on_change=cb_processa_e_salva_710)
                                with c_ano:
                                        st.number_input("Ano", min_value=1900, max_value=2100, value=ano_salvo, key=chave_a_710, on_change=cb_processa_e_salva_710)

                                cur_d = st.session_state.get(chave_d_710, dia_salvo)
                                cur_m = st.session_state.get(chave_m_710, mes_salvo)
                                cur_a = st.session_state.get(chave_a_710, ano_salvo)
                                if cur_a < 2014 or (cur_a == 2014 and cur_m < 12) or (cur_a == 2014 and cur_m == 12 and cur_d <= 31):
                                        fb_pts_710 = -30.0
                                else:
                                        fb_pts_710 = 0.0
                                st.metric(label="Penalidade por Defasagem", value=f"{fb_pts_710:.1f} pts")

                        with col2:
                                link_710 = st.text_area(
                                        "Link/Evidência (7.10):",
                                        value=evidencia_710_salva,
                                        key=chave_link_710,
                                        on_change=cb_processa_e_salva_710,
                                        placeholder="Página do Diário Oficial que publicou o decreto de revisão ou lei sancionada...",
                                        height=130
                                )
                                placeholder_links_710 = st.empty()
                                links_710_visuais = re.findall(r'(https?://[^\s]+)', link_710 or "")
                                if links_710_visuais:
                                        placeholder_links_710.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_710_visuais]))

                        cor_txt_710 = "#28a745" if fb_pts_710 == 0.0 else "#dc3545"
                        st.markdown(f"<span style='color:{cor_txt_710}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 7.10: {fb_pts_710:.1f} pontos</span>", unsafe_allow_html=True)
                        bloco_comentarios("7.10", res_data, ano_sel)

        # -------------------------------------------------------------------------
        # --- SEÇÃO 8: RESÍDUOS SÓLIDOS -------------------------------------------
        # -------------------------------------------------------------------------
        st.divider()
        st.header("8.0 Gestão de Resíduos Sólidos")
        
       # =============================================================================
        # GATILHOS DOS MODAIS AUTOMÁTICOS (Colocar no bloco de modais no topo do arquivo)
        # =============================================================================
        for q_id in [
                "8_0", "8_1", "8_2", "8_3", "8_3_1", 
                "8_4", "8_4_1", "8_4_2", "8_4_2_1", "8_4_3", "8_4_3_1", "8_4_4"
        ]:
                if st.session_state.get(f"gatilho_modal_{q_id}_{ano_sel}", False):
                        modal_aviso_link(q_id.replace("_", "."), st.session_state.get(f"links_pendentes_{q_id}_{ano_sel}", []))
                        st.session_state[f"gatilho_modal_{q_id}_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 8.0 • PLANO DE GESTÃO INTEGRADA DE RESÍDUOS SÓLIDOS
        # =============================================================================
        with st.container(key=f"container_bloco_residuos_8_0_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 8.0 - Elaboração do Plano de Resíduos Sólidos (PMGIRS/PRGIRS)", expanded=True):
                        st.subheader("8.0 • Existência de Plano Temático")
                        st.write("**Foi elaborado o Plano Municipal ou Regional de Gestão Integrada de Resíduos Sólidos?**")

                        opc80 = ["Selecione...", "Sim", "Não"]
                        d80 = res_data.get("8.0", {"valor": "Selecione...", "link": ""})
                        if d80 is None: d80 = {"valor": "Selecione...", "link": ""}

                        v_salvo_80 = d80.get("valor", "Selecione...")
                        if v_salvo_80 not in opc80: v_salvo_80 = "Selecione..."

                        evidencia_80_salva = d80.get("link", "")
                        chave_radio_80 = f"r_80_select_{ano_sel}"
                        chave_link_80 = f"l_80_txt_area_{ano_sel}"

                        def cb_processa_e_salva_80():
                                lnk_val = st.session_state.get(chave_link_80, evidencia_80_salva).strip()
                                val_salvar = st.session_state.get(chave_radio_80, v_salvo_80)
                                
                                save_resp("8.0", val_salvar, 0.0, lnk_val)
                                res_data["8.0"] = {"valor": val_salvar, "pontos": 0.0, "link": lnk_val}

                                links_atuais = re.findall(r'(https?://[^\s]+)', lnk_val or "")
                                links_antigos = re.findall(r'(https?://[^\s]+)', evidencia_80_salva or "")
                                if lnk_val != evidencia_80_salva and links_atuais and links_atuais != links_antigos:
                                        st.session_state[f"links_pendentes_8_0_{ano_sel}"] = links_atuais
                                        st.session_state[f"gatilho_modal_8_0_{ano_sel}"] = True

                        col1, col2 = st.columns([1, 1])
                        with col1:
                                idx80 = opc80.index(v_salvo_80)
                                st.radio(
                                        "Selecione uma opção (8.0):",
                                        options=opc80,
                                        index=idx80,
                                        key=chave_radio_80,
                                        on_change=cb_processa_e_salva_80
                                )

                        with col2:
                                link_80 = st.text_area(
                                        "Link/Evidência (8.0):",
                                        value=evidencia_80_salva,
                                        key=chave_link_80,
                                        on_change=cb_processa_e_salva_80,
                                        placeholder="Insira o link para o decreto, lei ou o plano digitalizado...",
                                        height=100
                                )
                                placeholder_links_80 = st.empty()
                                links_80_visuais = re.findall(r'(https?://[^\s]+)', link_80 or "")
                                if links_80_visuais:
                                        placeholder_links_80.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_80_visuais]))

                        st.markdown("<span style='color:#6c757d; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 8.0: +0.0 pontos (Referencial)</span>", unsafe_allow_html=True)
                        bloco_comentarios("8.0", res_data, ano_sel)


        # =============================================================================
        # QUESITO 8.1 • INSTRUMENTO NORMATIVO DE PUBLICAÇÃO
        # =============================================================================
        with st.container(key=f"container_bloco_residuos_8_1_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 8.1 - Dados de Formalização Legal do Plano", expanded=True):
                        st.subheader("8.1 • Instrumento Normativo, Número e Data")
                        st.write("**Informe o Instrumento normativo, Número e Data da publicação:**")

                        d81 = res_data.get("8.1", {"valor": "", "link": ""})
                        if d81 is None: d81 = {"valor": "", "link": ""}

                        v_salvo_81 = d81.get("valor", "")
                        chave_texto_81 = f"q81_txt_area_{ano_sel}"

                        def cb_processa_e_salva_81():
                                val_salvar = st.session_state.get(chave_texto_81, v_salvo_81)
                                save_resp("8.1", val_salvar, 0.0, "")
                                res_data["8.1"] = {"valor": val_salvar, "pontos": 0.0, "link": ""}

                                links_atuais = re.findall(r'(https?://[^\s]+)', val_salvar or "")
                                links_antigos = re.findall(r'(https?://[^\s]+)', v_salvo_81 or "")
                                if val_salvar != v_salvo_81 and links_atuais and links_atuais != links_antigos:
                                        st.session_state[f"links_pendentes_8_1_{ano_sel}"] = links_atuais
                                        st.session_state[f"gatilho_modal_8_1_{ano_sel}"] = True

                        col1, col2 = st.columns([1, 1])
                        with col1:
                                texto_81 = st.text_area(
                                        "Dados da Publicação (8.1):",
                                        value=v_salvo_81,
                                        key=chave_texto_81,
                                        on_change=cb_processa_e_salva_81,
                                        placeholder="Ex: Lei Municipal nº 4.321, de 15 de Outubro de 2021",
                                        height=110
                                )

                        with col2:
                                st.write("*Links ativos extraídos do texto:*")
                                placeholder_links_81 = st.empty()
                                links_81_visuais = re.findall(r'(https?://[^\s]+)', texto_81 or "")
                                if links_81_visuais:
                                        placeholder_links_81.markdown(" | ".join([f"🔗 [{u}]({u})" for u in links_81_visuais]))
                                else:
                                        placeholder_links_81.caption("Nenhum link detectado no corpo do texto.")

                        st.markdown("<span style='color:#6c757d; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 8.1: +0.0 pontos (Informativo)</span>", unsafe_allow_html=True)
                        bloco_comentarios("8.1", res_data, ano_sel)


        # =============================================================================
        # QUESITO 8.2 • ENDEREÇO ELETRÔNICO DO PLANO
        # =============================================================================
        with st.container(key=f"container_bloco_residuos_8_2_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 8.2 - Transparência Ativa e Disponibilização Digital", expanded=True):
                        st.subheader("8.2 • Página Eletrônica do Plano")
                        st.write("**Informe a página eletrônica (link na internet) do instrumento normativo do Plano Municipal ou Regional de Gestão Integrada de Resíduos Sólidos:**")
                        st.caption("ℹ *Se não estiver disponível na internet, insira no campo de resposta o texto **XYZ**.*")

                        d82 = res_data.get("8.2", {"valor": "XYZ", "pontos": 0.0, "link": ""})
                        if d82 is None: d82 = {"valor": "XYZ", "pontos": 0.0, "link": ""}

                        v_salvo_82 = d82.get("valor", "XYZ")
                        evidencia_82_salva = d82.get("link", "")

                        chave_input_82 = f"q82_txt_input_{ano_sel}"
                        chave_link_82 = f"l_82_txt_area_{ano_sel}"

                        def cb_processa_e_salva_82():
                                val_input = st.session_state.get(chave_input_82, v_salvo_82).strip()
                                lnk_val = st.session_state.get(chave_link_82, evidencia_82_salva).strip()
                                
                                if val_input.upper() == "XYZ" or val_input == "":
                                        pts_calculados = 0.0
                                else:
                                        pts_calculados = 2.0
                                        
                                save_resp("8.2", val_input, float(pts_calculados), lnk_val)
                                res_data["8.2"] = {"valor": val_input, "pontos": float(pts_calculados), "link": lnk_val}

                                links_atuais_val = re.findall(r'(https?://[^\s]+)', val_input or "")
                                links_atuais_lnk = re.findall(r'(https?://[^\s]+)', lnk_val or "")
                                todos_atuais = links_atuais_val + links_atuais_lnk

                                links_antigos_val = re.findall(r'(https?://[^\s]+)', v_salvo_82 or "")
                                links_antigos_lnk = re.findall(r'(https?://[^\s]+)', evidencia_82_salva or "")
                                todos_antigos = links_antigos_val + links_antigos_lnk

                                if (val_input != v_salvo_82 or lnk_val != evidencia_82_salva) and todos_atuais and todos_atuais != todos_antigos:
                                        st.session_state[f"links_pendentes_8_2_{ano_sel}"] = todos_atuais
                                        st.session_state[f"gatilho_modal_8_2_{ano_sel}"] = True

                        col1, col2 = st.columns([1, 1])
                        with col1:
                                val82 = st.text_input(
                                        "Endereço eletrônico (Link) ou XYZ:",
                                        value=v_salvo_82,
                                        key=chave_input_82,
                                        on_change=cb_processa_e_salva_82
                                )
                                
                                cur_val_82 = st.session_state.get(chave_input_82, v_salvo_82)
                                fb_pts_82 = 0.0 if cur_val_82.strip().upper() == "XYZ" or cur_val_82.strip() == "" else 2.0
                                st.metric(label="Pontuação do Quesito", value=f"{fb_pts_82:.1f} pts")

                                placeholder_links_v82 = st.empty()
                                links_v82_visuais = re.findall(r'(https?://[^\s]+)', cur_val_82 or "")
                                if links_v82_visuais:
                                        placeholder_links_v82.markdown(f"**🔗 Link do Plano:** " + " | ".join([f"[{u}]({u})" for u in links_v82_visuais]))

                        with col2:
                                link_82 = st.text_area(
                                        "Link/Evidência Adicional (8.2):",
                                        value=evidencia_82_salva,
                                        key=chave_link_82,
                                        on_change=cb_processa_e_salva_82,
                                        placeholder="Links complementares como portais da transparência ou repositórios municipais...",
                                        height=130
                                )
                                placeholder_links_82 = st.empty()
                                links_82_visuais = re.findall(r'(https?://[^\s]+)', link_82 or "")
                                if links_82_visuais:
                                        placeholder_links_82.markdown(f"**🔗 Link complementar:** " + " | ".join([f"[{u}]({u})" for u in links_82_visuais]))

                        cor_txt_82 = "#28a745" if fb_pts_82 > 0 else "#dc3545"
                        st.markdown(f"<span style='color:{cor_txt_82}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 8.2: +{fb_pts_82:.1f} pontos</span>", unsafe_allow_html=True)
                        bloco_comentarios("8.2", res_data, ano_sel)


        # =============================================================================
        # QUESITO 8.3 • CARACTERIZAÇÃO DOS RESÍDUOS SÓLIDOS URBANOS
        # =============================================================================
        with st.container(key=f"container_bloco_residuos_8_3_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 8.3 - Gravimetria, Qualificação e Quantificação de RSU", expanded=True):
                        st.subheader("8.3 • Caracterização Qualitativa e Quantitativa")
                        st.write("**A Prefeitura realizou a caracterização qualitativa e quantitativa dos resíduos sólidos urbanos gerados no município, identificando ainda sua origem?**")

                        opc83 = ["Selecione...", "Sim – 10", "Não – 00"]
                        d83 = res_data.get("8.3", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        if d83 is None: d83 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                        v_salvo_83 = d83.get("valor", "Selecione...")
                        if v_salvo_83 not in opc83: v_salvo_83 = "Selecione..."

                        evidencia_83_salva = d83.get("link", "")
                        chave_radio_83 = f"r_83_select_{ano_sel}"
                        chave_link_83 = f"l_83_txt_area_{ano_sel}"

                        def cb_processa_e_salva_83():
                                lnk_val = st.session_state.get(chave_link_83, evidencia_83_salva).strip()
                                val_salvar = st.session_state.get(chave_radio_83, v_salvo_83)
                                
                                pts_calculados = 10.0 if "Sim" in val_salvar else 0.0
                                save_resp("8.3", val_salvar, float(pts_calculados), lnk_val)
                                res_data["8.3"] = {"valor": val_salvar, "pontos": float(pts_calculados), "link": lnk_val}

                                links_atuais = re.findall(r'(https?://[^\s]+)', lnk_val or "")
                                links_antigos = re.findall(r'(https?://[^\s]+)', evidencia_83_salva or "")
                                if lnk_val != evidencia_83_salva and links_atuais and links_atuais != links_antigos:
                                        st.session_state[f"links_pendentes_8_3_{ano_sel}"] = links_atuais
                                        st.session_state[f"gatilho_modal_8_3_{ano_sel}"] = True

                        col1, col2 = st.columns([1, 1])
                        with col1:
                                idx83 = opc83.index(v_salvo_83)
                                st.radio(
                                        "Selecione uma opção (8.3):",
                                        options=opc83,
                                        index=idx83,
                                        key=chave_radio_83,
                                        on_change=cb_processa_e_salva_83
                                )

                        with col2:
                                link_83 = st.text_area(
                                        "Link/Evidência (8.3):",
                                        value=evidencia_83_salva,
                                        key=chave_link_83,
                                        on_change=cb_processa_e_salva_83,
                                        placeholder="Estudos gravimétricos oficiais, laudos técnicos ou relatórios anexos ao PMGIRS...",
                                        height=110
                                )
                                placeholder_links_83 = st.empty()
                                links_83_visuais = re.findall(r'(https?://[^\s]+)', link_83 or "")
                                if links_83_visuais:
                                        placeholder_links_83.markdown(f"**🔗 Link ativo:** " + " | ".join([f"[{u}]({u})" for u in links_83_visuais]))

                        v_atual_83 = st.session_state.get(chave_radio_83, v_salvo_83)
                        pts_atuais_83 = 10.0 if "Sim" in v_atual_83 else 0.0
                        cor_txt_83 = "#28a745" if pts_atuais_83 > 0 else ("#6c757d" if v_atual_83 == "Selecione..." else "#dc3545")
                        st.markdown(f"<span style='color:{cor_txt_83}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 8.3: +{pts_atuais_83:.1f} pontos</span>", unsafe_allow_html=True)
                        bloco_comentarios("8.3", res_data, ano_sel)

     


        # =============================================================================
        # QUESITO 8.3.1 • INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q8_3_1_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 8.3.1 - Métodos de Caracterização", expanded=True):
                        st.subheader("8.3.1 • Métodos de Caracterização")
                        st.write("**Assinale la forma utilizada para caracterizar os resíduos sólidos do município:**")

                        d831 = res_data.get("8.3.1", {"valor": "", "pontos": 0.0, "link": ""}) or {"valor": "", "pontos": 0.0, "link": ""}
                        texto_seguro_831 = str(d831.get("valor", "")) if d831.get("valor") not in ["", "[]"] else ""
                        evidencia_831_salva = d831.get("link", "")
                        opts831 = ["Estimativa com base em dados secundários", "Realização de estudo gravimétrico, por amostragem", "Pesquisa de dados primários com medição direta", "Outros"]

                        def cb_831():
                                lnk = st.session_state.get(f"l831_in_{ano_sel}", evidencia_831_salva).strip()
                                marcados = [opt for opt in opts831 if st.session_state.get(f"c831_{opt}_{ano_sel}", False)]
                                val = str(marcados)
                                
                                save_resp("8.3.1", val, 0.0, lnk)
                                res_data["8.3.1"] = {"valor": val, "pontos": 0.0, "link": lnk}
                                
                                lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                                if lnk != evidencia_831_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_831_salva or ""):
                                        st.session_state[f"links_pendentes_8_3_1_{ano_sel}"] = lk_at
                                        st.session_state[f"gatilho_modal_8_3_1_{ano_sel}"] = True

                        c1, c2 = st.columns([1, 1])
                        with c1:
                                for opt in opts831:
                                        st.checkbox(opt, value=(opt in texto_seguro_831), key=f"c831_{opt}_{ano_sel}", on_change=cb_831)
                        with c2:
                                lk831 = st.text_area("Link/Evidência (8.3.1):", value=evidencia_831_salva, key=f"l831_in_{ano_sel}", on_change=cb_831, height=120)
                                if lk831: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk831 or "")]))

                        st.markdown("<span style='color:#6c757d; font-weight:bold;'>📊 Impacto 8.3.1: +0.0 pts (Referencial)</span>", unsafe_allow_html=True)
                        bloco_comentarios("8.3.1_b8", res_data, ano_sel)


        # =============================================================================
        # QUESITO 8.4 • INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q8_4_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 8.4 - Cronograma de Metas", expanded=True):
                        st.subheader("8.4 • Cronograma de Metas")
                        st.write("**Possui cronograma com as metas a serem cumpridas de resíduos sólidos?**")

                        d84 = res_data.get("8.4", {"valor": "Selecione...", "pontos": 0.0, "link": ""}) or {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                        opc84 = ["Selecione...", "Sim – 20", "Não – 00"]
                        v_salvo_84 = d84.get("valor", "Selecione...")
                        if v_salvo_84 not in opc84: v_salvo_84 = "Selecione..."
                        evidencia_84_salva = d84.get("link", "")

                        def cb_84():
                                lnk = st.session_state.get(f"l84_in_{ano_sel}", evidencia_84_salva).strip()
                                val = st.session_state.get(f"r84_in_{ano_sel}", v_salvo_84)
                                pts = 20.0 if "Sim" in val else 0.0
                                
                                save_resp("8.4", val, float(pts), lnk)
                                res_data["8.4"] = {"valor": val, "pontos": float(pts), "link": lnk}
                                
                                lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                                if lnk != evidencia_84_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_84_salva or ""):
                                        st.session_state[f"links_pendentes_8_4_{ano_sel}"] = lk_at
                                        st.session_state[f"gatilho_modal_8_4_{ano_sel}"] = True

                        c1, c2 = st.columns([1, 1])
                        with c1:
                                st.radio("Selecione uma opção (8.4):", options=opc84, index=opc84.index(v_salvo_84), key=f"r84_in_{ano_sel}", on_change=cb_84)
                        with c2:
                                lk84 = st.text_area("Link/Evidência (8.4):", value=evidencia_84_salva, key=f"l84_in_{ano_sel}", on_change=cb_84, height=100)
                                if lk84: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk84 or "")]))

                        v_f84 = st.session_state.get(f"r84_in_{ano_sel}", v_salvo_84)
                        pts_f84 = 20.0 if "Sim" in v_f84 else 0.0
                        st.markdown(f"<span style='color:{'#28a745' if pts_f84 > 0 else '#dc3545'}; font-weight:bold;'>📊 Impacto 8.4: +{pts_f84:.1f} pontos</span>", unsafe_allow_html=True)
                        bloco_comentarios("8.4_b8", res_data, ano_sel)


        # =============================================================================
        # SUBQUESITO 8.4.1 • INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q8_4_1_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 8.4.1 - Metas Estabelecidas", expanded=True):
                        st.subheader("8.4.1 • Metas Estabelecidas")
                        st.write("**Assinale quais as metas estabelecidas sobre resíduos sólidos:**")

                        d841 = res_data.get("8.4.1", {"valor": "", "pontos": 0.0, "link": ""}) or {"valor": "", "pontos": 0.0, "link": ""}
                        texto_seguro_841 = str(d841.get("valor", "")) if d841.get("valor") not in ["", "[]"] else ""
                        evidencia_841_salva = d841.get("link", "")
                        
                        opts841 = {
                                "Metas de redução da geração de resíduos sólidos na fonte – 2,5": 2.5, 
                                "Metas de coleta seletiva – 02": 2.0, 
                                "Metas de redução de resíduos sólidos secos dispostos in aterros – 2,5": 2.5, 
                                "Metas de redução de resíduos sólidos úmidos dispostos in aterros – 2,5": 2.5, 
                                "Outro – 0,5": 0.5
                        }

                        def cb_841():
                                lnk = st.session_state.get(f"l841_in_{ano_sel}", evidencia_841_salva).strip()
                                marcados = [txt for txt in opts841.keys() if st.session_state.get(f"c841_{txt}_{ano_sel}", False)]
                                val = str(marcados)
                                pts = sum(opts841[txt] for txt in marcados)
                                
                                save_resp("8.4.1", val, float(pts), lnk)
                                res_data["8.4.1"] = {"valor": val, "pontos": float(pts), "link": lnk}
                                
                                lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                                if lnk != evidencia_841_salva& lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_841_salva or ""):
                                        st.session_state[f"links_pendentes_8_4_1_{ano_sel}"] = lk_at
                                        st.session_state[f"gatilho_modal_8_4_1_{ano_sel}"] = True

                        c1, c2 = st.columns([1, 1])
                        with c1:
                                for txt in opts841.keys():
                                        st.checkbox(txt, value=(txt in texto_seguro_841), key=f"c841_{txt}_{ano_sel}", on_change=cb_841)
                        with c2:
                                lk841 = st.text_area("Link/Evidência (8.4.1):", value=evidencia_841_salva, key=f"l841_in_{ano_sel}", on_change=cb_841, height=150)
                                if lk841: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk841 or "")]))

                        marcados_f841 = [txt for txt in opts841.keys() if st.session_state.get(f"c841_{txt}_{ano_sel}", (txt in texto_seguro_841))]
                        pts_f841 = sum(opts841[txt] for txt in marcados_f841)
                        st.markdown(f"<span style='color:{'#28a745' if pts_f841 > 0 else '#dc3545'}; font-weight:bold;'>📊 Impacto 8.4.1: +{pts_f841:.1f} pontos</span>", unsafe_allow_html=True)
                        bloco_comentarios("8.4.1_b8", res_data, ano_sel)


        # =============================================================================
        # QUESITO 8.4.2 • INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q8_4_2_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 8.4.2 - Monitoramento e Avaliação", expanded=True):
                        st.subheader("8.4.2 • Monitoramento e Avaliação")
                        st.write("**8.4.2 Realiza monitoramento e avaliação das ações e metas de resíduos sólidos?**")

                        d842 = res_data.get("8.4.2", {"valor": "Selecione...", "pontos": 0.0, "link": ""}) or {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                        opc842 = ["Selecione...", "Sim – 30", "Não – 00"]
                        v_salvo_842 = d842.get("valor", "Selecione...")
                        if v_salvo_842 not in opc842: v_salvo_842 = "Selecione..."
                        evidencia_842_salva = d842.get("link", "")

                        def cb_842():
                                lnk = st.session_state.get(f"l842_in_{ano_sel}", evidencia_842_salva).strip()
                                val = st.session_state.get(f"r842_in_{ano_sel}", v_salvo_842)
                                pts = 30.0 if "Sim" in val else 0.0
                                
                                save_resp("8.4.2", val, float(pts), lnk)
                                res_data["8.4.2"] = {"valor": val, "pontos": float(pts), "link": lnk}
                                
                                lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                                if lnk != evidencia_842_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_842_salva or ""):
                                        st.session_state[f"links_pendentes_8_4_2_{ano_sel}"] = lk_at
                                        st.session_state[f"gatilho_modal_8_4_2_{ano_sel}"] = True

                        c1, c2 = st.columns([1, 1])
                        with c1:
                                st.radio("Selecione uma opção (8.4.2):", options=opc842, index=opc842.index(v_salvo_842), key=f"r842_in_{ano_sel}", on_change=cb_842)
                        with c2:
                                lk842 = st.text_area("Link/Evidência (8.4.2):", value=evidencia_842_salva, key=f"l842_in_{ano_sel}", on_change=cb_842, height=100)
                                if lk842: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk842 or "")]))

                        v_f842 = st.session_state.get(f"r842_in_{ano_sel}", v_salvo_842)
                        pts_f842 = 30.0 if "Sim" in v_f842 else 0.0
                        st.markdown(f"<span style='color:{'#28a745' if pts_f842 > 0 else '#dc3545'}; font-weight:bold;'>📊 Impacto 8.4.2: +{pts_f842:.1f} pontos</span>", unsafe_allow_html=True)
                        bloco_comentarios("8.4.2_b8", res_data, ano_sel)


        # =============================================================================
        # QUESITO 8.4.2.1 • INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q8_4_2_1_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 8.4.2.1 - Formas de Monitoramento", expanded=True):
                        st.subheader("8.4.2.1 • Formas de Monitoramento")
                        st.write("**De que forma é realizado o monitoramento e avaliação das ações e metas de resíduos sólidos?**")

                        d8421 = res_data.get("8.4.2.1", {"valor": "", "pontos": 0.0, "link": ""}) or {"valor": "", "pontos": 0.0, "link": ""}
                        texto_seguro_8421 = str(d8421.get("valor", "")) if d8421.get("valor") not in ["", "[]"] else ""
                        evidencia_8421_salva = d8421.get("link", "")
                        opts8421 = ["Relatórios anuais discutidos e/ou publicados", "Indicadores de eficácia e eficiência", "Avaliação de recursos aplicados", "Outros"]

                        def cb_8421():
                                lnk = st.session_state.get(f"l8421_in_{ano_sel}", evidencia_8421_salva).strip()
                                marcados = [opt for opt in opts8421 if st.session_state.get(f"c8421_{opt}_{ano_sel}", False)]
                                val = str(marcados)
                                
                                save_resp("8.4.2.1", val, 0.0, lnk)
                                res_data["8.4.2.1"] = {"valor": val, "pontos": 0.0, "link": lnk}
                                
                                lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                                if lnk != evidencia_8421_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_8421_salva or ""):
                                        st.session_state[f"links_pendentes_8_4_2_1_{ano_sel}"] = lk_at
                                        st.session_state[f"gatilho_modal_8_4_2_1_{ano_sel}"] = True

                        c1, c2 = st.columns([1, 1])
                        with c1:
                                for opt in opts8421:
                                        st.checkbox(opt, value=(opt in texto_seguro_8421), key=f"c8421_{opt}_{ano_sel}", on_change=cb_8421)
                        with c2:
                                lk8421 = st.text_area("Link/Evidência (8.4.2.1):", value=evidencia_8421_salva, key=f"l8421_in_{ano_sel}", on_change=cb_8421, height=120)
                                if lk8421: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk8421 or "")]))

                        st.markdown("<span style='color:#6c757d; font-weight:bold;'>📊 Impacto 8.4.2.1: +0.0 pts (Referencial)</span>", unsafe_allow_html=True)
                        bloco_comentarios("8.4.2.1_b8", res_data, ano_sel)


        # =============================================================================
        # QUESITO 8.4.3 • INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q8_4_3_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 8.4.3 - Cumprimento de Metas", expanded=True):
                        st.subheader("8.4.3 • Cumprimento de Metas")
                        st.write("**As metas do Plano Municipal ou Regional de Gestão Integrada de Resíduos Sólidos estão sendo cumpridas no prazo estipulado?**")

                        d843 = res_data.get("8.4.3", {"valor": "Selecione...", "pontos": 0.0, "link": ""}) or {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                        opc843 = ["Selecione...", "Todas as metas foram cumpridas dentro do prazo – 50", "A maior parte das metas foram cumpridas dentro do prazo – 30", "A menor parte das metas foram cumpridas dentro do prazo – 10", "As metas não foram cumpridas dentro do prazo – 00"]
                        v_salvo_843 = d843.get("valor", "Selecione...")
                        if v_salvo_843 not in opc843: v_salvo_843 = "Selecione..."
                        evidencia_843_salva = d843.get("link", "")

                        def cb_843():
                                lnk = st.session_state.get(f"l843_in_{ano_sel}", evidencia_843_salva).strip()
                                val = st.session_state.get(f"r843_in_{ano_sel}", v_salvo_843)
                                
                                pts = 0.0
                                if "Todas" in val: pts = 50.0
                                elif "maior parte" in val: pts = 30.0
                                elif "menor parte" in val: pts = 10.0
                                
                                save_resp("8.4.3", val, float(pts), lnk)
                                res_data["8.4.3"] = {"valor": val, "pontos": float(pts), "link": lnk}
                                
                                lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                                if lnk != evidencia_843_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_843_salva or ""):
                                        st.session_state[f"links_pendentes_8_4_3_{ano_sel}"] = lk_at
                                        st.session_state[f"gatilho_modal_8_4_3_{ano_sel}"] = True

                        c1, c2 = st.columns([1, 1])
                        with c1:
                                st.radio("Selecione uma opção (8.4.3):", options=opc843, index=opc843.index(v_salvo_843), key=f"r843_in_{ano_sel}", on_change=cb_843)
                        with c2:
                                lk843 = st.text_area("Link/Evidência (8.4.3):", value=evidencia_843_salva, key=f"l843_in_{ano_sel}", on_change=cb_843, height=120)
                                if lk843: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk843 or "")]))

                        v_f843 = st.session_state.get(f"r843_in_{ano_sel}", v_salvo_843)
                        pts_f843 = 0.0
                        if "Todas" in v_f843: pts_f843 = 50.0
                        elif "maior parte" in v_f843: pts_f843 = 30.0
                        elif "menor parte" in v_f843: pts_f843 = 10.0
                                                
                        st.markdown(f"<span style='color:{'#28a745' if pts_f843 > 0 else '#dc3545'}; font-weight:bold;'>📊 Impacto 8.4.3: +{pts_f843:.1f} pontos</span>", unsafe_allow_html=True)
                        bloco_comentarios("8.4.3_b8", res_data, ano_sel)


        # =============================================================================
        # QUESITO 8.4.3.1 • INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q8_4_3_1_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 8.4.3.1 - Motivos do Não Cumprimento", expanded=True):
                        st.subheader("8.4.3.1 • Motivos do Não Cumprimento")
                        st.write("**Assinale os motivos pelos quais as metas do Plano Municipal ou Regional de Gestão Integrada de Resíduos Sólidos não estão sendo cumpridas:**")

                        d8431 = res_data.get("8.4.3.1", {"valor": "", "pontos": 0.0, "link": ""}) or {"valor": "", "pontos": 0.0, "link": ""}
                        texto_seguro_8431 = str(d8431.get("valor", "")) if d8431.get("valor") not in ["", "[]"] else ""
                        evidencia_8431_salva = d8431.get("link", "")
                        opts8431 = ["Falta de recursos orçamentários", "Falta de aprovação legislativa", "Atraso na licitação", "Não realizou licitação necessária", "Falta de pessoal qualificado", "Falta de consenso no consórcio intermunicipal", "Outros"]

                        def cb_8431():
                                lnk = st.session_state.get(f"l8431_in_{ano_sel}", evidencia_8431_salva).strip()
                                marcados = [opt for opt in opts8431 if st.session_state.get(f"c8431_{opt}_{ano_sel}", False)]
                                val = str(marcados)
                                
                                save_resp("8.4.3.1", val, 0.0, lnk)
                                res_data["8.4.3.1"] = {"valor": val, "pontos": 0.0, "link": lnk}
                                
                                lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                                if lnk != evidencia_8431_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_8431_salva or ""):
                                        st.session_state[f"links_pendentes_8_4_3_1_{ano_sel}"] = lk_at
                                        st.session_state[f"gatilho_modal_8_4_3_1_{ano_sel}"] = True

                        c1, c2 = st.columns([1, 1])
                        with c1:
                                for opt in opts8431:
                                        st.checkbox(opt, value=(opt in texto_seguro_8431), key=f"c8431_{opt}_{ano_sel}", on_change=cb_8431)
                        with c2:
                                lk8431 = st.text_area("Link/Evidência (8.4.3.1):", value=evidencia_8431_salva, key=f"l8431_in_{ano_sel}", on_change=cb_8431, height=120)
                                if lk8431: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk8431 or "")]))

                        st.markdown("<span style='color:#6c757d; font-weight:bold;'>📊 Impacto 8.4.3.1: +0.0 pts (Referencial)</span>", unsafe_allow_html=True)
                        bloco_comentarios("8.4.3.1_b8", res_data, ano_sel)

      # =============================================================================
        # QUESITO 8.4.4 • INDEPENDENTE (DATA DA ÚLTIMA REVISÃO)
        # =============================================================================
        with st.container(key=f"bloco_isolado_q8_4_4_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 8.4.4 - Data da Última Revisão do Plano", expanded=True):
                        st.subheader("8.4.4 • Data da Última Revisão do Plano")
                        st.write("**Qual a data da última revisão do Plano Municipal ou Regional de Gestão Integrada de Resíduos Sólidos?**")
                        st.caption("ℹ *Se não houve revisão do plano de gestão integrada de resíduos sólidos, informe a data do início de vigência do plano.*")

                        d844 = res_data.get("8.4.4", {"valor": "01/01/2015", "pontos": 0.0, "link": ""}) or {"valor": "01/01/2015", "pontos": 0.0, "link": ""}
                        v_salvo_844 = d844.get("valor", "01/01/2015")
                        evidencia_844_salva = d844.get("link", "")

                        try:
                                dia_salvo, mes_salvo, ano_salvo = map(int, v_salvo_844.split("/"))
                        except Exception:
                                dia_salvo, mes_salvo, ano_salvo = 1, 1, 2015

                        chk_d = f"q844_d_in_{ano_sel}"
                        chk_m = f"q844_m_in_{ano_sel}"
                        chk_a = f"q844_a_in_{ano_sel}"
                        chk_l = f"l844_txt_in_{ano_sel}"

                        def cb_844():
                                d_atual = int(st.session_state.get(chk_d, dia_salvo))
                                m_atual = int(st.session_state.get(chk_m, mes_salvo))
                                a_atual = int(st.session_state.get(chk_a, ano_salvo))
                                lnk_val = st.session_state.get(chk_l, evidencia_844_salva).strip()

                                if a_atual < 2014 or (a_atual == 2014 and m_atual < 12) or (a_atual == 2014 and m_atual == 12 and d_atual <= 31):
                                        pts_calculados = -30.0
                                else:
                                        pts_calculados = 0.0

                                data_formatada = f"{d_atual:02d}/{m_atual:02d}/{a_atual}"
                                save_resp("8.4.4", data_formatada, float(pts_calculados), lnk_val)
                                res_data["8.4.4"] = {"valor": data_formatada, "pontos": float(pts_calculados), "link": lnk_val}

                                links_atuais = re.findall(r'(https?://[^\s]+)', lnk_val or "")
                                links_antigos = re.findall(r'(https?://[^\s]+)', evidencia_844_salva or "")
                                if lnk_val != evidencia_844_salva and links_atuais and links_atuais != links_antigos:
                                        st.session_state[f"links_pendentes_8_4_4_{ano_sel}"] = links_atuais
                                        st.session_state[f"gatilho_modal_8_4_4_{ano_sel}"] = True

                        col1, col2 = st.columns([1, 1])
                        with col1:
                                c_dia, c_mes, c_ano = st.columns(3)
                                with c_dia:
                                        d_v = st.number_input("Dia", min_value=1, max_value=31, value=dia_salvo, key=chk_d, on_change=cb_844)
                                with c_mes:
                                        m_v = st.number_input("Mês", min_value=1, max_value=12, value=mes_salvo, key=chk_m, on_change=cb_844)
                                with c_ano:
                                        a_v = st.number_input("Ano", min_value=1900, max_value=2100, value=ano_salvo, key=chk_a, on_change=cb_844)

                                if a_v < 2014 or (a_v == 2014 and m_v < 12) or (a_v == 2014 and m_v == 12 and d_v <= 31):
                                        pts_display = -30.0
                                        cor_metric = "#dc3545"
                                else:
                                        pts_display = 0.0
                                        cor_metric = "#6c757d"

                                st.metric(label="Impacto na Pontuação", value=f"{pts_display:.1f} pts")

                        with col2:
                                lk844 = st.text_area("Link/Evidência (8.4.4):", value=evidencia_844_salva, key=chk_l, on_change=cb_844, height=110)
                                if lk844:
                                        st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk844 or "")]))

                        st.markdown(f"<span style='color:{cor_metric}; font-weight:bold;'>📊 Impacto Técnico 8.4.4: {pts_display:.1f} pontos aplicados</span>", unsafe_allow_html=True)
                        bloco_comentarios("8.4.4_b8", res_data, ano_sel)

        # =============================================================================
        # GATILHOS DOS MODAIS AUTOMÁTICOS • GRUPO 9 (INDIVIDUAIS)
        # =============================================================================
        if st.session_state.get(f"gatilho_modal_9_0_{ano_sel}", False):
                modal_aviso_link("9.0", st.session_state.get(f"links_pendentes_9_0_{ano_sel}", []))
                st.session_state[f"gatilho_modal_9_0_{ano_sel}"] = False

        if st.session_state.get(f"gatilho_modal_9_1_{ano_sel}", False):
                modal_aviso_link("9.1", st.session_state.get(f"links_pendentes_9_1_{ano_sel}", []))
                st.session_state[f"gatilho_modal_9_1_{ano_sel}"] = False

        if st.session_state.get(f"gatilho_modal_9_2_{ano_sel}", False):
                modal_aviso_link("9.2", st.session_state.get(f"links_pendentes_9_2_{ano_sel}", []))
                st.session_state[f"gatilho_modal_9_2_{ano_sel}"] = False

        if st.session_state.get(f"gatilho_modal_9_3_{ano_sel}", False):
                modal_aviso_link("9.3", st.session_state.get(f"links_pendentes_9_3_{ano_sel}", []))
                st.session_state[f"gatilho_modal_9_3_{ano_sel}"] = False

        if st.session_state.get(f"gatilho_modal_9_3_1_{ano_sel}", False):
                modal_aviso_link("9.3.1", st.session_state.get(f"links_pendentes_9_3_1_{ano_sel}", []))
                st.session_state[f"gatilho_modal_9_3_1_{ano_sel}"] = False

# =============================================================================
        # QUESITO 9.0 • INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q9_0_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 9.0 - Coleta Seletiva", expanded=True):
                        st.subheader("9.0 • Coleta Seletiva")
                        st.write("**A prefeitura municipal realiza a coleta seletiva de resíduos sólidos?**")

                        d90 = res_data.get("9.0", {"valor": "Selecione...", "link": ""}) or {"valor": "Selecione...", "link": ""}
                        opc90 = ["Selecione...", "Sim", "Não"]
                        v_salvo_90 = d90.get("valor", "Selecione...")
                        if v_salvo_90 not in opc90: v_salvo_90 = "Selecione..."
                        evidencia_90_salva = d90.get("link", "")

                        def cb_90():
                                lnk = st.session_state.get(f"l90_in_{ano_sel}", evidencia_90_salva).strip()
                                val = st.session_state.get(f"r90_in_{ano_sel}", v_salvo_90)
                                save_resp("9.0", val, 0.0, lnk)
                                res_data["9.0"] = {"valor": val, "pontos": 0.0, "link": lnk}
                                
                                lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                                if lnk != evidencia_90_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_90_salva or ""):
                                        st.session_state[f"links_pendentes_9_0_{ano_sel}"] = lk_at
                                        st.session_state[f"gatilho_modal_9_0_{ano_sel}"] = True

                        c1, c2 = st.columns([1, 1])
                        with c1:
                                st.radio("Selecione uma opção (9.0):", options=opc90, index=opc90.index(v_salvo_90), key=f"r90_in_{ano_sel}", on_change=cb_90)
                        with c2:
                                lk90 = st.text_area("Link/Evidência (9.0):", value=evidencia_90_salva, key=f"l90_in_{ano_sel}", on_change=cb_90, height=100)
                                if lk90: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk90 or "")]))

                        st.markdown("<span style='color:#6c757d; font-weight:bold;'>📊 Impacto 9.0: +0.0 pts (Referencial)</span>", unsafe_allow_html=True)
                        bloco_comentarios("9.0_b9", res_data, ano_sel)


        # =============================================================================
        # QUESITO 9.1 • INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q9_1_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 9.1 - Programação da Coleta", expanded=True):
                        st.subheader("9.1 • Programação da Coleta")
                        st.write("**9.1 A coleta seletiva ocorre de forma programada (determinados os horários e dias da semana)?**")

                        d91 = res_data.get("9.1", {"valor": "Selecione...", "link": ""}) or {"valor": "Selecione...", "link": ""}
                        opc91 = ["Selecione...", "Sim – 00", "Não – -30 (perde 30 pontos)"]
                        v_salvo_91 = d91.get("valor", "Selecione...")
                        if v_salvo_91 not in opc91: v_salvo_91 = "Selecione..."
                        evidencia_91_salva = d91.get("link", "")

                        def cb_91():
                                lnk = st.session_state.get(f"l91_in_{ano_sel}", evidencia_91_salva).strip()
                                val = st.session_state.get(f"r91_in_{ano_sel}", v_salvo_91)
                                pts = 0.0 if "Sim" in val else (-30.0 if "Não" in val else 0.0)
                                save_resp("9.1", val, float(pts), lnk)
                                res_data["9.1"] = {"valor": val, "pontos": float(pts), "link": lnk}
                                
                                lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                                if lnk != evidencia_91_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_91_salva or ""):
                                        st.session_state[f"links_pendentes_9_1_{ano_sel}"] = lk_at
                                        st.session_state[f"gatilho_modal_9_1_{ano_sel}"] = True

                        c1, c2 = st.columns([1, 1])
                        with c1:
                                st.radio("Selecione uma opção (9.1):", options=opc91, index=opc91.index(v_salvo_91), key=f"r91_in_{ano_sel}", on_change=cb_91)
                        with c2:
                                lk91 = st.text_area("Link/Evidência (9.1):", value=evidencia_91_salva, key=f"l91_in_{ano_sel}", on_change=cb_91, height=100)
                                if lk91: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk91 or "")]))

                        v_f91 = st.session_state.get(f"r91_in_{ano_sel}", v_salvo_91)
                        pts_exibido_91 = 0.0 if "Sim" in v_f91 else (-30.0 if "Não" in v_f91 else 0.0)
                        st.markdown(f"<span style='color:{'#28a745' if pts_exibido_91 >= 0 else '#dc3545'}; font-weight:bold;'>📊 Impacto 9.1: {pts_exibido_91:+.1f} pts</span>", unsafe_allow_html=True)
                        bloco_comentarios("9.1_b9", res_data, ano_sel)


        # =============================================================================
        # QUESITO 9.2 • INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q9_2_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 9.2 - Abrangência das Regiões", expanded=True):
                        st.subheader("9.2 • Abrangência das Regiões")
                        st.write("**9.2 Todas as regiões do município são atendidas pela coleta seletiva?**")

                        d92 = res_data.get("9.2", {"valor": "Selecione...", "link": ""}) or {"valor": "Selecione...", "link": ""}
                        opc92 = ["Selecione...", "Todos os bairros do município são atendidos – 100", "A maior parte dos bairros são atendidos – 50", "A menor parte dos bairros são atendidos – 10"]
                        v_salvo_92 = d92.get("valor", "Selecione...")
                        if v_salvo_92 not in opc92: v_salvo_92 = "Selecione..."
                        evidencia_92_salva = d92.get("link", "")

                        def cb_92():
                                lnk = st.session_state.get(f"l92_in_{ano_sel}", evidencia_92_salva).strip()
                                val = st.session_state.get(f"r92_in_{ano_sel}", v_salvo_92)
                                pts = 100.0 if "Todos" in val else (50.0 if "maior parte" in val else (10.0 if "menor parte" in val else 0.0))
                                save_resp("9.2", val, float(pts), lnk)
                                res_data["9.2"] = {"valor": val, "pontos": float(pts), "link": lnk}
                                
                                lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                                if lnk != evidencia_92_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_92_salva or ""):
                                        st.session_state[f"links_pendentes_9_2_{ano_sel}"] = lk_at
                                        st.session_state[f"gatilho_modal_9_2_{ano_sel}"] = True

                        c1, c2 = st.columns([1, 1])
                        with c1:
                                st.radio("Selecione uma opção (9.2):", options=opc92, index=opc92.index(v_salvo_92), key=f"r92_in_{ano_sel}", on_change=cb_92)
                        with c2:
                                lk92 = st.text_area("Link/Evidência (9.2):", value=evidencia_92_salva, key=f"l92_in_{ano_sel}", on_change=cb_92, height=100)
                                if lk92: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk92 or "")]))

                        v_f92 = st.session_state.get(f"r92_in_{ano_sel}", v_salvo_92)
                        pts_exibido_92 = 100.0 if "Todos" in v_f92 else (50.0 if "maior parte" in v_f92 else (10.0 if "menor parte" in v_f92 else 0.0))
                        st.markdown(f"<span style='color:{'#28a745' if pts_exibido_92 > 0 else '#dc3545'}; font-weight:bold;'>📊 Impacto 9.2: +{pts_exibido_92:.1f} pts</span>", unsafe_allow_html=True)
                        bloco_comentarios("9.2_b9", res_data, ano_sel)


        # =============================================================================
        # QUESITO 9.3 • INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q9_3_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 9.3 - Campanhas de Incentivo", expanded=True):
                        st.subheader("9.3 • Campanhas de Incentivo")
                        st.write("**9.3 A Prefeitura incentiva e orienta a população por meio de Ações e/ou Campanhas sobre a importância da coleta seletiva?**")

                        d93 = res_data.get("9.3", {"valor": "Selecione...", "link": ""}) or {"valor": "Selecione...", "link": ""}
                        opc93 = ["Selecione...", "Sim – 05", "Não – 00"]
                        v_salvo_93 = d93.get("valor", "Selecione...")
                        if v_salvo_93 not in opc93: v_salvo_93 = "Selecione..."
                        evidencia_93_salva = d93.get("link", "")

                        def cb_93():
                                lnk = st.session_state.get(f"l93_in_{ano_sel}", evidencia_93_salva).strip()
                                val = st.session_state.get(f"r93_in_{ano_sel}", v_salvo_93)
                                pts = 5.0 if "Sim" in val else 0.0
                                save_resp("9.3", val, float(pts), lnk)
                                res_data["9.3"] = {"valor": val, "pontos": float(pts), "link": lnk}
                                
                                lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                                if lnk != evidencia_93_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_93_salva or ""):
                                        st.session_state[f"links_pendentes_9_3_{ano_sel}"] = lk_at
                                        st.session_state[f"gatilho_modal_9_3_{ano_sel}"] = True

                        c1, c2 = st.columns([1, 1])
                        with c1:
                                st.radio("Selecione uma opção (9.3):", options=opc93, index=opc93.index(v_salvo_93), key=f"r93_in_{ano_sel}", on_change=cb_93)
                        with c2:
                                lk93 = st.text_area("Link/Evidência (9.3):", value=evidencia_93_salva, key=f"l93_in_{ano_sel}", on_change=cb_93, height=100)
                                if lk93: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk93 or "")]))

                        v_f93 = st.session_state.get(f"r93_in_{ano_sel}", v_salvo_93)
                        pts_exibido_93 = 5.0 if "Sim" in v_f93 else 0.0
                        st.markdown(f"<span style='color:{'#28a745' if pts_exibido_93 > 0 else '#dc3545'}; font-weight:bold;'>📊 Impacto 9.3: +{pts_exibido_93:.1f} pts</span>", unsafe_allow_html=True)
                        bloco_comentarios("9.3_b9", res_data, ano_sel)


        # =============================================================================
        # QUESITO 9.3.1 • INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q9_3_1_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 9.3.1 - Detalhamento das Ações", expanded=True):
                        st.subheader("9.3.1 • Detalhamento das Ações")
                        st.write("**9.3.1 Assinale quais Ações e/ou Campanhas foram realizadas:**")

                        d931 = res_data.get("9.3.1", {"valor": "", "link": ""}) or {"valor": "", "link": ""}
                        texto_seguro_931 = str(d931.get("valor", "")) if d931.get("valor") not in ["", "[]"] else ""
                        evidencia_931_salva = d931.get("link", "")

                        opts931 = [
                                "Divulgações em redes sociais e/ou site da prefeitura – 01", 
                                "Ações de educação ambiental – 0,5", 
                                "Campanhas de conscientização por meio de sinalizações, folders, cartazes, propagandas e materiais impressos – 01", 
                                "Projetos de incentivo – 01", 
                                "Workshops / Palestras – 0,5", 
                                "Instalação de lixeiras seletivas e distribuição de sacolas retornáveis para separação dos resíduos recicláveis – 01"
                        ]

                        def cb_931():
                                lnk = st.session_state.get(f"l931_in_{ano_sel}", evidencia_931_salva).strip()
                                marcados = [opt for opt in opts931 if st.session_state.get(f"q931_in_{opt}_{ano_sel}", False)]
                                val = str(marcados)
                                
                                pts = 0.0
                                for m in marcados:
                                        pts += 0.5 if "0,5" in m else 1.0
                                        
                                save_resp("9.3.1", val, float(pts), lnk)
                                res_data["9.3.1"] = {"valor": val, "pontos": float(pts), "link": lnk}
                                
                                lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                                if lnk != evidencia_931_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_931_salva or ""):
                                        st.session_state[f"links_pendentes_9_3_1_{ano_sel}"] = lk_at
                                        st.session_state[f"gatilho_modal_9_3_1_{ano_sel}"] = True

                        c1, c2 = st.columns([1, 1])
                        with c1:
                                for txt in opts931:
                                        st.checkbox(txt, value=(txt in texto_seguro_931), key=f"q931_in_{txt}_{ano_sel}", on_change=cb_931)
                        with c2:
                                lk931 = st.text_area("Link/Evidência (9.3.1):", value=evidencia_931_salva, key=f"l931_in_{ano_sel}", on_change=cb_931, height=100)
                                if lk931: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk931 or "")]))

                        marcados_f931 = [opt for opt in opts931 if st.session_state.get(f"q931_in_{opt}_{ano_sel}", (opt in texto_seguro_931))]
                        pts_exibido_931 = 0.0
                        for m in marcados_f931:
                                pts_exibido_931 += 0.5 if "0,5" in m else 1.0

                        st.markdown(f"<span style='color:{'#28a745' if pts_exibido_931 > 0 else '#dc3545'}; font-weight:bold;'>📊 Impacto 9.3.1: +{pts_exibido_931:.1f} pts</span>", unsafe_allow_html=True)
                        bloco_comentarios("9.3.1_b9", res_data, ano_sel)

        # =============================================================================
        # GATILHOS DOS MODAIS AUTOMÁTICOS • GRUPO 10 (INDIVIDUAIS)
        # =============================================================================
        if st.session_state.get(f"gatilho_modal_10_0_{ano_sel}", False):
                modal_aviso_link("10.0", st.session_state.get(f"links_pendentes_10_0_{ano_sel}", []))
                st.session_state[f"gatilho_modal_10_0_{ano_sel}"] = False

        if st.session_state.get(f"gatilho_modal_10_1_{ano_sel}", False):
                modal_aviso_link("10.1", st.session_state.get(f"links_pendentes_10_1_{ano_sel}", []))
                st.session_state[f"gatilho_modal_10_1_{ano_sel}"] = False

        if st.session_state.get(f"gatilho_modal_10_2_{ano_sel}", False):
                modal_aviso_link("10.2", st.session_state.get(f"links_pendentes_10_2_{ano_sel}", []))
                st.session_state[f"gatilho_modal_10_2_{ano_sel}"] = False

        if st.session_state.get(f"gatilho_modal_10_3_{ano_sel}", False):
                modal_aviso_link("10.3", st.session_state.get(f"links_pendentes_10_3_{ano_sel}", []))
                st.session_state[f"gatilho_modal_10_3_{ano_sel}"] = False

        if st.session_state.get(f"gatilho_modal_10_3_1_{ano_sel}", False):
                modal_aviso_link("10.3.1", st.session_state.get(f"links_pendentes_10_3_1_{ano_sel}", []))
                st.session_state[f"gatilho_modal_10_3_1_{ano_sel}"] = False

        if st.session_state.get(f"gatilho_modal_10_3_1_1_{ano_sel}", False):
                modal_aviso_link("10.3.1.1", st.session_state.get(f"links_pendentes_10_3_1_1_{ano_sel}", []))
                st.session_state[f"gatilho_modal_10_3_1_1_{ano_sel}"] = False

       # =============================================================================
        # QUESITO 10.0 • INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q10_0_{ano_sel}", border=True):
                with st.expander("📌 Quesito 10.0 - Coleta de Lixo Doméstico", expanded=True):
                        st.subheader("10.0 • Coleta de Lixo Doméstico")
                        st.write("**É realizada a coleta de lixo doméstico (resíduos domiciliares)? Lixo doméstico (resíduos domiciliares) são os resíduos originários de atividades domésticas em residências urbanas**")
                        
                        d100 = res_data.get("10.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""}) or {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                        opc100 = ["Selecione...", "Sim – 00", "Não – -100 (perde 100 pontos)"]
                        v_salvo_100 = d100.get("valor", "Selecione...")
                        if v_salvo_100 not in opc100: v_salvo_100 = "Selecione..."
                        evidencia_100_salva = d100.get("link", "")

                        def cb_100():
                                lnk = st.session_state.get(f"l100_in_{ano_sel}", evidencia_100_salva).strip()
                                val = st.session_state.get(f"r100_in_{ano_sel}", v_salvo_100)
                                pts = 0.0 if "Sim" in val else (-100.0 if "Não" in val else 0.0)
                                save_resp("10.0", val, float(pts), lnk)
                                res_data["10.0"] = {"valor": val, "pontos": float(pts), "link": lnk}
                                
                                lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                                if lnk != evidencia_100_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_100_salva or ""):
                                        st.session_state[f"links_pendentes_10_0_{ano_sel}"] = lk_at
                                        st.session_state[f"gatilho_modal_10_0_{ano_sel}"] = True

                        col1, col2 = st.columns([1, 1])
                        with col1:
                                st.radio("Selecione uma opção (10.0):", options=opc100, index=opc100.index(v_salvo_100), key=f"r100_in_{ano_sel}", on_change=cb_100)
                        with col2:
                                lk100 = st.text_area("Link/Evidência (10.0):", value=evidencia_100_salva, key=f"l100_in_{ano_sel}", on_change=cb_100, height=100)
                                if lk100: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk100 or "")]))

                        v_f100 = st.session_state.get(f"r100_in_{ano_sel}", v_salvo_100)
                        pts_exibido_100 = 0.0 if "Sim" in v_f100 else (-100.0 if "Não" in v_f100 else 0.0)
                        st.markdown(f"<span style='color:{'#28a745' if pts_exibido_100 >= 0 else '#dc3545'}; font-weight:bold;'>📊 Impacto 10.0: {pts_exibido_100:.1f} pontos aplicados</span>", unsafe_allow_html=True)
                        bloco_comentarios("10.0_b10", res_data, ano_sel)


        # =============================================================================
        # QUESITO 10.1 • INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q10_1_{ano_sel}", border=True):
                with st.expander("📌 Quesito 10.1 - Programação da Coleta Doméstica", expanded=True):
                        st.subheader("10.1 • Programação da Coleta")
                        st.write("**A coleta de lixo doméstico (resíduos domiciliares) ocorre de forma programada (determinados os horários e dias da semana)?**")
                        
                        d101 = res_data.get("10.1", {"valor": "Selecione...", "pontos": 0.0, "link": ""}) or {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                        opc101 = ["Selecione...", "Sim – 00", "Não – -30 (perde 30 pontos)"]
                        v_salvo_101 = d101.get("valor", "Selecione...")
                        if v_salvo_101 not in opc101: v_salvo_101 = "Selecione..."
                        evidencia_101_salva = d101.get("link", "")

                        def cb_101():
                                lnk = st.session_state.get(f"l101_in_{ano_sel}", evidencia_101_salva).strip()
                                val = st.session_state.get(f"r101_in_{ano_sel}", v_salvo_101)
                                pts = 0.0 if "Sim" in val else (-30.0 if "Não" in val else 0.0)
                                save_resp("10.1", val, float(pts), lnk)
                                res_data["10.1"] = {"valor": val, "pontos": float(pts), "link": lnk}
                                
                                lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                                if lnk != evidencia_101_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_101_salva or ""):
                                        st.session_state[f"links_pendentes_10_1_{ano_sel}"] = lk_at
                                        st.session_state[f"gatilho_modal_10_1_{ano_sel}"] = True

                        col1, col2 = st.columns([1, 1])
                        with col1:
                                st.radio("Selecione uma opção (10.1):", options=opc101, index=opc101.index(v_salvo_101), key=f"r101_in_{ano_sel}", on_change=cb_101)
                        with col2:
                                lk101 = st.text_area("Link/Evidência (10.1):", value=evidencia_101_salva, key=f"l101_in_{ano_sel}", on_change=cb_101, height=100)
                                if lk101: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk101 or "")]))

                        v_f101 = st.session_state.get(f"r101_in_{ano_sel}", v_salvo_101)
                        pts_exibido_101 = 0.0 if "Sim" in v_f101 else (-30.0 if "Não" in v_f101 else 0.0)
                        st.markdown(f"<span style='color:{'#28a745' if pts_exibido_101 >= 0 else '#dc3545'}; font-weight:bold;'>📊 Impacto 10.1: {pts_exibido_101:.1f} pontos aplicados</span>", unsafe_allow_html=True)
                        bloco_comentarios("10.1_b10", res_data, ano_sel)


        # =============================================================================
        # QUESITO 10.2 • INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q10_2_{ano_sel}", border=True):
                with st.expander("📌 Quesito 10.2 - Abrangência da Coleta", expanded=True):
                        st.subheader("10.2 • Abrangência das Regiões")
                        st.write("**Todas as regiões do município são atendidas pela coleta de lixo doméstico (resíduos domiciliares)?** *Inclusive zona rural e periferia*")
                        
                        d102 = res_data.get("10.2", {"valor": "Selecione...", "pontos": 0.0, "link": ""}) or {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                        opc102 = [
                                "Selecione...",
                                "Todos os bairros do município são atendidos – 00", 
                                "A maior parte dos bairros são atendidos – -10 (perde 10 pontos)", 
                                "A menor parte dos bairros são atendidos – -30 (perde 30 pontos)"
                        ]
                        v_salvo_102 = d102.get("valor", "Selecione...")
                        if v_salvo_102 not in opc102: v_salvo_102 = "Selecione..."
                        evidencia_102_salva = d102.get("link", "")

                        def cb_102():
                                lnk = st.session_state.get(f"l102_in_{ano_sel}", evidencia_102_salva).strip()
                                val = st.session_state.get(f"r102_in_{ano_sel}", v_salvo_102)
                                pts = 0.0 if "Todos" in val else (-10.0 if "maior parte" in val else (-30.0 if "menor parte" in val else 0.0))
                                save_resp("10.2", val, float(pts), lnk)
                                res_data["10.2"] = {"valor": val, "pontos": float(pts), "link": lnk}
                                
                                lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                                if lnk != evidencia_102_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_102_salva or ""):
                                        st.session_state[f"links_pendentes_10_2_{ano_sel}"] = lk_at
                                        st.session_state[f"gatilho_modal_10_2_{ano_sel}"] = True

                        col1, col2 = st.columns([1, 1])
                        with col1:
                                st.radio("Selecione uma opção (10.2):", options=opc102, index=opc102.index(v_salvo_102), key=f"r102_in_{ano_sel}", on_change=cb_102)
                        with col2:
                                lk102 = st.text_area("Link/Evidência (10.2):", value=evidencia_102_salva, key=f"l102_in_{ano_sel}", on_change=cb_102, height=100)
                                if lk102: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk102 or "")]))

                        v_f102 = st.session_state.get(f"r102_in_{ano_sel}", v_salvo_102)
                        pts_exibido_102 = 0.0 if "Todos" in v_f102 else (-10.0 if "maior parte" in v_f102 else (-30.0 if "menor parte" in v_f102 else 0.0))
                        st.markdown(f"<span style='color:{'#28a745' if pts_exibido_102 >= 0 else '#dc3545'}; font-weight:bold;'>📊 Impacto 10.2: {pts_exibido_102:.1f} pontos aplicados</span>", unsafe_allow_html=True)
                        bloco_comentarios("10.2_b10", res_data, ano_sel)


        # =============================================================================
        # QUESITO 10.3 • INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q10_3_{ano_sel}", border=True):
                with st.expander("📌 Quesito 10.3 - Área de Transbordo e Triagem (ATT)", expanded=True):
                        st.subheader("10.3 • Área de Transbordo e Triagem (ATT)")
                        st.write("**Existe Área de Transbordo e Triagem (ATT) para os Resíduos Sólidos Urbanos no município?**")
                        
                        d103 = res_data.get("10.3", {"valor": "Selecione...", "pontos": 0.0, "link": ""}) or {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                        opc103 = ["Selecione...", "Sim", "Não"]
                        v_salvo_103 = d103.get("valor", "Selecione...")
                        if v_salvo_103 not in opc103: v_salvo_103 = "Selecione..."
                        evidencia_103_salva = d103.get("link", "")

                        def cb_103():
                                lnk = st.session_state.get(f"l103_in_{ano_sel}", evidencia_103_salva).strip()
                                val = st.session_state.get(f"r103_in_{ano_sel}", v_salvo_103)
                                save_resp("10.3", val, 0.0, lnk)
                                res_data["10.3"] = {"valor": val, "pontos": 0.0, "link": lnk}
                                
                                lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                                if lnk != evidencia_103_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_103_salva or ""):
                                        st.session_state[f"links_pendentes_10_3_{ano_sel}"] = lk_at
                                        st.session_state[f"gatilho_modal_10_3_{ano_sel}"] = True

                        col1, col2 = st.columns([1, 1])
                        with col1:
                                st.radio("Selecione uma opção (10.3):", options=opc103, index=opc103.index(v_salvo_103), key=f"r103_in_{ano_sel}", on_change=cb_103)
                        with col2:
                                lk103 = st.text_area("Link/Evidência (10.3):", value=evidencia_103_salva, key=f"l103_in_{ano_sel}", on_change=cb_103, height=100)
                                if lk103: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk103 or "")]))

                        st.markdown("<span style='color:#6c757d; font-weight:bold;'>📊 Impacto 10.3: +0.0 pts (Referencial)</span>", unsafe_allow_html=True)
                        bloco_comentarios("10.3_b10", res_data, ano_sel)


        # =============================================================================
        # QUESITO 10.3.1 • INDEPENDENTE (REMOVIDO CONDICIONAL)
        # =============================================================================
        with st.container(key=f"bloco_isolado_q10_3_1_{ano_sel}", border=True):
                with st.expander("📌 Quesito 10.3.1 - Licença de Operação da ATT", expanded=True):
                        st.subheader("10.3.1 • Licença de Operação da CETESB")
                        st.write("**Existe licença de operação da CETESB para a Área de Transbordo e Triagem (ATT) de Resíduos Sólidos Urbanos?**")
                        
                        d1031 = res_data.get("10.3.1", {"valor": "Selecione...", "pontos": 0.0, "link": ""}) or {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                        opc1031 = ["Selecione...", "Sim – 00", "Não – -50 (perde 50 pontos)"]
                        v_salvo_1031 = d1031.get("valor", "Selecione...")
                        if v_salvo_1031 not in opc1031: v_salvo_1031 = "Selecione..."
                        evidencia_1031_salva = d1031.get("link", "")

                        def cb_1031():
                                lnk = st.session_state.get(f"l1031_in_{ano_sel}", evidencia_1031_salva).strip()
                                val = st.session_state.get(f"r1031_in_{ano_sel}", v_salvo_1031)
                                pts = 0.0 if "Sim" in val else (-50.0 if "Não" in val else 0.0)
                                save_resp("10.3.1", val, float(pts), lnk)
                                res_data["10.3.1"] = {"valor": val, "pontos": float(pts), "link": lnk}
                                
                                lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                                if lnk != evidencia_1031_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_1031_salva or ""):
                                        st.session_state[f"links_pendentes_10_3_1_{ano_sel}"] = lk_at
                                        st.session_state[f"gatilho_modal_10_3_1_{ano_sel}"] = True

                        col1, col2 = st.columns([1, 1])
                        with col1:
                                st.radio("Selecione uma opção (10.3.1):", options=opc1031, index=opc1031.index(v_salvo_1031), key=f"r1031_in_{ano_sel}", on_change=cb_1031)
                        with col2:
                                lk1031 = st.text_area("Link/Evidência (10.3.1):", value=evidencia_1031_salva, key=f"l1031_in_{ano_sel}", on_change=cb_1031, height=100)
                                if lk1031: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk1031 or "")]))

                        v_f1031 = st.session_state.get(f"r1031_in_{ano_sel}", v_salvo_1031)
                        pts_exibido_1031 = 0.0 if "Sim" in v_f1031 else (-50.0 if "Não" in v_f1031 else 0.0)
                        st.markdown(f"<span style='color:{'#28a745' if pts_exibido_1031 >= 0 else '#dc3545'}; font-weight:bold;'>📊 Impacto 10.3.1: {pts_exibido_1031:.1f} pontos aplicados</span>", unsafe_allow_html=True)
                        bloco_comentarios("10.3.1_b10", res_data, ano_sel)


        # =============================================================================
        # QUESITO 10.3.1.1 • INDEPENDENTE (REMOVIDO CONDICIONAL)
        # =============================================================================
        with st.container(key=f"bloco_isolado_q10_3_1_1_{ano_sel}", border=True):
                with st.expander("📌 Quesito 10.3.1.1 - Validade da Licença da ATT", expanded=True):
                        st.subheader("10.3.1.1 • Validade da Licença")
                        st.write("**Informe o prazo de validade da licença da Área de Transbordo e Triagem (ATT):**")
                        
                        d10311 = res_data.get("10.3.1.1", {"valor": "31/12/2024", "pontos": 0.0, "link": ""}) or {"valor": "31/12/2024", "pontos": 0.0, "link": ""}
                        v_salvo_10311 = d10311.get("valor", "31/12/2024")
                        evidencia_10311_salva = d10311.get("link", "")

                        try:
                                dia_salvo, mes_salvo, ano_salvo = map(int, v_salvo_10311.split("/"))
                        except Exception:
                                dia_salvo, mes_salvo, ano_salvo = 31, 12, 2024

                        chk10311_d = f"q10311_d_in_{ano_sel}"
                        chk10311_m = f"q10311_m_in_{ano_sel}"
                        chk10311_a = f"q10311_a_in_{ano_sel}"
                        chk10311_l = f"l10311_txt_in_{ano_sel}"

                        def cb_10311():
                                d_atual = int(st.session_state.get(chk10311_d, dia_salvo))
                                m_atual = int(st.session_state.get(chk10311_m, mes_salvo))
                                a_atual = int(st.session_state.get(chk10311_a, ano_salvo))
                                lnk_val = st.session_state.get(chk10311_l, evidencia_10311_salva).strip()

                                if a_atual < 2024 or (a_atual == 2024 and m_atual < 12) or (a_atual == 2024 and m_atual == 12 and d_atual <= 31):
                                        pts_calculados = -50.0
                                else:
                                        pts_calculados = 0.0

                                data_formatada = f"{d_atual:02d}/{m_atual:02d}/{a_atual}"
                                save_resp("10.3.1.1", data_formatada, float(pts_calculados), lnk_val)
                                res_data["10.3.1.1"] = {"valor": data_formatada, "pontos": float(pts_calculados), "link": lnk_val}

                                lk_at = re.findall(r'(https?://[^\s]+)', lnk_val or "")
                                if lnk_val != evidencia_10311_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_10311_salva or ""):
                                        st.session_state[f"links_pendentes_10_3_1_1_{ano_sel}"] = lk_at
                                        st.session_state[f"gatilho_modal_10_3_1_1_{ano_sel}"] = True

                        col1, col2 = st.columns([1, 1])
                        with col1:
                                c_dia, c_mes, c_ano = st.columns(3)
                                with c_dia:
                                        d_v = st.number_input("Dia", min_value=1, max_value=31, value=dia_salvo, key=chk10311_d, on_change=cb_10311)
                                with c_mes:
                                        m_v = st.number_input("Mês", min_value=1, max_value=12, value=mes_salvo, key=chk10311_m, on_change=cb_10311)
                                with c_ano:
                                        a_v = st.number_input("Ano", min_value=1900, max_value=2100, value=ano_salvo, key=chk10311_a, on_change=cb_10311)

                                if a_v < 2024 or (a_v == 2024 and m_v < 12) or (a_v == 2024 and m_v == 12 and d_v <= 31):
                                        pts_display = -50.0
                                        cor_metric = "#dc3545"
                                else:
                                        pts_display = 0.0
                                        cor_metric = "#28a745"

                                st.metric(label="Impacto na Pontuação", value=f"{pts_display:.1f} pts")

                        with col2:
                                lk10311 = st.text_area("Link/Evidência (10.3.1.1):", value=evidencia_10311_salva, key=chk10311_l, on_change=cb_10311, height=110)
                                if lk10311: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk10311 or "")]))

                        st.markdown(f"<span style='color:{cor_metric}; font-weight:bold;'>📊 Impacto Técnico 10.3.1.1: {pts_display:.1f} pontos aplicados</span>", unsafe_allow_html=True)
                        bloco_comentarios("10.3.1.1_b10", res_data, ano_sel)

# =============================================================================
        # GATILHOS DOS MODAIS AUTOMÁTICOS • GRUPO 11 (TOTALMENTE INDEPENDENTES)
        # =============================================================================
        if st.session_state.get(f"gatilho_modal_11_0_{ano_sel}", False):
                modal_aviso_link("11.0", st.session_state.get(f"links_pendentes_11_0_{ano_sel}", []))
                st.session_state[f"gatilho_modal_11_0_{ano_sel}"] = False

        if st.session_state.get(f"gatilho_modal_11_1_{ano_sel}", False):
                modal_aviso_link("11.1", st.session_state.get(f"links_pendentes_11_1_{ano_sel}", []))
                st.session_state[f"gatilho_modal_11_1_{ano_sel}"] = False

        if st.session_state.get(f"gatilho_modal_11_2_{ano_sel}", False):
                modal_aviso_link("11.2", st.session_state.get(f"links_pendentes_11_2_{ano_sel}", []))
                st.session_state[f"gatilho_modal_11_2_{ano_sel}"] = False

        if st.session_state.get(f"gatilho_modal_11_3_{ano_sel}", False):
                modal_aviso_link("11.3", st.session_state.get(f"links_pendentes_11_3_{ano_sel}", []))
                st.session_state[f"gatilho_modal_11_3_{ano_sel}"] = False

        if st.session_state.get(f"gatilho_modal_11_3_1_{ano_sel}", False):
                modal_aviso_link("11.3.1", st.session_state.get(f"links_pendentes_11_3_1_{ano_sel}", []))
                st.session_state[f"gatilho_modal_11_3_1_{ano_sel}"] = False

        if st.session_state.get(f"gatilho_modal_11_3_2_{ano_sel}", False):
                modal_aviso_link("11.3.2", st.session_state.get(f"links_pendentes_11_3_2_{ano_sel}", []))
                st.session_state[f"gatilho_modal_11_3_2_{ano_sel}"] = False

        if st.session_state.get(f"gatilho_modal_11_3_2_1_{ano_sel}", False):
                modal_aviso_link("11.3.2.1", st.session_state.get(f"links_pendentes_11_3_2_1_{ano_sel}", []))
                st.session_state[f"gatilho_modal_11_3_2_1_{ano_sel}"] = False

        if st.session_state.get(f"gatilho_modal_11_3_3_{ano_sel}", False):
                modal_aviso_link("11.3.3", st.session_state.get(f"links_pendentes_11_3_3_{ano_sel}", []))
                st.session_state[f"gatilho_modal_11_3_3_{ano_sel}"] = False

        if st.session_state.get(f"gatilho_modal_11_3_3_1_{ano_sel}", False):
                modal_aviso_link("11.3.3.1", st.session_state.get(f"links_pendentes_11_3_3_1_{ano_sel}", []))
                st.session_state[f"gatilho_modal_11_3_3_1_{ano_sel}"] = False

        if st.session_state.get(f"gatilho_modal_11_4_{ano_sel}", False):
                modal_aviso_link("11.4", st.session_state.get(f"links_pendentes_11_4_{ano_sel}", []))
                st.session_state[f"gatilho_modal_11_4_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 11.0 • INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q11_0_{ano_sel}", border=True):
            with st.expander("📌 Quesito 11.0 - Plano de Gerenciamento (PGRCC)", expanded=True):
                st.subheader("11.0 • Existência do PGRCC")
                st.write("**A prefeitura possui Plano de Gerenciamento de Resíduos da Construção Civil (PGRCC) elaborado e implantado de acordo com a resolução CONAMA 307/2002 e suas alterações?**")
                
                d110 = res_data.get("11.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""}) or {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                opc110 = ["Selecione...", "Sim", "Não"]
                v_salvo_110 = d110.get("valor", "Selecione...")
                if v_salvo_110 not in opc110: v_salvo_110 = "Selecione..."
                evidencia_110_salva = d110.get("link", "")

                def cb_110():
                    lnk = st.session_state.get(f"l110_in_{ano_sel}", evidencia_110_salva).strip()
                    val = st.session_state.get(f"r110_in_{ano_sel}", v_salvo_110)
                    pts = 0.0
                    save_resp("11.0", val, float(pts), lnk)
                    res_data["11.0"] = {"valor": val, "pontos": float(pts), "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_110_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_110_salva or ""):
                        st.session_state[f"links_pendentes_11_0_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_11_0_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    st.radio("Selecione uma opção (11.0):", options=opc110, index=opc110.index(v_salvo_110), key=f"r110_in_{ano_sel}", on_change=cb_110)
                with col2:
                    lk110 = st.text_area("Link/Evidência (11.0):", value=evidencia_110_salva, key=f"l110_in_{ano_sel}", on_change=cb_110, height=100)
                    if lk110: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk110 or "")]))

                st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto 11.0: 0.0 pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("11.0", res_data, ano_sel)

        # =============================================================================
        # QUESITO 11.1 • INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q11_1_{ano_sel}", border=True):
            with st.expander("📌 Quesito 11.1 - Instrumento Normativo", expanded=True):
                st.subheader("11.1 • Instrumento Normativo")
                st.write("**Informe o Instrumento normativo, Número e Data da publicação:**")
                
                d111 = res_data.get("11.1", {"valor": "", "link": ""}) or {"valor": "", "link": ""}
                v_salvo_111 = d111.get("valor", "")

                def cb_111():
                    val = st.session_state.get(f"t111_in_{ano_sel}", v_salvo_111).strip()
                    save_resp("11.1", val, 0.0, "")
                    res_data["11.1"] = {"valor": val, "pontos": 0.0, "link": ""}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', val or "")
                    if val != v_salvo_111 and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', v_salvo_111 or ""):
                        st.session_state[f"links_pendentes_11_1_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_11_1_{ano_sel}"] = True

                t111 = st.text_area("Instrumento normativo, Número e Data da publicação (11.1):", value=v_salvo_111, key=f"t111_in_{ano_sel}", on_change=cb_111, height=100)
                if t111: 
                    lk_det = re.findall(r'(https?://[^\s]+)', t111 or "")
                    if lk_det: st.markdown("**🔗 Detectados:** " + " | ".join([f"[{u}]({u})" for u in lk_det]))
                        
                bloco_comentarios("11.1", res_data, ano_sel)

        # =============================================================================
        # QUESITO 11.2 • INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q11_2_{ano_sel}", border=True):
            with st.expander("📌 Quesito 11.2 - Página Eletrônica do Plano", expanded=True):
                st.subheader("11.2 • Endereço Eletrônico do PGRCC")
                st.write("**Informe a página eletrônica (link na internet) do Plano de Gerenciamento de Resíduos da Construção Civil (PGRCC):**")
                st.caption("Se não estiver disponível na internet, insira no campo de resposta o texto **XYZ**.")
                
                d112 = res_data.get("11.2", {"valor": "XYZ", "pontos": 0.0, "link": ""}) or {"valor": "XYZ", "pontos": 0.0, "link": ""}
                v_salvo_112 = d112.get("valor", "XYZ")
                evidencia_112_salva = d112.get("link", "")

                def cb_112():
                    val = st.session_state.get(f"i112_in_{ano_sel}", v_salvo_112).strip()
                    lnk = st.session_state.get(f"l112_in_{ano_sel}", evidencia_112_salva).strip()
                    pts = 0.0 if val.upper() == "XYZ" or val == "" else 2.0
                    save_resp("11.2", val, float(pts), lnk)
                    res_data["11.2"] = {"valor": val, "pontos": float(pts), "link": lnk}
                    
                    lk_val = re.findall(r'(https?://[^\s]+)', val or "")
                    lk_lnk = re.findall(r'(https?://[^\s]+)', lnk or "")
                    todos_at = lk_val + lk_lnk
                    
                    lk_val_ant = re.findall(r'(https?://[^\s]+)', v_salvo_112 or "")
                    lk_lnk_ant = re.findall(r'(https?://[^\s]+)', evidencia_112_salva or "")
                    todos_ant = lk_val_ant + lk_lnk_ant
                    
                    if (val != v_salvo_112 or lnk != evidencia_112_salva) and todos_at and todos_at != todos_ant:
                        st.session_state[f"links_pendentes_11_2_{ano_sel}"] = todos_at
                        st.session_state[f"gatilho_modal_11_2_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    i112 = st.text_input("Endereço eletrônico (Link) ou XYZ:", value=v_salvo_112, key=f"i112_in_{ano_sel}", on_change=cb_112)
                    if i112 and i112.strip().upper() != "XYZ":
                        lk_i112 = re.findall(r'(https?://[^\s]+)', i112 or "")
                        if lk_i112: st.markdown("**🔗 Link do Plano:** " + " | ".join([f"[{u}]({u})" for u in lk_i112]))
                with col2:
                    lk112 = st.text_area("Link/Evidência Adicional (11.2):", value=evidencia_112_salva, key=f"l112_in_{ano_sel}", on_change=cb_112, height=100)
                    if lk112: st.markdown("**🔗 Links da Evidência:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk112 or "")]))

                v_f112 = st.session_state.get(f"i112_in_{ano_sel}", v_salvo_112)
                pts_exibido_112 = 0.0 if v_f112.strip().upper() == "XYZ" or v_f112.strip() == "" else 2.0
                st.markdown(f"<span style='color:#28a745; font-weight:bold;'>📊 Impacto 11.2: {pts_exibido_112:.1f} pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("11.2", res_data, ano_sel)

        # =============================================================================
        # QUESITO 11.3 • INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q11_3_{ano_sel}", border=True):
            with st.expander("📌 Quesito 11.3 - Cronograma de Metas", expanded=True):
                st.subheader("11.3 • Existência de Cronograma")
                st.write("**Possui cronograma com as metas a serem cumpridas?**")
                
                d113 = res_data.get("11.3", {"valor": "Selecione...", "pontos": 0.0, "link": ""}) or {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                opc113 = ["Selecione...", "Sim – 30", "Não – 00"]
                v_salvo_113 = d113.get("valor", "Selecione...")
                if v_salvo_113 not in opc113: v_salvo_113 = "Selecione..."
                evidencia_113_salva = d113.get("link", "")

                def cb_113():
                    lnk = st.session_state.get(f"l113_in_{ano_sel}", evidencia_113_salva).strip()
                    val = st.session_state.get(f"r113_in_{ano_sel}", v_salvo_113)
                    pts = 30.0 if "Sim" in val else 0.0
                    save_resp("11.3", val, float(pts), lnk)
                    res_data["11.3"] = {"valor": val, "pontos": float(pts), "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_113_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_113_salva or ""):
                        st.session_state[f"links_pendentes_11_3_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_11_3_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    st.radio("Selecione uma opção (11.3):", options=opc113, index=opc113.index(v_salvo_113), key=f"r113_in_{ano_sel}", on_change=cb_113)
                with col2:
                    lk113 = st.text_area("Link/Evidência (11.3):", value=evidencia_113_salva, key=f"l113_in_{ano_sel}", on_change=cb_113, height=100)
                    if lk113: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk113 or "")]))

                v_f113 = st.session_state.get(f"r113_in_{ano_sel}", v_salvo_113)
                pts_exibido_113 = 30.0 if "Sim" in v_f113 else 0.0
                st.markdown(f"<span style='color:#28a745; font-weight:bold;'>📊 Impacto 11.3: {pts_exibido_113:.1f} pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("11.3", res_data, ano_sel)

        # =============================================================================
        # QUESITO 11.3.1 • INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q11_3_1_{ano_sel}", border=True):
            with st.expander("📌 Quesito 11.3.1 - Descrição das Metas", expanded=True):
                st.subheader("11.3.1 • Metas Previstas")
                st.write("**Informe quais metas estão previstas:**")
                
                d1131 = res_data.get("11.3.1", {"valor": "[]", "pontos": 0.0, "link": ""}) or {"valor": "[]", "pontos": 0.0, "link": ""}
                v_salvo_1131 = d1131.get("valor", "[]")
                evidencia_1131_salva = d1131.get("link", "")
                
                opts1131 = [
                    "Aumento/melhoria dos Pontos de Entrega Voluntária - PEV", 
                    "Aumento/melhoria de Áreas de Transbordo e Triagem - ATT", 
                    "Realização de operações de coleta de Resíduos da Construção Civil em “pontos viciados”", 
                    "Cadastro de transportadores de Resíduos da Construção Civil", 
                    "Outro"
                ]

                def cb_1131():
                    sel = []
                    for opt in opts1131:
                        if st.session_state.get(f"ck_1131_{opts1131.index(opt)}_{ano_sel}", False):
                            sel.append(opt)
                    lnk = st.session_state.get(f"l1131_in_{ano_sel}", evidencia_1131_salva).strip()
                    val = str(sel)
                    save_resp("11.3.1", val, 0.0, lnk)
                    res_data["11.3.1"] = {"valor": val, "pontos": 0.0, "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_1131_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_1131_salva or ""):
                        st.session_state[f"links_pendentes_11_3_1_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_11_3_1_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    texto_seguro_1131 = str(v_salvo_1131) if v_salvo_1131 not in ["", "[]"] else ""
                    for opt in opts1131:
                        st.checkbox(opt, value=opt in texto_seguro_1131, key=f"ck_1131_{opts1131.index(opt)}_{ano_sel}", on_change=cb_1131)
                with col2:
                    lk1131 = st.text_area("Link/Evidência (11.3.1):", value=evidencia_1131_salva, key=f"l1131_in_{ano_sel}", on_change=cb_1131, height=100)
                    if lk1131: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk1131 or "")]))

                st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto 11.3.1: 0.0 pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("11.3.1", res_data, ano_sel)

        # =============================================================================
        # QUESITO 11.3.2 • INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q11_3_2_{ano_sel}", border=True):
            with st.expander("📌 Quesito 11.3.2 - Monitoramento do Plano", expanded=True):
                st.subheader("11.3.2 • Realização de Monitoramento")
                st.write("**Realiza monitoramento e avaliação das ações e metas?**")
                
                d1132 = res_data.get("11.3.2", {"valor": "Selecione...", "pontos": 0.0, "link": ""}) or {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                opc1132 = ["Selecione...", "Sim – 20", "Não – 00"]
                v_salvo_1132 = d1132.get("valor", "Selecione...")
                if v_salvo_1132 not in opc1132: v_salvo_1132 = "Selecione..."
                evidencia_1132_salva = d1132.get("link", "")

                def cb_1132():
                    lnk = st.session_state.get(f"l1132_in_{ano_sel}", evidencia_1132_salva).strip()
                    val = st.session_state.get(f"r1132_in_{ano_sel}", v_salvo_1132)
                    pts = 20.0 if "Sim" in val else 0.0
                    save_resp("11.3.2", val, float(pts), lnk)
                    res_data["11.3.2"] = {"valor": val, "pontos": float(pts), "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_1132_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_1132_salva or ""):
                        st.session_state[f"links_pendentes_11_3_2_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_11_3_2_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    st.radio("Selecione uma opção (11.3.2):", options=opc1132, index=opc1132.index(v_salvo_1132), key=f"r1132_in_{ano_sel}", on_change=cb_1132)
                with col2:
                    lk1132 = st.text_area("Link/Evidência (11.3.2):", value=evidencia_1132_salva, key=f"l1132_in_{ano_sel}", on_change=cb_1132, height=100)
                    if lk1132: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk1132 or "")]))

                v_f1132 = st.session_state.get(f"r1132_in_{ano_sel}", v_salvo_1132)
                pts_exibido_1132 = 20.0 if "Sim" in v_f1132 else 0.0
                st.markdown(f"<span style='color:#28a745; font-weight:bold;'>📊 Impacto 11.3.2: {pts_exibido_1132:.1f} pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("11.3.2", res_data, ano_sel)

        # =============================================================================
        # QUESITO 11.3.2.1 • INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q11_3_2_1_{ano_sel}", border=True):
            with st.expander("📌 Quesito 11.3.2.1 - Metodologia de Monitoramento", expanded=True):
                st.subheader("11.3.2.1 • Forma de Monitoramento")
                st.write("**De que forma é realizado o monitoramento e avaliação?**")
                
                d11321 = res_data.get("11.3.2.1", {"valor": "[]", "pontos": 0.0, "link": ""}) or {"valor": "[]", "pontos": 0.0, "link": ""}
                v_salvo_11321 = d11321.get("valor", "[]")
                evidencia_11321_salva = d11321.get("link", "")
                
                opts11321 = ["Relatórios anuais discutidos e/ou publicados", "Indicadores de eficácia e eficiência", "Avaliação de recursos aplicados", "Outro"]

                def cb_11321():
                    sel = []
                    for opt in opts11321:
                        if st.session_state.get(f"ck_11321_{opts11321.index(opt)}_{ano_sel}", False):
                            sel.append(opt)
                    lnk = st.session_state.get(f"l11321_in_{ano_sel}", evidencia_11321_salva).strip()
                    val = str(sel)
                    save_resp("11.3.2.1", val, 0.0, lnk)
                    res_data["11.3.2.1"] = {"valor": val, "pontos": 0.0, "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_11321_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_11321_salva or ""):
                        st.session_state[f"links_pendentes_11_3_2_1_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_11_3_2_1_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    texto_seguro_11321 = str(v_salvo_11321) if v_salvo_11321 not in ["", "[]"] else ""
                    for opt in opts11321:
                        st.checkbox(opt, value=opt in texto_seguro_11321, key=f"ck_11321_{opts11321.index(opt)}_{ano_sel}", on_change=cb_11321)
                with col2:
                    lk11321 = st.text_area("Link/Evidência (11.3.2.1):", value=evidencia_11321_salva, key=f"l11321_in_{ano_sel}", on_change=cb_11321, height=100)
                    if lk11321: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk11321 or "")]))

                st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto 11.3.2.1: 0.0 pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("11.3.2.1", res_data, ano_sel)

        # =============================================================================
        # QUESITO 11.3.3 • INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q11_3_3_{ano_sel}", border=True):
            with st.expander("📌 Quesito 11.3.3 - Cumprimento de Prazos", expanded=True):
                st.subheader("11.3.3 • Cumprimento das Metas")
                st.write("**As metas do Plano estão sendo cumpridas no prazo estipulado?**")
                
                d1133 = res_data.get("11.3.3", {"valor": "Selecione...", "pontos": 0.0, "link": ""}) or {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                opc1133 = [
                    "Selecione...",
                    "Todas as metas foram cumpridas dentro do prazo – 40", 
                    "A maior parte das metas foram cumpridas dentro do prazo – 30", 
                    "A menor parte das metas foram cumpridas dentro do prazo – 10", 
                    "As metas não foram cumpridas dentro do prazo – 00"
                ]
                v_salvo_1133 = d1133.get("valor", "Selecione...")
                if v_salvo_1133 not in opc1133: v_salvo_1133 = "Selecione..."
                evidencia_1133_salva = d1133.get("link", "")

                def cb_1133():
                    lnk = st.session_state.get(f"l1133_in_{ano_sel}", evidencia_1133_salva).strip()
                    val = st.session_state.get(f"r1133_in_{ano_sel}", v_salvo_1133)
                    pts = 40.0 if "Todas" in val else (30.0 if "maior parte" in val else (10.0 if "menor parte" in val else 0.0))
                    save_resp("11.3.3", val, float(pts), lnk)
                    res_data["11.3.3"] = {"valor": val, "pontos": float(pts), "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_1133_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_1133_salva or ""):
                        st.session_state[f"links_pendentes_11_3_3_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_11_3_3_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    st.radio("Selecione uma opção (11.3.3):", options=opc1133, index=opc1133.index(v_salvo_1133), key=f"r1133_in_{ano_sel}", on_change=cb_1133)
                with col2:
                    lk1133 = st.text_area("Link/Evidência (11.3.3):", value=evidencia_1133_salva, key=f"l1133_in_{ano_sel}", on_change=cb_1133, height=100)
                    if lk1133: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk1133 or "")]))

                v_f1133 = st.session_state.get(f"r1133_in_{ano_sel}", v_salvo_1133)
                pts_exibido_1133 = 40.0 if "Todas" in v_f1133 else (30.0 if "maior parte" in v_f1133 else (10.0 if "menor parte" in v_f1133 else 0.0))
                st.markdown(f"<span style='color:#28a745; font-weight:bold;'>📊 Impacto 11.3.3: {pts_exibido_1133:.1f} pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("11.3.3", res_data, ano_sel)

        # =============================================================================
        # QUESITO 11.3.3.1 • INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q11_3_3_1_{ano_sel}", border=True):
            with st.expander("📌 Quesito 11.3.3.1 - Motivos de Descumprimento", expanded=True):
                st.subheader("11.3.3.1 • Motivos de Atraso")
                st.write("**Assinale os motivos pelos quais as metas não estão sendo cumpridas:**")
                
                d11331 = res_data.get("11.3.3.1", {"valor": "[]", "pontos": 0.0, "link": ""}) or {"valor": "[]", "pontos": 0.0, "link": ""}
                v_salvo_11331 = d11331.get("valor", "[]")
                evidencia_11331_salva = d11331.get("link", "")
                
                opts11331 = ["Falta de recursos orçamentários", "Falta de aprovação legislativa", "Atraso na licitação", "Não realizou licitação necessária", "Falta de pessoal qualificado", "Falta de consenso no consórcio intermunicipal", "Outros"]

                def cb_11331():
                    sel = []
                    for opt in opts11331:
                        if st.session_state.get(f"ck_11331_{opts11331.index(opt)}_{ano_sel}", False):
                            sel.append(opt)
                    lnk = st.session_state.get(f"l11331_in_{ano_sel}", evidencia_11331_salva).strip()
                    val = str(sel)
                    save_resp("11.3.3.1", val, 0.0, lnk)
                    res_data["11.3.3.1"] = {"valor": val, "pontos": 0.0, "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_11331_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_11331_salva or ""):
                        st.session_state[f"links_pendentes_11_3_3_1_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_11_3_3_1_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    texto_seguro_11331 = str(v_salvo_11331) if v_salvo_11331 not in ["", "[]"] else ""
                    for opt in opts11331:
                        st.checkbox(opt, value=opt in texto_seguro_11331, key=f"ck_11331_{opts11331.index(opt)}_{ano_sel}", on_change=cb_11331)
                with col2:
                    lk11331 = st.text_area("Link/Evidência (11.3.3.1):", value=evidencia_11331_salva, key=f"l11331_in_{ano_sel}", on_change=cb_11331, height=100)
                    if lk11331: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk11331 or "")]))

                st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto 11.3.3.1: 0.0 pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("11.3.3.1", res_data, ano_sel)

        # =============================================================================
        # GATILHOS DOS MODAIS AUTOMÁTICOS • GRUPO 11 (CONTINUAÇÃO - TOTALMENTE INDEPENDENTES)
        # =============================================================================
        if st.session_state.get(f"gatilho_modal_11_4_{ano_sel}", False):
            modal_aviso_link("11.4", st.session_state.get(f"links_pendentes_11_4_{ano_sel}", []))
            st.session_state[f"gatilho_modal_11_4_{ano_sel}"] = False

        if st.session_state.get(f"gatilho_modal_11_5_{ano_sel}", False):
            modal_aviso_link("11.5", st.session_state.get(f"links_pendentes_11_5_{ano_sel}", []))
            st.session_state[f"gatilho_modal_11_5_{ano_sel}"] = False

        if st.session_state.get(f"gatilho_modal_11_5_1_{ano_sel}", False):
            modal_aviso_link("11.5.1", st.session_state.get(f"links_pendentes_11_5_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_11_5_1_{ano_sel}"] = False

        if st.session_state.get(f"gatilho_modal_11_6_{ano_sel}", False):
            modal_aviso_link("11.6", st.session_state.get(f"links_pendentes_11_6_{ano_sel}", []))
            st.session_state[f"gatilho_modal_11_6_{ano_sel}"] = False

        if st.session_state.get(f"gatilho_modal_11_6_1_{ano_sel}", False):
            modal_aviso_link("11.6.1", st.session_state.get(f"links_pendentes_11_6_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_11_6_1_{ano_sel}"] = False

        if st.session_state.get(f"gatilho_modal_11_6_1_1_{ano_sel}", False):
            modal_aviso_link("11.6.1.1", st.session_state.get(f"links_pendentes_11_6_1_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_11_6_1_1_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 11.4 • INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q11_4_{ano_sel}", border=True):
            with st.expander("📌 Quesito 11.4 - Responsabilidade de Triagem", expanded=True):
                st.subheader("11.4 • Responsável pela Triagem")
                st.write("**Quem é o responsável pela triagem dos resíduos da construção civil?**")
                
                d114 = res_data.get("11.4", {"valor": "Selecione...", "pontos": 0.0, "link": ""}) or {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                opc114 = [
                    "Selecione...",
                    "Gerador dos resíduos – 00", 
                    "Prefeitura – -10 (perde 10 pontos)", 
                    "Outros – -10 (perde 10 pontos)"
                ]
                v_salvo_114 = d114.get("valor", "Selecione...")
                if v_salvo_114 not in opc114: v_salvo_114 = "Selecione..."
                evidencia_114_salva = d114.get("link", "")

                def cb_114():
                    lnk = st.session_state.get(f"l114_in_{ano_sel}", evidencia_114_salva).strip()
                    val = st.session_state.get(f"r114_in_{ano_sel}", v_salvo_114)
                    pts = 0.0 if "Gerador" in val else (-10.0 if "Prefeitura" in val or "Outros" in val else 0.0)
                    save_resp("11.4", val, float(pts), lnk)
                    res_data["11.4"] = {"valor": val, "pontos": float(pts), "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_114_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_114_salva or ""):
                        st.session_state[f"links_pendentes_11_4_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_11_4_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    st.radio("Selecione uma opção (11.4):", options=opc114, index=opc114.index(v_salvo_114), key=f"r114_in_{ano_sel}", on_change=cb_114)
                with col2:
                    lk114 = st.text_area("Link/Evidência (11.4):", value=evidencia_114_salva, key=f"l114_in_{ano_sel}", on_change=cb_114, height=100)
                    if lk114: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk114 or "")]))

                v_f114 = st.session_state.get(f"r114_in_{ano_sel}", v_salvo_114)
                pts_exibido_114 = 0.0 if "Gerador" in v_f114 else (-10.0 if "Prefeitura" in v_f114 or "Outros" in v_f114 else 0.0)
                st.markdown(f"<span style='color:{'#28a745' if pts_exibido_114 >= 0 else '#dc3545'}; font-weight:bold;'>📊 Impacto 11.4: {pts_exibido_114:.1f} pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("11.4", res_data, ano_sel)

        # =============================================================================
        # QUESITO 11.5 • INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q11_5_{ano_sel}", border=True):
            with st.expander("📌 Quesito 11.5 - Fiscalização de Gerenciamento", expanded=True):
                st.subheader("11.5 • Execução de Fiscalizações")
                st.write("**A Prefeitura realiza fiscalizações das atividades envolvidas no gerenciamento dos resíduos da construção civil?**")
                
                d115 = res_data.get("11.5", {"valor": "Selecione...", "pontos": 0.0, "link": ""}) or {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                opc115 = ["Selecione...", "Sim – 10", "Não – 00"]
                v_salvo_115 = d115.get("valor", "Selecione...")
                if v_salvo_115 not in opc115: v_salvo_115 = "Selecione..."
                evidencia_115_salva = d115.get("link", "")

                def cb_115():
                    lnk = st.session_state.get(f"l115_in_{ano_sel}", evidencia_115_salva).strip()
                    val = st.session_state.get(f"r115_in_{ano_sel}", v_salvo_115)
                    pts = 10.0 if "Sim" in val else 0.0
                    save_resp("11.5", val, float(pts), lnk)
                    res_data["11.5"] = {"valor": val, "pontos": float(pts), "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_115_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_115_salva or ""):
                        st.session_state[f"links_pendentes_11_5_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_11_5_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    st.radio("Selecione uma opção (11.5):", options=opc115, index=opc115.index(v_salvo_115), key=f"r115_in_{ano_sel}", on_change=cb_115)
                with col2:
                    lk115 = st.text_area("Link/Evidência (11.5):", value=evidencia_115_salva, key=f"l115_in_{ano_sel}", on_change=cb_115, height=100)
                    if lk115: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk115 or "")]))

                v_f115 = st.session_state.get(f"r115_in_{ano_sel}", v_salvo_115)
                pts_exibido_115 = 10.0 if "Sim" in v_f115 else 0.0
                st.markdown(f"<span style='color:#28a745; font-weight:bold;'>📊 Impacto 11.5: {pts_exibido_115:.1f} pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("11.5", res_data, ano_sel)

        # =============================================================================
        # QUESITO 11.5.1 • INDEPENDENTE (Condicional Visual)
        # =============================================================================
        v_cond_115 = st.session_state.get(f"r115_in_{ano_sel}", v_salvo_115)
        if "Sim" in v_cond_115:
            with st.container(key=f"bloco_isolado_q11_5_1_{ano_sel}", border=True):
                with st.expander("📌 Quesito 11.5.1 - Atividades Fiscalizadas", expanded=True):
                    st.subheader("11.5.1 • Escopo das Fiscalizações")
                    st.write("**Em quais atividades são realizadas essas fiscalizações?**")
                    
                    d1151 = res_data.get("11.5.1", {"valor": "[]", "pontos": 0.0, "link": ""}) or {"valor": "[]", "pontos": 0.0, "link": ""}
                    v_salvo_1151 = d1151.get("valor", "[]")
                    evidencia_1151_salva = d1151.get("link", "")
                    
                    opts1151 = ["Coleta", "Acondicionamento", "Transporte", "Destinação / disposição final"]

                    def cb_1151():
                        sel = []
                        for opt in opts1151:
                            if st.session_state.get(f"ck_1151_{opts1151.index(opt)}_{ano_sel}", False):
                                sel.append(opt)
                        lnk = st.session_state.get(f"l1151_in_{ano_sel}", evidencia_1151_salva).strip()
                        val = str(sel)
                        save_resp("11.5.1", val, 0.0, lnk)
                        res_data["11.5.1"] = {"valor": val, "pontos": 0.0, "link": lnk}
                        
                        lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                        if lnk != evidencia_1151_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_1151_salva or ""):
                            st.session_state[f"links_pendentes_11_5_1_{ano_sel}"] = lk_at
                            st.session_state[f"gatilho_modal_11_5_1_{ano_sel}"] = True

                    col1, col2 = st.columns([1, 1])
                    with col1:
                        texto_seguro_1151 = str(v_salvo_1151) if v_salvo_1151 not in ["", "[]"] else ""
                        for opt in opts1151:
                            st.checkbox(opt, value=opt in texto_seguro_1151, key=f"ck_1151_{opts1151.index(opt)}_{ano_sel}", on_change=cb_1151)
                    with col2:
                        lk1151 = st.text_area("Link/Evidência (11.5.1):", value=evidencia_1151_salva, key=f"l1151_in_{ano_sel}", on_change=cb_1151, height=100)
                        if lk1151: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk1151 or "")]))

                    st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto 11.5.1: 0.0 pontos aplicados</span>", unsafe_allow_html=True)
                    bloco_comentarios("11.5.1", res_data, ano_sel)

        # =============================================================================
        # QUESITO 11.6 • INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q11_6_{ano_sel}", border=True):
            with st.expander("📌 Quesito 11.6 - Área de Transbordo e Triagem (ATT)", expanded=True):
                st.subheader("11.6 • Existência de ATT")
                st.write("**Existe Área de Transbordo e Triagem (ATT) para os Resíduos da Construção Civil no município?**")
                
                d116 = res_data.get("11.6", {"valor": "Selecione...", "pontos": 0.0, "link": ""}) or {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                opc116 = ["Selecione...", "Sim", "Não"]
                v_salvo_116 = d116.get("valor", "Selecione...")
                if v_salvo_116 not in opc116: v_salvo_116 = "Selecione..."
                evidencia_116_salva = d116.get("link", "")

                def cb_116():
                    lnk = st.session_state.get(f"l116_in_{ano_sel}", evidencia_116_salva).strip()
                    val = st.session_state.get(f"r116_in_{ano_sel}", v_salvo_116)
                    pts = 0.0
                    save_resp("11.6", val, float(pts), lnk)
                    res_data["11.6"] = {"valor": val, "pontos": float(pts), "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_116_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_116_salva or ""):
                        st.session_state[f"links_pendentes_11_6_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_11_6_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    st.radio("Selecione uma opção (11.6):", options=opc116, index=opc116.index(v_salvo_116), key=f"r116_in_{ano_sel}", on_change=cb_116)
                with col2:
                    lk116 = st.text_area("Link/Evidência (11.6):", value=evidencia_116_salva, key=f"l116_in_{ano_sel}", on_change=cb_116, height=100)
                    if lk116: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk116 or "")]))

                st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto 11.6: 0.0 pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("11.6", res_data, ano_sel)

        # =============================================================================
        # QUESITO 11.6.1 • INDEPENDENTE (Condicional Visual)
        # =============================================================================
        v_cond_116 = st.session_state.get(f"r116_in_{ano_sel}", v_salvo_116)
        if "Sim" in v_cond_116:
            with st.container(key=f"bloco_isolado_q11_6_1_{ano_sel}", border=True):
                with st.expander("📌 Quesito 11.6.1 - Licença da CETESB", expanded=True):
                    st.subheader("11.6.1 • Licença de Operação da ATT")
                    st.write("**Existe licença de operação da CETESB para a Área de Transbordo e Triagem (ATT) de Resíduos da Construção Civil?**")
                    
                    d1161 = res_data.get("11.6.1", {"valor": "Selecione...", "pontos": 0.0, "link": ""}) or {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                    opc1161 = ["Selecione...", "Sim", "Não"]
                    v_salvo_1161 = d1161.get("valor", "Selecione...")
                    if v_salvo_1161 not in opc1161: v_salvo_1161 = "Selecione..."
                    evidencia_1161_salva = d1161.get("link", "")

                    def cb_1161():
                        lnk = st.session_state.get(f"l1161_in_{ano_sel}", evidencia_1161_salva).strip()
                        val = st.session_state.get(f"r1161_in_{ano_sel}", v_salvo_1161)
                        pts = 0.0
                        save_resp("11.6.1", val, float(pts), lnk)
                        res_data["11.6.1"] = {"valor": val, "pontos": float(pts), "link": lnk}
                        
                        lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                        if lnk != evidencia_1161_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_1161_salva or ""):
                            st.session_state[f"links_pendentes_11_6_1_{ano_sel}"] = lk_at
                            st.session_state[f"gatilho_modal_11_6_1_{ano_sel}"] = True

                    col1, col2 = st.columns([1, 1])
                    with col1:
                        st.radio("Selecione uma opção (11.6.1):", options=opc1161, index=opc1161.index(v_salvo_1161), key=f"r1161_in_{ano_sel}", on_change=cb_1161)
                    with col2:
                        lk1161 = st.text_area("Link/Evidência (11.6.1):", value=evidencia_1161_salva, key=f"l1161_in_{ano_sel}", on_change=cb_1161, height=100)
                        if lk1161: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk1161 or "")]))

                    st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto 11.6.1: 0.0 pontos aplicados</span>", unsafe_allow_html=True)
                    bloco_comentarios("11.6.1", res_data, ano_sel)

        # =============================================================================
        # QUESITO 11.6.1.1 • INDEPENDENTE (Condicional Visual de Data Adaptada)
        # =============================================================================
        v_cond_1161 = st.session_state.get(f"r1161_in_{ano_sel}", "Selecione...")
        if "Sim" in v_cond_116 and "Sim" in v_cond_1161:
            with st.container(key=f"bloco_isolado_q11_6_1_1_{ano_sel}", border=True):
                with st.expander("📌 Quesito 11.6.1.1 - Prazo de Validade", expanded=True):
                    st.subheader("11.6.1.1 • Validade da Licença")
                    st.write("**Informe o prazo de validade da licença:**")
                    
                    d11611 = res_data.get("11.6.1.1", {"valor": "31/12/2024", "pontos": 0.0, "link": ""}) or {"valor": "31/12/2024", "pontos": 0.0, "link": ""}
                    v_salvo_11611 = d11611.get("valor", "31/12/2024")
                    evidencia_11611_salva = d11611.get("link", "")
                    
                    try:
                        dia_salvo, mes_salvo, ano_salvo = map(int, v_salvo_11611.split("/"))
                    except:
                        dia_salvo, mes_salvo, ano_salvo = 31, 12, 2024

                    def cb_11611():
                        d_ = st.session_state.get(f"q11611_d_{ano_sel}", dia_salvo)
                        m_ = st.session_state.get(f"q11611_m_{ano_sel}", mes_salvo)
                        a_ = st.session_state.get(f"q11611_a_{ano_sel}", ano_salvo)
                        val = f"{d_:02d}/{m_:02d}/{a_}"
                        lnk = st.session_state.get(f"l11611_in_{ano_sel}", evidencia_11611_salva).strip()
                        
                        save_resp("11.6.1.1", val, 0.0, lnk)
                        res_data["11.6.1.1"] = {"valor": val, "pontos": 0.0, "link": lnk}
                        
                        lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                        if lnk != evidencia_11611_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_11611_salva or ""):
                            st.session_state[f"links_pendentes_11_6_1_1_{ano_sel}"] = lk_at
                            st.session_state[f"gatilho_modal_11_6_1_1_{ano_sel}"] = True

                    col1, col2 = st.columns([1, 1])
                    with col1:
                        c_dia, c_mes, c_ano = st.columns(3)
                        with c_dia:
                            st.number_input("Dia", min_value=1, max_value=31, value=dia_salvo, key=f"q11611_d_{ano_sel}", on_change=cb_11611)
                        with c_mes:
                            st.number_input("Mês", min_value=1, max_value=12, value=mes_salvo, key=f"q11611_m_{ano_sel}", on_change=cb_11611)
                        with c_ano:
                            st.number_input("Ano", min_value=1900, max_value=2100, value=ano_salvo, key=f"q11611_a_{ano_sel}", on_change=cb_11611)
                        st.markdown("<br>", unsafe_allow_html=True)
                    with col2:
                        lk11611 = st.text_area("Link/Evidência (11.6.1.1):", value=evidencia_11611_salva, key=f"l11611_in_{ano_sel}", on_change=cb_11611, height=100)
                        if lk11611: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk11611 or "")]))

                    st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto 11.6.1.1: 0.0 pontos aplicados</span>", unsafe_allow_html=True)
                    bloco_comentarios("11.6.1.1", res_data, ano_sel)

       # =============================================================================
        # GATILHOS DOS MODAIS AUTOMÁTICOS • GRUPO 12 (TOTALMENTE INDEPENDENTES)
        # =============================================================================
        if st.session_state.get(f"gatilho_modal_12_0_{ano_sel}", False):
            modal_aviso_link("12.0", st.session_state.get(f"links_pendentes_12_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_12_0_{ano_sel}"] = False

        if st.session_state.get(f"gatilho_modal_12_1_{ano_sel}", False):
            modal_aviso_link("12.1", st.session_state.get(f"links_pendentes_12_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_12_1_{ano_sel}"] = False

# =============================================================================
        # QUESITO 12.0 • TOTALMENTE INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q12_0_{ano_sel}", border=True):
            with st.expander("📌 Quesito 12.0 - Processamento de Resíduos", expanded=True):
                st.subheader("12.0 • Processamento Prévio")
                st.write("**Antes de aterrar o lixo, o município realiza algum tipo de processamento de resíduos?**")
                
                d120 = res_data.get("12.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""}) or {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                opc120 = ["Selecione...", "Sim", "Não"]
                v_salvo_120 = d120.get("valor", "Selecione...")
                if v_salvo_120 not in opc120: v_salvo_120 = "Selecione..."
                evidencia_120_salva = d120.get("link", "")

                def cb_120():
                    lnk = st.session_state.get(f"l120_in_{ano_sel}", evidencia_120_salva).strip()
                    val = st.session_state.get(f"r120_in_{ano_sel}", v_salvo_120)
                    pts = 0.0
                    
                    save_resp("12.0", val, float(pts), lnk)
                    res_data["12.0"] = {"valor": val, "pontos": float(pts), "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_120_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_120_salva or ""):
                        st.session_state[f"links_pendentes_12_0_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_12_0_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    st.radio("Selecione uma opção (12.0):", options=opc120, index=opc120.index(v_salvo_120), key=f"r120_in_{ano_sel}", on_change=cb_120)
                with col2:
                    lk120 = st.text_area("Link/Evidência (12.0):", value=evidencia_120_salva, key=f"l120_in_{ano_sel}", on_change=cb_120, height=100)
                    if lk120: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk120 or "")]))

                st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto 12.0: 0.0 pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("12.0", res_data, ano_sel)

        # =============================================================================
        # QUESITO 12.1 • TOTALMENTE INDEPENDENTE (Removida a condicional visual)
        # =============================================================================
        with st.container(key=f"bloco_isolado_q12_1_{ano_sel}", border=True):
            with st.expander("📌 Quesito 12.1 - Formas de Processamento", expanded=True):
                st.subheader("12.1 • Formas Realizadas")
                st.write("**Assinale qual a forma realizada de processamento de resíduos:**")
                
                d121 = res_data.get("12.1", {"valor": "[]", "pontos": 0.0, "link": ""}) or {"valor": "[]", "pontos": 0.0, "link": ""}
                v_salvo_121 = d121.get("valor", "[]")
                evidencia_121_salva = d121.get("link", "")
                
                opts121 = {
                    "Reciclagem – 04": 4.0, 
                    "Compostagem – 20": 20.0, 
                    "Reutilização – 20": 20.0, 
                    "Sistema de Logística Reversa – 10": 10.0, 
                    "Outro – 00": 0.0
                }

                def cb_121():
                    sel = []
                    pts = 0.0
                    for opt, p_val in opts121.items():
                        if st.session_state.get(f"ck_121_{list(opts121.keys()).index(opt)}_{ano_sel}", False):
                            sel.append(opt)
                            pts += p_val
                            
                    lnk = st.session_state.get(f"l121_in_{ano_sel}", evidencia_121_salva).strip()
                    val = str(sel)
                    
                    save_resp("12.1", val, float(pts), lnk)
                    res_data["12.1"] = {"valor": val, "pontos": float(pts), "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_121_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_121_salva or ""):
                        st.session_state[f"links_pendentes_12_1_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_12_1_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    texto_seguro_121 = str(v_salvo_121) if v_salvo_121 not in ["", "[]"] else ""
                    for opt in opts121.keys():
                        st.checkbox(opt, value=opt in texto_seguro_121, key=f"ck_121_{list(opts121.keys()).index(opt)}_{ano_sel}", on_change=cb_121)
                with col2:
                    lk121 = st.text_area("Link/Evidência (12.1):", value=evidencia_121_salva, key=f"l121_in_{ano_sel}", on_change=cb_121, height=100)
                    if lk121: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk121 or "")]))

                # Recalcula feedback de pontuação em tempo real na tela
                pts_exibido_121 = 0.0
                for opt, p_val in opts121.items():
                    if st.session_state.get(f"ck_121_{list(opts121.keys()).index(opt)}_{ano_sel}", False):
                        pts_exibido_121 += p_val
                        
                st.markdown(f"<span style='color:#28a745; font-weight:bold;'>📊 Impacto 12.1: {pts_exibido_121:.1f} pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("12.1", res_data, ano_sel)

        # =============================================================================
        # GATILHOS DOS MODAIS AUTOMÁTICOS • GRUPO 13 (TOTALMENTE INDEPENDENTES)
        # =============================================================================
        if st.session_state.get(f"gatilho_modal_13_0_{ano_sel}", False):
            modal_aviso_link("13.0", st.session_state.get(f"links_pendentes_13_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_13_0_{ano_sel}"] = False

        if st.session_state.get(f"gatilho_modal_13_1_{ano_sel}", False):
            modal_aviso_link("13.1", st.session_state.get(f"links_pendentes_13_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_13_1_{ano_sel}"] = False

# =============================================================================
        # QUESITO 13.0 • TOTALMENTE INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q13_0_{ano_sel}", border=True):
            with st.expander("📌 Quesito 13.0 - Existência de Aterro", expanded=True):
                st.subheader("13.0 • Aterro de Resíduos Sólidos Urbanos")
                st.write("**Existe aterro para os resíduos sólidos urbanos (lixo doméstico e limpeza urbana) no município?**")
                
                d130 = res_data.get("13.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""}) or {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                opc130 = ["Selecione...", "Sim", "Não"]
                v_salvo_130 = d130.get("valor", "Selecione...")
                if v_salvo_130 not in opc130: v_salvo_130 = "Selecione..."
                evidencia_130_salva = d130.get("link", "")

                def cb_130():
                    lnk = st.session_state.get(f"l130_in_{ano_sel}", evidencia_130_salva).strip()
                    val = st.session_state.get(f"r130_in_{ano_sel}", v_salvo_120)
                    pts = 0.0
                    
                    save_resp("13.0", val, float(pts), lnk)
                    res_data["13.0"] = {"valor": val, "pontos": float(pts), "link": lnk}
                    
                    # Limpeza condicional lógica (se Não, limpa o 13.1 no banco)
                    if val == "Não":
                        save_resp("13.1", "[]", -110.0, "")
                        res_data["13.1"] = {"valor": "[]", "pontos": -110.0, "link": ""}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_130_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_130_salva or ""):
                        st.session_state[f"links_pendentes_13_0_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_13_0_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    st.radio("Selecione uma opção (13.0):", options=opc130, index=opc130.index(v_salvo_130), key=f"r130_in_{ano_sel}", on_change=cb_130)
                with col2:
                    lk130 = st.text_area("Link/Evidência (13.0):", value=evidencia_130_salva, key=f"l130_in_{ano_sel}", on_change=cb_130, height=100)
                    if lk130: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk130 or "")]))

                st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto 13.0: 0.0 pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("13.0", res_data, ano_sel)

        # =============================================================================
        # QUESITO 13.1 • TOTALMENTE INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q13_1_{ano_sel}", border=True):
            with st.expander("📌 Quesito 13.1 - Características do Aterro", expanded=True):
                st.subheader("13.1 • Lógica de Penalidade e Recuperação")
                st.write("**Assinale as características do local de destinação final dos resíduos sólidos urbanos do município (aterro):**")
                
                d131 = res_data.get("13.1", {"valor": "[]", "pontos": -110.0, "link": ""}) or {"valor": "[]", "pontos": -110.0, "link": ""}
                v_salvo_131 = d131.get("valor", "[]")
                evidencia_131_salva = d131.get("link", "")
                
                opts131 = [
                    "Local da instalação foi planejado", "Capacidade do local é definida", 
                    "Há desenvolvimento de células individuais", "Impermeabilização do solo", 
                    "Total gestão do chorume", "Total gestão dos gases", 
                    "Aplicação diária de camadas intermediárias e finais - cobertura do solo", 
                    "Há compactação dos resíduos", "Há proteção vegetal (manutenção do paisagismo sobre as células de resíduos)", 
                    "Há desenvolvimento e manutenção das vias de acesso do aterro", "Há cercas/muros ao redor do local do aterro", 
                    "Há controle de acesso ao local do aterro", "Controle total do quantitativo de resíduos que entram no aterro", 
                    "Controle total da procedência dos resíduos que entram no aterro", "Controle total da composição dos resíduos que entram no aterro", 
                    "Não há coleta de resíduos por catadores dentro do aterro", "Não há comércio de resíduos dentro do aterro", 
                    "Não há presença de animais domésticos e/or animais silvestres (urubus, garças, etc.)", 
                    "Não há odores nem presença de moscas", "Não há queima de resíduos dentro do aterro", 
                    "Conhecimento da data provável de fechamento do aterro", "Previsão de gerenciamento do aterro pós-fechamento", 
                    "Outros"
                ]

                def cb_131():
                    sel = []
                    pts = -110.0
                    for idx, opt in enumerate(opts131):
                        if st.session_state.get(f"ck_131_{idx}_{ano_sel}", False):
                            sel.append(opt)
                            if opt != "Outros":
                                pts += 5.0
                                
                    pts = max(-110.0, min(0.0, pts))
                    lnk = st.session_state.get(f"l131_in_{ano_sel}", evidencia_131_salva).strip()
                    val = str(sel)
                    
                    save_resp("13.1", val, float(pts), lnk)
                    res_data["13.1"] = {"valor": val, "pontos": float(pts), "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_131_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_131_salva or ""):
                        st.session_state[f"links_pendentes_13_1_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_13_1_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    texto_seguro_131 = str(v_salvo_131) if v_salvo_131 not in ["", "[]"] else ""
                    for idx, opt in enumerate(opts131):
                        st.checkbox(opt, value=opt in texto_seguro_131, key=f"ck_131_{idx}_{ano_sel}", on_change=cb_131)
                with col2:
                    lk131 = st.text_area("Link/Evidência (13.1):", value=evidencia_131_salva, key=f"l131_in_{ano_sel}", on_change=cb_131, height=150)
                    if lk131: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk131 or "")]))

                # Recalcula a métrica de penalidade em tempo real na tela para feedback
                pts_exibido_131 = -110.0
                for idx, opt in enumerate(opts131):
                    if st.session_state.get(f"ck_131_{idx}_{ano_sel}", False) and opt != "Outros":
                        pts_exibido_131 += 5.0
                pts_exibido_131 = max(-110.0, min(0.0, pts_exibido_131))
                
                st.markdown(f"<span style='color:{'#28a745' if pts_exibido_131 == 0 else '#dc3545'}; font-weight:bold;'>📊 Impacto 13.1: {pts_exibido_131:.1f} pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("13.1", res_data, ano_sel)

        # =============================================================================
        # GATILHOS DOS MODAIS AUTOMÁTICOS • GRUPO 14 (TODOS TOTALMENTE INDEPENDENTES)
        # =============================================================================
        if st.session_state.get(f"gatilho_modal_14_0_{ano_sel}", False):
            modal_aviso_link("14.0", st.session_state.get(f"links_pendentes_14_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_14_0_{ano_sel}"] = False

        if st.session_state.get(f"gatilho_modal_14_1_{ano_sel}", False):
            modal_aviso_link("14.1", st.session_state.get(f"links_pendentes_14_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_14_1_{ano_sel}"] = False

        if st.session_state.get(f"gatilho_modal_14_2_{ano_sel}", False):
            modal_aviso_link("14.2", st.session_state.get(f"links_pendentes_14_2_{ano_sel}", []))
            st.session_state[f"gatilho_modal_14_2_{ano_sel}"] = False

        if st.session_state.get(f"gatilho_modal_14_3_{ano_sel}", False):
            modal_aviso_link("14.3", st.session_state.get(f"links_pendentes_14_3_{ano_sel}", []))
            st.session_state[f"gatilho_modal_14_3_{ano_sel}"] = False
# =============================================================================
        # QUESITO 14.0 • TOTALMENTE INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q14_0_{ano_sel}", border=True):
            with st.expander("📌 Quesito 14.0 - Pontos de Descarte Irregular", expanded=True):
                st.subheader("14.0 • Existência de Descarte Irregular")
                st.write("**Existem pontos de descarte irregular de lixo no município?**")
                
                d140 = res_data.get("14.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""}) or {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                opc140 = ["Selecione...", "Sim – -30 (perde 30 pontos)", "Não – 00"]
                v_salvo_140 = d140.get("valor", "Selecione...")
                if v_salvo_140 not in opc140: v_salvo_140 = "Selecione..."
                evidencia_140_salva = d140.get("link", "")

                def cb_140():
                    lnk = st.session_state.get(f"l140_in_{ano_sel}", evidencia_140_salva).strip()
                    val = st.session_state.get(f"r140_in_{ano_sel}", v_salvo_140)
                    pts = -30.0 if "Sim" in val else 0.0
                    
                    save_resp("14.0", val, float(pts), lnk)
                    res_data["14.0"] = {"valor": val, "pontos": float(pts), "link": lnk}
                    
                    if "Não" in val:
                        save_resp("14.1", "", 0.0, "")
                        res_data["14.1"] = {"valor": "", "pontos": 0.0, "link": ""}
                        save_resp("14.2", "", 0.0, "")
                        res_data["14.2"] = {"valor": "", "pontos": 0.0, "link": ""}
                        save_resp("14.3", "[]", 0.0, "")
                        res_data["14.3"] = {"valor": "[]", "pontos": 0.0, "link": ""}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_140_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_140_salva or ""):
                        st.session_state[f"links_pendentes_14_0_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_14_0_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    st.radio("Selecione uma opção (14.0):", options=opc140, index=opc140.index(v_salvo_140), key=f"r140_in_{ano_sel}", on_change=cb_140)
                with col2:
                    lk140 = st.text_area("Link/Evidência (14.0):", value=evidencia_140_salva, key=f"l140_in_{ano_sel}", on_change=cb_140, height=100)
                    if lk140: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk140 or "")]))

                v_f140 = st.session_state.get(f"r140_in_{ano_sel}", v_salvo_140)
                pts_exibido_140 = -30.0 if "Sim" in v_f140 else 0.0
                st.markdown(f"<span style='color:{'#dc3545' if pts_exibido_140 < 0 else '#28a745'}; font-weight:bold;'>📊 Impacto 14.0: {pts_exibido_140:.1f} pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("14.0", res_data, ano_sel)

        # =============================================================================
        # QUESITO 14.1 • TOTALMENTE INDEPENDENTE (Com Link/Evidência adicionado)
        # =============================================================================
        with st.container(key=f"bloco_isolado_q14_1_{ano_sel}", border=True):
            with st.expander("📌 Quesito 14.1 - Quantidade de Pontos", expanded=True):
                st.subheader("14.1 • Quantidade Identificada")
                st.write("**Informe a quantidade de pontos identificados:**")
                
                d141 = res_data.get("14.1", {"valor": "", "pontos": 0.0, "link": ""}) or {"valor": "", "pontos": 0.0, "link": ""}
                v_salvo_141 = d141.get("valor", "")
                evidencia_141_salva = d141.get("link", "")

                def cb_141():
                    val = st.session_state.get(f"t141_in_{ano_sel}", v_salvo_141).strip()
                    lnk = st.session_state.get(f"l141_in_{ano_sel}", evidencia_141_salva).strip()
                    
                    save_resp("14.1", val, 0.0, lnk)
                    res_data["14.1"] = {"valor": val, "pontos": 0.0, "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_141_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_141_salva or ""):
                        st.session_state[f"links_pendentes_14_1_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_14_1_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    st.text_area("Quantidade de pontos (14.1):", value=v_salvo_141, key=f"t141_in_{ano_sel}", on_change=cb_141, height=100)
                with col2:
                    lk141 = st.text_area("Link/Evidência (14.1):", value=evidencia_141_salva, key=f"l141_in_{ano_sel}", on_change=cb_141, height=100)
                    if lk141: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk141 or "")]))

                st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto 14.1: 0.0 pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("14.1", res_data, ano_sel)

        # =============================================================================
        # QUESITO 14.2 • TOTALMENTE INDEPENDENTE (Com Link/Evidência adicionado)
        # =============================================================================
        with st.container(key=f"bloco_isolado_q14_2_{ano_sel}", border=True):
            with st.expander("📌 Quesito 14.2 - Endereço dos Locais", expanded=True):
                st.subheader("14.2 • Localização do Descarte Irregular")
                st.write("**Informe o endereço dos locais identificados:**")
                
                d142 = res_data.get("14.2", {"valor": "", "pontos": 0.0, "link": ""}) or {"valor": "", "pontos": 0.0, "link": ""}
                v_salvo_142 = d142.get("valor", "")
                evidencia_142_salva = d142.get("link", "")

                def cb_142():
                    val = st.session_state.get(f"t142_in_{ano_sel}", v_salvo_142).strip()
                    lnk = st.session_state.get(f"l142_in_{ano_sel}", evidencia_142_salva).strip()
                    
                    save_resp("14.2", val, 0.0, lnk)
                    res_data["14.2"] = {"valor": val, "pontos": 0.0, "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_142_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_142_salva or ""):
                        st.session_state[f"links_pendentes_14_2_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_14_2_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    st.text_area("Endereço dos locais (14.2):", value=v_salvo_142, key=f"t142_in_{ano_sel}", on_change=cb_142, height=100)
                with col2:
                    lk142 = st.text_area("Link/Evidência (14.2):", value=evidencia_142_salva, key=f"l142_in_{ano_sel}", on_change=cb_142, height=100)
                    if lk142: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk142 or "")]))

                st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto 14.2: 0.0 pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("14.2", res_data, ano_sel)

        # =============================================================================
        # QUESITO 14.3 • TOTALMENTE INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q14_3_{ano_sel}", border=True):
            with st.expander("📌 Quesito 14.3 - Ações de Combate", expanded=True):
                st.subheader("14.3 • Ações Promovidas pela Prefeitura")
                st.write("**Assinale as ações promovidas pela Prefeitura para combater o descarte irregular de lixo no ano:**")
                
                d143 = res_data.get("14.3", {"valor": "[]", "pontos": 0.0, "link": ""}) or {"valor": "[]", "pontos": 0.0, "link": ""}
                v_salvo_143 = d143.get("valor", "[]")
                evidencia_143_salva = d143.get("link", "")
                
                opts143 = {
                    "Campanhas de conscientização – 05": 5.0, 
                    "Mobilização de grupos de bairro – 05": 5.0, 
                    "Retirada dos resíduos sólidos por caminhões – 05": 5.0, 
                    "Sinalização no local sobre a proibição de descarte naquele local – 05": 5.0, 
                    "Plantio de árvores em áreas que não deveriam receber lixo ou entulho – 05": 5.0, 
                    "Notificações e multas aos responsáveis – 05": 5.0
                }

                def cb_143():
                    sel = []
                    pts = 0.0
                    for opt, p_val in opts143.items():
                        if st.session_state.get(f"ck_143_{list(opts143.keys()).index(opt)}_{ano_sel}", False):
                            sel.append(opt)
                            pts += p_val
                            
                    lnk = st.session_state.get(f"l143_in_{ano_sel}", evidencia_143_salva).strip()
                    val = str(sel)
                    
                    save_resp("14.3", val, float(pts), lnk)
                    res_data["14.3"] = {"valor": val, "pontos": float(pts), "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_143_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_143_salva or ""):
                        st.session_state[f"links_pendentes_14_3_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_14_3_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    texto_seguro_143 = str(v_salvo_143) if v_salvo_143 not in ["", "[]"] else ""
                    for opt in opts143.keys():
                        st.checkbox(opt, value=opt in texto_seguro_143, key=f"ck_143_{list(opts143.keys()).index(opt)}_{ano_sel}", on_change=cb_143)
                with col2:
                    lk143 = st.text_area("Link/Evidência (14.3):", value=evidencia_143_salva, key=f"l143_in_{ano_sel}", on_change=cb_143, height=100)
                    if lk143: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk143 or "")]))

                pts_exibido_143 = 0.0
                for opt, p_val in opts143.items():
                    if st.session_state.get(f"ck_143_{list(opts143.keys()).index(opt)}_{ano_sel}", False):
                        pts_exibido_143 += p_val
                        
                st.markdown(f"<span style='color:#28a745; font-weight:bold;'>📊 Impacto 14.3: {pts_exibido_143:.1f} pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("14.3", res_data, ano_sel)

        # =============================================================================
        # QUESITO 15.0 • TOTALMENTE INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q15_0_{ano_sel}", border=True):
            with st.expander("📌 Quesito 15.0 - Entidade Reguladora", expanded=True):
                st.subheader("15.0 • Definição de Entidade Responsável")
                st.write("**O Município definiu a entidade responsável pela regulação e fiscalização dos serviços públicos de saneamento básico?**")
                
                d150 = res_data.get("15.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""}) or {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                opc150 = ["Selecione...", "Sim – 02", "Não – 00"]
                v_salvo_150 = d150.get("valor", "Selecione...")
                if v_salvo_150 not in opc150: v_salvo_150 = "Selecione..."
                evidencia_150_salva = d150.get("link", "")

                def cb_150():
                    lnk = st.session_state.get(f"l150_in_{ano_sel}", evidencia_150_salva).strip()
                    val = st.session_state.get(f"r150_in_{ano_sel}", v_salvo_150)
                    pts = 2.0 if "Sim" in val else 0.0
                    
                    save_resp("15.0", val, float(pts), lnk)
                    res_data["15.0"] = {"valor": val, "pontos": float(pts), "link": lnk}
                    
                    if "Não" in val:
                        save_resp("15.1", "[]", 0.0, "")
                        res_data["15.1"] = {"valor": "[]", "pontos": 0.0, "link": ""}
                        for subq in ["15.1.1", "15.1.2", "15.1.3", "15.1.4"]:
                            save_resp(subq, "", 0.0, "")
                            res_data[subq] = {"valor": "", "pontos": 0.0, "link": ""}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_150_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_150_salva or ""):
                        st.session_state[f"links_pendentes_15_0_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_15_0_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    st.radio("Selecione uma opção (15.0):", options=opc150, index=opc150.index(v_salvo_150), key=f"r150_in_{ano_sel}", on_change=cb_150)
                with col2:
                    lk150 = st.text_area("Link/Evidência (15.0):", value=evidencia_150_salva, key=f"l150_in_{ano_sel}", on_change=cb_150, height=100)
                    if lk150: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk150 or "")]))

                v_f150 = st.session_state.get(f"r150_in_{ano_sel}", v_salvo_150)
                pts_exibido_150 = 2.0 if "Sim" in v_f150 else 0.0
                st.markdown(f"<span style='color:#28a745; font-weight:bold;'>📊 Impacto 15.0: {pts_exibido_150:.1f} pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("15.0", res_data, ano_sel)

        # =============================================================================
        # QUESITO 15.1 • TOTALMENTE INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q15_1_{ano_sel}", border=True):
            with st.expander("📌 Quesito 15.1 - Serviços Regulados", expanded=True):
                st.subheader("15.1 • Serviços com Entidade Responsável")
                st.write("**Assinale quais os serviços que possuem entidade responsável pela regulação e fiscalização:**")
                
                d151 = res_data.get("15.1", {"valor": "[]", "pontos": 0.0, "link": ""}) or {"valor": "[]", "pontos": 0.0, "link": ""}
                v_salvo_151 = d151.get("valor", "[]")
                evidencia_151_salva = d151.get("link", "")
                
                opts151 = {
                    "Abastecimento de água potável: – 01": 1.0, 
                    "Esgotamento sanitário: – 01": 1.0, 
                    "Limpeza urbana e manejo de resíduos sólidos: – 01": 1.0, 
                    "Drenagem e manejo das águas pluviais urbanas: – 00": 0.0
                }

                def cb_151():
                    sel = []
                    pts = 0.0
                    for opt, p_val in opts151.items():
                        if st.session_state.get(f"ck_151_{list(opts151.keys()).index(opt)}_{ano_sel}", False):
                            sel.append(opt)
                            pts += p_val
                            
                    lnk = st.session_state.get(f"l151_in_{ano_sel}", evidencia_151_salva).strip()
                    val = str(sel)
                    
                    save_resp("15.1", val, float(pts), lnk)
                    res_data["15.1"] = {"valor": val, "pontos": float(pts), "link": lnk}
                    
                    # Limpezas cirúrgicas condicionais no banco
                    if "Abastecimento de água potável: – 01" not in sel:
                        save_resp("15.1.1", "", 0.0, "")
                        res_data["15.1.1"] = {"valor": "", "pontos": 0.0, "link": ""}
                    if "Esgotamento sanitário: – 01" not in sel:
                        save_resp("15.1.2", "", 0.0, "")
                        res_data["15.1.2"] = {"valor": "", "pontos": 0.0, "link": ""}
                    if "Limpeza urbana e manejo de resíduos sólidos: – 01" not in sel:
                        save_resp("15.1.3", "", 0.0, "")
                        res_data["15.1.3"] = {"valor": "", "pontos": 0.0, "link": ""}
                    if "Drenagem e manejo das águas pluviais urbanas: – 00" not in sel:
                        save_resp("15.1.4", "", 0.0, "")
                        res_data["15.1.4"] = {"valor": "", "pontos": 0.0, "link": ""}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_151_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_151_salva or ""):
                        st.session_state[f"links_pendentes_15_1_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_15_1_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    texto_seguro_151 = str(v_salvo_151) if v_salvo_151 not in ["", "[]"] else ""
                    for opt in opts151.keys():
                        st.checkbox(opt, value=opt in texto_seguro_151, key=f"ck_151_{list(opts151.keys()).index(opt)}_{ano_sel}", on_change=cb_151)
                with col2:
                    lk151 = st.text_area("Link/Evidência (15.1):", value=evidencia_151_salva, key=f"l151_in_{ano_sel}", on_change=cb_151, height=100)
                    if lk151: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk151 or "")]))

                pts_exibido_151 = 0.0
                for opt, p_val in opts151.items():
                    if st.session_state.get(f"ck_151_{list(opts151.keys()).index(opt)}_{ano_sel}", False):
                        pts_exibido_151 += p_val
                        
                st.markdown(f"<span style='color:#28a745; font-weight:bold;'>📊 Impacto 15.1: {pts_exibido_151:.1f} pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("15.1", res_data, ano_sel)

        # =============================================================================
        # QUESITO 15.1.1 • TOTALMENTE INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q15_1_1_{ano_sel}", border=True):
            with st.expander("📌 Quesito 15.1.1 - Regulação de Água Potável", expanded=True):
                st.subheader("15.1.1 • Entidade de Água Potável")
                st.write("**Informe a entidade responsável pela regulação e fiscalização do abastecimento de água potável do município:**")
                
                d1511 = res_data.get("15.1.1", {"valor": "", "pontos": 0.0, "link": ""}) or {"valor": "", "pontos": 0.0, "link": ""}
                v_salvo_1511 = d1511.get("valor", "")
                evidencia_1511_salva = d1511.get("link", "")

                def cb_1511():
                    val = st.session_state.get(f"t1511_in_{ano_sel}", v_salvo_1511).strip()
                    lnk = st.session_state.get(f"l1511_in_{ano_sel}", evidencia_1511_salva).strip()
                    save_resp("15.1.1", val, 0.0, lnk)
                    res_data["15.1.1"] = {"valor": val, "pontos": 0.0, "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_1511_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_1511_salva or ""):
                        st.session_state[f"links_pendentes_15_1_1_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_15_1_1_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    st.text_area("Entidade responsável (15.1.1):", value=v_salvo_1511, key=f"t1511_in_{ano_sel}", on_change=cb_1511, height=100)
                with col2:
                    lk1511 = st.text_area("Link/Evidência (15.1.1):", value=evidencia_1511_salva, key=f"l1511_in_{ano_sel}", on_change=cb_1511, height=100)
                    if lk1511: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk1511 or "")]))

                st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto 15.1.1: 0.0 pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("15.1.1", res_data, ano_sel)

        # =============================================================================
        # QUESITO 15.1.2 • TOTALMENTE INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q15_1_2_{ano_sel}", border=True):
            with st.expander("📌 Quesito 15.1.2 - Regulação de Esgotamento", expanded=True):
                st.subheader("15.1.2 • Entidade de Esgotamento Sanitário")
                st.write("**Informe a entidade responsável pela regulação e fiscalização do esgotamento sanitário do município:**")
                
                d1512 = res_data.get("15.1.2", {"valor": "", "pontos": 0.0, "link": ""}) or {"valor": "", "pontos": 0.0, "link": ""}
                v_salvo_1512 = d1512.get("valor", "")
                evidencia_1512_salva = d1512.get("link", "")

                def cb_1512():
                    val = st.session_state.get(f"t1512_in_{ano_sel}", v_salvo_1512).strip()
                    lnk = st.session_state.get(f"l1512_in_{ano_sel}", evidencia_1512_salva).strip()
                    save_resp("15.1.2", val, 0.0, lnk)
                    res_data["15.1.2"] = {"valor": val, "pontos": 0.0, "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_1512_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_1512_salva or ""):
                        st.session_state[f"links_pendentes_15_1_2_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_15_1_2_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    st.text_area("Entidade responsável (15.1.2):", value=v_salvo_1512, key=f"t1512_in_{ano_sel}", on_change=cb_1512, height=100)
                with col2:
                    lk1512 = st.text_area("Link/Evidência (15.1.2):", value=evidencia_1512_salva, key=f"l1512_in_{ano_sel}", on_change=cb_1512, height=100)
                    if lk1512: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk1512 or "")]))

                st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto 15.1.2: 0.0 pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("15.1.2", res_data, ano_sel)

        # =============================================================================
        # QUESITO 15.1.3 • TOTALMENTE INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q15_1_3_{ano_sel}", border=True):
            with st.expander("📌 Quesito 15.1.3 - Regulação de Resíduos Sólidos", expanded=True):
                st.subheader("15.1.3 • Entidade de Limpeza Urbana e Resíduos")
                st.write("**Informe a entidade responsável pela regulação e fiscalização de limpeza urbana e manejo de resíduos sólidos do município:**")
                
                d1513 = res_data.get("15.1.3", {"valor": "", "pontos": 0.0, "link": ""}) or {"valor": "", "pontos": 0.0, "link": ""}
                v_salvo_1513 = d1513.get("valor", "")
                evidencia_1513_salva = d1513.get("link", "")

                def cb_1513():
                    val = st.session_state.get(f"t1513_in_{ano_sel}", v_salvo_1513).strip()
                    lnk = st.session_state.get(f"l1513_in_{ano_sel}", evidencia_1513_salva).strip()
                    save_resp("15.1.3", val, 0.0, lnk)
                    res_data["15.1.3"] = {"valor": val, "pontos": 0.0, "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_1513_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_1513_salva or ""):
                        st.session_state[f"links_pendentes_15_1_3_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_15_1_3_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    st.text_area("Entidade responsável (15.1.3):", value=v_salvo_1513, key=f"t1513_in_{ano_sel}", on_change=cb_1513, height=100)
                with col2:
                    lk1513 = st.text_area("Link/Evidência (15.1.3):", value=evidencia_1513_salva, key=f"l1513_in_{ano_sel}", on_change=cb_1513, height=100)
                    if lk1513: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk1513 or "")]))

                st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto 15.1.3: 0.0 pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("15.1.3", res_data, ano_sel)

        # =============================================================================
        # QUESITO 15.1.4 • TOTALMENTE INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q15_1_4_{ano_sel}", border=True):
            with st.expander("📌 Quesito 15.1.4 - Regulação de Águas Pluviais", expanded=True):
                st.subheader("15.1.4 • Entidade de Drenagem e Águas Pluviais")
                st.write("**Informe a entidade responsável pela regulação e fiscalização de drenagem e manejo das águas pluviais urbanas do município:**")
                
                d1514 = res_data.get("15.1.4", {"valor": "", "pontos": 0.0, "link": ""}) or {"valor": "", "pontos": 0.0, "link": ""}
                v_salvo_1514 = d1514.get("valor", "")
                evidencia_1514_salva = d1514.get("link", "")

                def cb_1514():
                    val = st.session_state.get(f"t1514_in_{ano_sel}", v_salvo_1514).strip()
                    lnk = st.session_state.get(f"l1514_in_{ano_sel}", evidencia_1514_salva).strip()
                    save_resp("15.1.4", val, 0.0, lnk)
                    res_data["15.1.4"] = {"valor": val, "pontos": 0.0, "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_1514_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_1514_salva or ""):
                        st.session_state[f"links_pendentes_15_1_4_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_15_1_4_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    st.text_area("Entidade responsável (15.1.4):", value=v_salvo_1514, key=f"t1514_in_{ano_sel}", on_change=cb_1514, height=100)
                with col2:
                    lk1514 = st.text_area("Link/Evidência (15.1.4):", value=evidencia_1514_salva, key=f"l1514_in_{ano_sel}", on_change=cb_1514, height=100)
                    if lk1514: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk1514 or "")]))

                st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto 15.1.4: 0.0 pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("15.1.4", res_data, ano_sel)

        # =============================================================================
        # QUESITO 16.0 • TOTALMENTE INDEPENDENTE
        # =============================================================================
        st.divider()
        st.header("16.0 Impressões Finais")

        with st.container(key=f"bloco_isolado_q16_0_{ano_sel}", border=True):
            with st.expander("📌 Quesito 16.0 - Impressões Finais", expanded=True):
                st.subheader("16.0 • Considerações Finais")
                st.write("**Deixe suas impressões finais sobre o preenchimento do questionário:**")
                
                # Resgate seguro utilizando a chave padrão ou a variante '_valor' se aplicável
                d160 = res_data.get("16.0_valor", {"valor": "", "pontos": 0.0, "link": ""}) or {"valor": "", "pontos": 0.0, "link": ""}
                v_salvo_160 = d160.get("valor", "")
                evidencia_160_salva = d160.get("link", "")

                def cb_160():
                    val = st.session_state.get(f"t160_in_{ano_sel}", v_salvo_160).strip()
                    lnk = st.session_state.get(f"l160_in_{ano_sel}", evidencia_160_salva).strip()
                    
                    # Salva a resposta de forma assíncrona
                    save_resp("16.0_valor", val, 0.0, lnk)
                    res_data["16.0_valor"] = {"valor": val, "pontos": 0.0, "link": lnk}
                    
                    # Validação e processamento do modal de links
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_160_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_160_salva or ""):
                        st.session_state[f"links_pendentes_16_0_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_16_0_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    st.text_area("Impressões Finais (16.0):", value=v_salvo_160, key=f"t160_in_{ano_sel}", on_change=cb_160, height=150)
                with col2:
                    lk160 = st.text_area("Link/Evidência (16.0):", value=evidencia_160_salva, key=f"l160_in_{ano_sel}", on_change=cb_160, height=150)
                    if lk160: 
                        st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk160 or "")]))

                st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto 16.0: 0.0 pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("16.0_valor", res_data, ano_sel)

        
    with aba_ext:
        st.header("📊 Dados Externos do Meio Ambiente")
        
        # A1: ICTEM
        st.markdown('<div class="externo-card">', unsafe_allow_html=True)
        st.subheader("A1 - ICTEM (Indicador de Coleta de Tratabilidade de Esgoto)- Dados da CETESB. Não sujeitos à validação. Fórmula de cálculo: Pontuação: se ICTEM >= 7,5 - 00 se 5,0 < ICTEM <= 7,5 - -50 (perde 50 pontos) se 2,5 < ICTEM <= 5,0 - -150 (perde 150 pontos) se ICTEM <= 2,5 - -200 (perde 200 pontos)")
        d_a1 = res_data.get("A1", {"valor": 10.0, "pontos": 0})
        v_a1 = st.number_input("Informe o ICTEM:", min_value=0.0, max_value=10.0, value=float(d_a1["valor"]), step=0.1, key=f"ext_a1_{ano_sel}")
        pts_a1 = 0
        if v_a1 >= 7.5: pts_a1 = 0
        elif 5.0 < v_a1 <= 7.5: pts_a1 = -50
        elif 2.5 < v_a1 <= 5.0: pts_a1 = -150
        else: pts_a1 = -200
        if v_a1 != float(d_a1["valor"]):
            save_resp("A1", v_a1, pts_a1, "Dados CETESB")
            st.rerun()
        st.write(f"**Pontuação:** {pts_a1}")
        st.markdown('</div>', unsafe_allow_html=True)

        # A2: IQR
        st.markdown('<div class="externo-card">', unsafe_allow_html=True)
        st.subheader("A2 - IQR (Índice de Qualidade de Aterro)- Dados da CETESB. Não sujeitos à avalidação. Fórmula de cálculo: Condições adequadas - 00 pontos Condições inadequadas - Rebaixar i-Amb 1 Faixa")
        d_a2 = res_data.get("A2", {"valor": "Condições adequadas", "pontos": 0})
        opc_a2 = ["Condições adequadas", "Condições inadequadas"]
        idx_a2 = opc_a2.index(d_a2["valor"]) if d_a2["valor"] in opc_a2 else 0
        v_a2 = st.selectbox("Utilização do IQR:", opc_a2, index=idx_a2, key=f"ext_a2_{ano_sel}")
        if v_a2 != d_a2["valor"]:
            save_resp("A2", v_a2, 0, "Dados CETESB")
            st.rerun()
        if v_a2 == "Condições inadequadas":
            st.warning("⚠️ Esta condição rebaixará o i-AMB em uma faixa no resultado final.")
        st.markdown('</div>', unsafe_allow_html=True)

        # A3: IQT
        st.markdown('<div class="externo-card">', unsafe_allow_html=True)
        st.subheader("A3 - IQT (Índice de Qualidade de Estações de Transbordo)Dados da CETESB. Não sujeitos à validação. Fórmula de cálculo: De 0,0 a 7,0 - Condições inadequadas De 7,1 a 10,0 - Condições adequadas Fórmula de cálculo: Condições adequadas - 00 pontos Condições inadequadas - -50 (perde 50 pontos)")
        d_a3 = res_data.get("A3", {"valor": 10.0, "pontos": 0})
        v_a3 = st.number_input("Informe o IQT:", min_value=0.0, max_value=10.0, value=float(d_a3["valor"]), step=0.1, key=f"ext_a3_{ano_sel}")
        pts_a3 = 0 if v_a3 > 7.0 else -50
        if v_a3 != float(d_a3["valor"]):
            save_resp("A3", v_a3, pts_a3, "Dados CETESB")
            st.rerun()
        st.write(f"**Status:** {'Adequado' if v_a3 > 7.0 else 'Inadequado'}")
        st.write(f"**Pontuação:** {pts_a3}")
        st.markdown('</div>', unsafe_allow_html=True)

        # --- QUESITO A4.1 ---
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        st.subheader("QUESITO A4.1")
        st.write("**Informe quais dados foram enviados ao SINISA:**")
        st.caption("Dados do SINISA. Não sujeitos à validação.")

        # Busca dados salvos ou define o padrão limpo de segurança
        dA41 = res_data.get("A4.1", {"valor": "[]", "pontos": 0.0, "link": ""}) or {"valor": "[]", "pontos": 0.0, "link": ""}

        col1, col2 = st.columns([1, 2])

        with col1:
            # Definição das opções baseadas no enunciado
            optsA41 = [
                "Abastecimento de água e esgotamento sanitário",
                "Limpeza urbana e manejo de resíduos sólidos",
                "Drenagem e manejo de águas pluviais urbanas"
            ]
    
            selA41 = []
            ptsA41 = 0.0 # Não sujeito à validação/pontuação ativa
            texto_salvo_A41 = str(dA41["valor"])
    
            # Renderiza as caixas de seleção (Iniciam marcadas 'True' se o banco estiver vazio, conforme o ☒ do enunciado)
            for i, txt in enumerate(optsA41):
                # Se houver histórico, respeita o histórico. Se for a primeira vez, inicia como True (marcado)
                valor_inicial = txt in texto_salvo_A41 if dA41["valor"] != "[]" else True
        
                if st.checkbox(txt, value=valor_inicial, key=f"qA41_opt_{i}_{ano_sel}"):
                    selA41.append(txt)

            st.metric(label="Pontuação", value=f"{ptsA41:.1f} pts")

        with col2:
            # Campo para inserção de link ou comprovante de envio ao SINISA
            lA41 = st.text_area("Link/Evidência (A4.1):", value=dA41.get("link", ""), key=f"lA41_evid_unique_{ano_sel}", height=120)

        # Salva as alterações se o usuário marcar/desmarcar algo ou editar o link
        if str(selA41) != dA41["valor"] or lA41 != dA41["link"]:
            save_resp("A4.1", str(selA41), float(ptsA41), lA41)
            st.rerun()

        bloco_comentarios("A4.1", res_data)
        st.markdown('</div>', unsafe_allow_html=True)

        # A4.1.1: Saneamento (SINISA)
        st.markdown('<div class="externo-card">', unsafe_allow_html=True)
        st.subheader("A4.1.1 - Abastecimento e Esgotamento (SINISA)")
        
        # Água
        d_agua = res_data.get("A4.1.1_agua", {"valor": 0.0, "pontos": 0})
        p_agua = st.number_input("% Percentual de população atendida com abastecimento de água:", 0.0, 100.0, float(d_agua["valor"]), key=f"ext_agua_{ano_sel}")
        pts_agua = 0
        if p_agua == 100: pts_agua = 20
        elif 99 < p_agua < 100: pts_agua = ((p_agua - 99) / 1 * 10) + 10
        elif 90 < p_agua <= 99: pts_agua = (p_agua - 90) / 9 * 10
        
        # Exibe a pontuação atualizada na tela
        st.markdown(f"**Pontuação obtida:** `{pts_agua:.2f} / 20.0 pts`")
        
        if p_agua != float(d_agua["valor"]):
            save_resp("A4.1.1_agua", p_agua, pts_agua, "SINISA")
            st.rerun()
            
        st.write("---") # Divisor simples entre subquestões
            
        # Perdas
        d_perda = res_data.get("A4.1.1_perdas", {"valor": 0.0, "pontos": 0})
        p_perda = st.number_input("% Percentual de perdas na distribuição de água:", 0.0, 100.0, float(d_perda["valor"]), key=f"ext_perda_{ano_sel}")
        pts_perda = 0
        if p_perda == 0: pts_perda = 0
        elif 0 < p_perda <= 10: pts_perda = (p_perda / 10) * (-5)
        elif 10 < p_perda <= 20: pts_perda = ((p_perda - 10) / 10 * (-2)) - 5
        else: pts_perda = -10
        
        # Exibe o impacto de perda (penalidade) na tela de forma direta
        if pts_perda < 0:
            st.markdown(f"⚠️ **Penalidade aplicada (Perdas):** :red[{pts_perda:.2f} pts]")
        else:
            st.markdown(f"**Penalidade aplicada (Perdas):** `0.00 pts (Sem perdas)`")
            
        if p_perda != float(d_perda["valor"]):
            save_resp("A4.1.1_perdas", p_perda, pts_perda, "SINISA")
            st.rerun()

        st.write("---")

        # Esgoto Coleta
        d_esg = res_data.get("A4.1.1_esgoto", {"valor": 0.0, "pontos": 0})
        p_esg = st.number_input("% Percentual de população atendida com coleta de esgoto:", 0.0, 100.0, float(d_esg["valor"]), key=f"ext_esg_{ano_sel}")
        pts_esg = 0
        if p_esg == 100: pts_esg = 20
        elif 90 < p_esg < 100: pts_esg = ((p_esg - 90) / 10 * 10) + 10
        elif 80 < p_esg <= 90: pts_esg = (p_esg - 80) / 10 * 10
        
        st.markdown(f"**Pontuação obtida:** `{pts_esg:.2f} / 20.0 pts`")
        
        if p_esg != float(d_esg["valor"]):
            save_resp("A4.1.1_esgoto", p_esg, pts_esg, "SINISA")
            st.rerun()

        st.write("---")

        # Tratamento Esgoto
        d_trat = res_data.get("A4.1.1_trat", {"valor": 0.0, "pontos": 0})
        p_trat = st.number_input("% Índice de tratamento de esgoto:", 0.0, 100.0, float(d_trat["valor"]), key=f"ext_trat_{ano_sel}")
        pts_trat = 0
        if p_trat == 100: pts_trat = 20
        elif 90 < p_trat < 100: pts_trat = ((p_trat - 90) / 10 * 10) + 10
        elif 80 < p_trat <= 90: pts_trat = (p_trat - 80) / 10 * 10
        
        st.markdown(f"**Pontuação obtida:** `{pts_trat:.2f} / 20.0 pts`")
        
        if p_trat != float(d_trat["valor"]):
            save_resp("A4.1.1_trat", p_trat, pts_trat, "SINISA")
            st.rerun()
            
        st.write("---")
            
        # Esgoto Tratado / Água Consumida
        d_trat_c = res_data.get("A4.1.1_trat_cons", {"valor": 0.0, "pontos": 0})
        p_trat_c = st.number_input("% Índice de esgoto tratado referido à água consumida:", 0.0, 100.0, float(d_trat_c["valor"]), key=f"ext_trat_c_{ano_sel}")
        pts_trat_c = 0
        if p_trat_c == 100: pts_trat_c = 30
        elif 90 < p_trat_c < 100: pts_trat_c = ((p_trat_c - 90) / 10 * 10) + 10
        elif 80 < p_trat_c <= 90: pts_trat_c = (p_trat_c - 80) / 10 * 10
        
        st.markdown(f"**Pontuação obtida:** `{pts_trat_c:.2f} / 30.0 pts`")
        
        if p_trat_c != float(d_trat_c["valor"]):
            save_resp("A4.1.1_trat_cons", p_trat_c, pts_trat_c, "SINISA")
            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

        # A4.1.2: Resíduos Coleta
        st.markdown('<div class="externo-card">', unsafe_allow_html=True)
        st.subheader("A4.1.2 - Coleta de Resíduos (SINISA)")
        d_col_res = res_data.get("A4.1.2_coleta", {"valor": 0.0, "pontos": 0})
        p_col_res = st.number_input("% Cobertura coleta domiciliar (Pop. Total):", 0.0, 100.0, float(d_col_res["valor"]), key=f"ext_col_res_{ano_sel}")
        pts_col_res = 0
        if p_col_res == 100: pts_col_res = 20
        elif 99 < p_col_res < 100: pts_col_res = ((p_col_res - 99) / 1 * 10) + 10
        elif 90 < p_col_res <= 99: pts_col_res = (p_col_res - 90) / 9 * 10
        
        st.markdown(f"**Pontuação obtida:** `{pts_col_res:.2f} / 20.0 pts`")
        
        if p_col_res != float(d_col_res["valor"]):
            save_resp("A4.1.2_coleta", p_col_res, pts_col_res, "SINISA")
            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

        # A4.1.3: Massa Resíduos
        st.markdown('<div class="externo-card">', unsafe_allow_html=True)
        st.subheader("A4.1.3 - Massa de Resíduos (SINISA)")
        
        # Massa Dia
        d_m_dia = res_data.get("A4.1.3_massa_dia", {"valor": 1.5, "pontos": 0})
        m_dia = st.number_input("Massa coletada de resíduos sólidos da população urbana por dia (em kg/hab/dia):", 0.0, 10.0, float(d_m_dia["valor"]), key=f"ext_m_dia_{ano_sel}")
        pts_m_dia = 0
        if m_dia > 1: pts_m_dia = 0
        elif 0.99 < m_dia <= 1: pts_m_dia = ((1 - m_dia) / 0.01 * 2) + 1
        elif 0.90 < m_dia <= 0.99: pts_m_dia = ((0.99 - m_dia) / 0.09 * 3) + 5
        elif 0.70 < m_dia <= 0.90: pts_m_dia = ((0.90 - m_dia) / 0.2 * 2) + 7
        else: pts_m_dia = 10
        
        st.markdown(f"**Pontuação obtida:** `{pts_m_dia:.2f} / 10.0 pts`")
        
        if m_dia != float(d_m_dia["valor"]):
            save_resp("A4.1.3_massa_dia", m_dia, pts_m_dia, "SINISA")
            st.rerun()

        st.write("---")

        # Massa Ano (Recicláveis)
        d_m_ano = res_data.get("A4.1.3_massa_ano", {"valor": 0.0, "pontos": 0})
        m_ano = st.number_input("Massa recuperada per capita de materiais recicláveis em relação a população urbana (em kg/hab/ano):", 0.0, 500.0, float(d_m_ano["valor"]), key=f"ext_m_ano_{ano_sel}")
        pts_m_ano = 0
        if m_ano > 73: pts_m_ano = 12
        elif 36.5 < m_ano <= 73: pts_m_ano = ((m_ano - 36.5) / 36.5 * 2) + 5
        elif 20 < m_ano <= 36.5: pts_m_ano = ((m_ano - 20) / 16.5 * 2) + 3
        elif 8 < m_ano <= 20: pts_m_ano = (m_ano - 8) / 12 * 3
        
        st.markdown(f"**Pontuação obtida:** `{pts_m_ano:.2f} / 12.0 pts`")
        
        if m_ano != float(d_m_ano["valor"]):
            save_resp("A4.1.3_massa_ano", m_ano, pts_m_ano, "SINISA")
            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

        # --- QUESITO A4.1.4 ---
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        st.subheader("QUESITO A4.1.4")
        st.write("**Dados sobre drenagem e/ou manejo de águas pluviais urbanas:**")
        st.caption("Dados do SINISA. Não sujeitos à validação.")

        # Busca dados salvos ou define o padrão limpo de segurança
        dA414 = res_data.get("A4.1.4", {"valor": "0.0|0.0|0.0", "pontos": 0.0, "link": ""}) or {"valor": "0.0|0.0|0.0", "pontos": 0.0, "link": ""}

        # Tenta recuperar os 3 valores salvos na string "taxa1|taxa2|taxa3"
        try:
            t_pav, t_red, p_risco = map(float, dA414["valor"].split("|"))
        except:
            t_pav, t_red, p_risco = 0.0, 0.0, 0.0

        col1, col2 = st.columns([1, 2])

        with col1:
            v_pav = st.number_input(
                "Taxa de cobertura de pavimentação e meio-fio (%):", 
                min_value=0.0, max_value=100.0, value=t_pav, step=0.1, key=f"qA414_pav_{ano_sel}"
            )

            v_red = st.number_input(
            "Taxa de cobertura de vias públicas com redes/canais subterrâneos (%):", 
            min_value=0.0, max_value=100.0, value=t_red, step=0.1, key=f"qA414_red_{ano_sel}"
            )

            v_risco = st.number_input(
            "Parcela de domicílios em situação de risco de inundação (%):", 
            min_value=0.0, max_value=100.0, value=p_risco, step=0.1, key=f"qA414_risco_{ano_sel}"
            )

            ptsA414 = 0.0
            st.metric(label="Pontuação", value=f"{ptsA414:.1f} pts")

        with col2:
            lA414 = st.text_area("Link/Evidência (A4.1.4):", value=dA414.get("link", ""), key=f"lA414_evid_unique_{ano_sel}", height=180)

        valores_consolidados = f"{v_pav}|{v_red}|{v_risco}"

        if valores_consolidados != dA414["valor"] or lA414 != dA414["link"]:
            save_resp("A4.1.4", valores_consolidados, float(ptsA414), lA414)
            st.rerun()

        bloco_comentarios("A4.1.4", res_data)
        st.markdown('</div>', unsafe_allow_html=True)

        # --- QUESITO A5 ---
        st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
        st.subheader("QUESITO A5")
        st.write("**Foi instituída taxa / tarifa de cobrança dos serviços de limpeza urbana e manejo de resíduos sólidos?**")
        st.caption("Dados do SINISA. Não sujeitos à validação.")

        # Busca dados salvos ou define o padrão limpo de segurança
        dA5 = res_data.get("A5", {"valor": "Não foi informado", "pontos": 0.0, "link": ""}) or {"valor": "Não foi informado", "pontos": 0.0, "link": ""}

        col1, col2 = st.columns([1, 2])

        with col1:
            # Opções textuais conforme o enunciado do SINISA
            optsA5 = [
                "Sim",
                "Não",
                "Não foi informado"
            ]
    
            # Identifica o índice salvo para manter o estado do botão
            idx_salvoA5 = optsA5.index(dA5["valor"]) if dA5["valor"] in optsA5 else 2
    
            # Renderiza o botão de escolha única
            selA5 = st.radio("Selecione uma opção:", options=optsA5, index=idx_salvoA5, key=f"qA5_radio_unique_{ano_sel}")
    
            # Pontuação neutra (Não sujeito à validação)
            ptsA5 = 0.0
            st.metric(label="Pontuação", value=f"{ptsA5:.1f} pts")

        with col2:
            # Campo para links, decretos ou comprovantes de instituição da taxa
            lA5 = st.text_area("Link/Evidência (A5):", value=dA5.get("link", ""), key=f"lA5_evid_unique_{ano_sel}", height=120)

        # Salva no banco de dados se houver alteração na resposta ou na evidência
        if selA5 != dA5["valor"] or lA5 != dA5["link"]:
            save_resp("A5", selA5, float(ptsA5), lA5)
            st.rerun()

        bloco_comentarios("A5", res_data)
        st.markdown('</div>', unsafe_allow_html=True)

        # A6: Balança
        st.markdown('<div class="externo-card">', unsafe_allow_html=True)
        st.subheader("A6 - Utilização de Balança")
        d_a6 = res_data.get("A6", {"valor": "Não", "pontos": 0})
        opc_a6 = ["Sim", "Não", "Não foi informado"]
        idx_a6 = opc_a6.index(d_a6["valor"]) if d_a6["valor"] in opc_a6 else 1
        v_a6 = st.selectbox("Utiliza balança para pesagem rotineira?", opc_a6, index=idx_a6, key=f"ext_a6_{ano_sel}")
        pts_a6 = 5 if v_a6 == "Sim" else 0
        if v_a6 != d_a6["valor"]:
            save_resp("A6", v_a6, pts_a6, "SINISA")
            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

    with aba_graf:
        st.header("📈 Evolução e Desempenho")
        all_data = get_all_years_data()
        if all_data:
            anos_lista = sorted(all_data.keys())
            totais = [sum(item.get("pontos", 0) for k, item in all_data[ano].items() if not k.startswith("COM_")) for ano in anos_lista]
            fig = px.bar(x=anos_lista, y=totais, labels={'x':'Ano', 'y':'Pontuação'}, title="Pontuação Total por Ano")
            st.plotly_chart(fig)
        else:
            st.info("Ainda não há dados para gerar gráficos.")

def main():
    st.set_page_config(page_title="i-AMB Auditoria Ambiental", layout="wide")
    mostrar_formulario_amb()

if __name__ == "__main__":
    main()
