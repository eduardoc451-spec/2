import streamlit as st
import pandas as pd
import dataclasses
from datetime import date, datetime
from typing import List, Optional
import io
import json
import os

# Importações do ReportLab para a geração do PDF corporativo estruturado
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.pdfgen import canvas

# Importação para renderização de gráficos modernos
import plotly.express as px

# Configuração da página do Streamlit para Wide Mode
st.set_page_config(layout="wide")

# Caminho do banco de dados persistente local
ARQUIVO_BANCO = "banco_plano_acao.json"

@dataclasses.dataclass
class ActionItem:
    """Representa um item do Plano de Ação IEG-M com campos estratégicos avançados."""
    dimensao: str
    meta_estrategica: str
    indicador_desempenho: str
    acao: str
    descricao_acao: str
    fragilidades: str
    meta: str
    resultados_esperados: str
    integracao_planejamento_municipal: str
    alinhamento_ods: str
    data_inicio: Optional[date]
    data_conclusao: Optional[date]
    periodo_report: str
    responsavel: str
    forma_execucao: str
    evidencias: str
    links_evidencias: str  
    status: str

class NumberedCanvas(canvas.Canvas):
    """Canvas customizado para calcular dinamicamente o sumário e o número total de páginas."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_number(num_pages)
            super().showPage()
        super().save()

    def draw_page_number(self, page_count):
        if self._pageNumber == 1:
            return
        self.saveState()
        self.setFont("Helvetica", 9)
        self.setFillColor(colors.HexColor("#718096"))
        
        self.setStrokeColor(colors.HexColor("#E2E8F0"))
        self.setLineWidth(0.5)
        self.line(30, 40, letter[0] - 30, 40)
        
        texto_pagina = f"Página {self._pageNumber} de {page_count}"
        self.drawRightString(letter[0] - 30, 25, texto_pagina)
        self.drawString(30, 25, "Plano de Ação Executivo para o IEG-M — Controle Interno")
        self.restoreState()

def carregar_dados_locais():
    if os.path.exists(ARQUIVO_BANCO):
        try:
            with open(ARQUIVO_BANCO, "r", encoding="utf-8") as f:
                dados = json.load(f)
                for item in dados:
                    if item.get("data_inicio"):
                        item["data_inicio"] = datetime.strptime(item["data_inicio"], "%Y-%m-%d").date()
                    if item.get("data_conclusao"):
                        item["data_conclusao"] = datetime.strptime(item["data_conclusao"], "%Y-%m-%d").date()
                return dados
        except Exception as e:
            st.error(f"Erro ao carregar banco de dados local: {e}")
            
    return [
        {
            "dimensao": "i-Educ",
            "meta_estrategica": "ADEQUAÇÃO DO ESPAÇO POR ALUNO",
            "indicador_desempenho": "Área Física Disponível",
            "acao": "Levantamento técnico das salas",
            "descricao_acao": "Medição de todas as salas de aula para otimização de espaço físico.",
            "fragilidades": "Falta de engenheiro permanente na secretaria para homologar laudos.",
            "meta": "Atingir 100% das salas mapeadas",
            "resultados_esperados": "Redução em 15% de salas superlotadas",
            "integracao_planejamento_municipal": "Sim (PPA/LDO)",
            "alinhamento_ods": "ODS 4 - Educação de Qualidade",
            "data_inicio": date(2025, 2, 2),
            "data_conclusao": date(2025, 6, 30),
            "periodo_report": "Trimestral",
            "responsavel": "Misma/Patrícia",
            "forma_execucao": "Medição in loco",
            "evidencias": "Relatório fotográfico e laudos assinados",
            "links_evidencias": "",  
            "status": "🟢 Verde - Atendido"
        }
    ]

def salvar_dados_locais():
    try:
        dados_para_salvar = []
        for item in st.session_state.plano_acao_db:
            item_copia = item.copy()
            if isinstance(item_copia.get("data_inicio"), date):
                item_copia["data_inicio"] = item_copia["data_inicio"].strftime("%Y-%m-%d")
            if isinstance(item_copia.get("data_conclusao"), date):
                item_copia["data_conclusao"] = item_copia["data_conclusao"].strftime("%Y-%m-%d")
            dados_para_salvar.append(item_copia)
            
        with open(ARQUIVO_BANCO, "w", encoding="utf-8") as f:
            json.dump(dados_para_salvar, f, ensure_ascii=False, indent=4)
    except Exception as e:
        st.error(f"Erro ao gravar alterações no banco local: {e}")

def init_session_state():
    if "plano_acao_db" not in st.session_state:
        st.session_state.plano_acao_db = carregar_dados_locais()

def converter_para_df() -> pd.DataFrame:
    if not st.session_state.plano_acao_db:
        return pd.DataFrame(columns=[f.name for f in dataclasses.fields(ActionItem)])
    return pd.DataFrame(st.session_state.plano_acao_db)

def gerar_pdf_relatorio(df_dados, ano_selecionado):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=30, leftMargin=30, topMargin=40, bottomMargin=50)
    story = []
    
    styles = getSampleStyleSheet()
    
    style_capa_titulo = ParagraphStyle('CapaTitulo', parent=styles['Heading1'], fontSize=26, leading=32, textColor=colors.HexColor("#1A365D"), alignment=1, spaceBefore=20)
    style_capa_sub = ParagraphStyle('CapaSub', parent=styles['Normal'], fontSize=12, textColor=colors.HexColor("#4A5568"), alignment=1, spaceBefore=15)
    style_capa_meta = ParagraphStyle('CapaMeta', parent=styles['Normal'], fontSize=10, textColor=colors.gray, alignment=1, spaceBefore=180)
    
    style_h1 = ParagraphStyle('H1PDF', parent=styles['Heading1'], fontSize=18, leading=22, textColor=colors.HexColor("#1A365D"), spaceBefore=10, spaceAfter=15)
    style_dimensao = ParagraphStyle('DimPDF', parent=styles['Heading2'], fontSize=13, leading=16, textColor=colors.HexColor("#2B6CB0"), spaceBefore=18, spaceAfter=10)
    style_sumario_item = ParagraphStyle('SumItem', parent=styles['Normal'], fontSize=11, textColor=colors.HexColor("#2D3748"), spaceAfter=6)
    
    style_texto_bold = ParagraphStyle('TxtBold', parent=styles['Normal'], fontSize=8.5, leading=11, fontName="Helvetica-Bold")
    style_texto_normal = ParagraphStyle('TxtNorm', parent=styles['Normal'], fontSize=8.5, leading=11)

    # 1. CONSTRUÇÃO DA CAPA (Dimensões e Alinhamento Corrigidos)
    story.append(Spacer(1, 20))
    if os.path.exists("iegm.png"):
        try:
            logo = Image("iegm.png", width=380, height=180)
            logo.hAlign = 'CENTER'
            story.append(logo)
        except Exception:
            story.append(Paragraph("[Erro ao renderizar arquivo iegm.png]", style_capa_sub))
    else:
        story.append(Paragraph("<b>[Arquivo iegm.png não localizado na pasta do script]</b>", style_capa_sub))
        
    story.append(Spacer(1, 20))
    
    # Título Principal da Capa Dinâmico baseado no ano
    titulo_capa_dinamico = f"Plano de Ação — {ano_selecionado}" if ano_selecionado != "Todos" else "Plano de Ação — Plurianual"
    
    story.append(Paragraph(titulo_capa_dinamico, style_capa_titulo))
    story.append(Paragraph("Relatório Estratégico de Consolidação de Metas e Auditoria IEG-M", style_capa_sub))
    story.append(Paragraph(f"Emitido em: {date.today().strftime('%d/%m/%Y')} | Gestão Municipal Ativa", style_capa_meta))
    story.append(PageBreak())

    # 2. CONSTRUÇÃO DO SUMÁRIO
    story.append(Paragraph("SUMÁRIO ANALÍTICO", style_h1))
    story.append(Paragraph("Abaixo estão listadas as dimensões de controle do IEG-M avaliadas e consolidadas neste livrete executivo:", style_capa_sub))
    story.append(Spacer(1, 15))
    
    dimensoes_presentes = sorted(df_dados['dimensao'].unique())
    for d_item in dimensoes_presentes:
        texto_sumario = f"• Dimensão Temática: <b>{d_item.upper()}</b> ............................................................................................................ Ver Seção Detalhada"
        story.append(Paragraph(texto_sumario, style_sumario_item))
    
    story.append(PageBreak())

    # 3. DADOS DAS MATRIZES POR DIMENSÃO
    for dim in dimensoes_presentes:
        story.append(Paragraph(f"🏛️ DIMENSÃO: {dim.upper()}", style_dimensao))
        
        df_dim = df_dados[df_dados['dimensao'] == dim]
        for _, row in df_dim.iterrows():
            dados_tabela = [
                [Paragraph("Ação Prática:", style_texto_bold), Paragraph(str(row['acao']), style_texto_bold),
                 Paragraph("Status:", style_texto_bold), Paragraph(str(row['status']), style_texto_normal)],
                [Paragraph("Meta Estratégica:", style_texto_bold), Paragraph(str(row['meta_estrategica']), style_texto_normal),
                 Paragraph("Responsável:", style_texto_bold), Paragraph(str(row['responsavel']), style_texto_normal)],
                [Paragraph("Descrição:", style_texto_bold), Paragraph(str(row['descricao_acao']), style_texto_normal),
                 Paragraph("Prazo Final:", style_texto_bold), Paragraph(row['data_conclusao'].strftime('%d/%m/%Y') if row['data_conclusao'] else "Não definido", style_texto_normal)],
                [Paragraph("Fragilidades Mapeadas:", style_texto_bold), Paragraph(str(row['fragilidades']), style_texto_normal),
                 Paragraph("Resultados Esperados:", style_texto_bold), Paragraph(str(row['resultados_esperados']), style_texto_normal)]
            ]
            
            t = Table(dados_tabela, colWidths=[110, 170, 80, 190])
            t.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#F7FAFC")),
                ('ALIGN', (0,0), (-1,-1), 'LEFT'),
                ('VALIGN', (0,0), (-1,-1), 'TOP'),
                ('TEXTCOLOR', (0,0), (-1,-1), colors.black),
                ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor("#CBD5E0")),
                ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor("#E2E8F0")),
                ('TOPPADDING', (0,0), (-1,-1), 5),
                ('BOTTOMPADDING', (0,0), (-1,-1), 5),
            ]))
            story.append(t)
            story.append(Spacer(1, 10))
            
        story.append(Spacer(1, 10))

    doc.build(story, canvasmaker=NumberedCanvas)
    buffer.seek(0)
    return buffer

def mostrar_formulario_plano_acao():
    init_session_state()
    df_completo = converter_para_df()
    
    dimensoes_iegm = ["i-Cidade", "i-Educ", "i-Gov TI", "i-Amb", "i-Plan", "i-Fiscal", "i-Saúde"]
    lista_status = ["🟢 Verde - Atendido", "🟡 Amarelo - Em análise", "🔴 Vermelho - Pendente"]
    periodos_report = ["Mensal", "Bimestral", "Trimestral", "Semestral", "Anual"]

    # Filtro de Anos Fixos
    anos_fixos = ["Todos", "2025", "2026", "2027", "2028", "2029", "2030"]

    # CONTROLADORES DE FILTROS NA SIDEBAR
    st.sidebar.header("🔍 Filtros Operacionais")
    filtro_dim = st.sidebar.selectbox("Filtrar por Dimensão IEG-M", ["Todas"] + dimensoes_iegm)
    filtro_status = st.sidebar.selectbox("Filtrar por Status", ["Todos"] + lista_status)
    filtro_ano = st.sidebar.selectbox("Filtrar por Ano de Conclusão", anos_fixos)
    
    # MUDANÇA DO TÍTULO EM TELA CONFORME O FILTRO DE ANO SELECIONADO
    titulo_pagina_dinamico = f"🎯 Painel Estratégico do Plano de Ação — {filtro_ano}" if filtro_ano != "Todos" else "🎯 Painel Estratégico do Plano de Ação — Plurianual"
    st.title(titulo_pagina_dinamico)
    st.caption(f"💾 Banco de Dados Físico Ativo Localmente em: `{ARQUIVO_BANCO}`")
    
    df_filtrado = df_completo.copy()
    
    # Extração segura e isolada do ano
    df_filtrado['ano_conclusao_aux'] = df_filtrado['data_conclusao'].apply(lambda d: d.year if isinstance(d, date) else None)

    # Aplicação dos filtros do usuário
    if filtro_dim != "Todas":
        df_filtrado = df_filtrado[df_filtrado["dimensao"] == filtro_dim]
    if filtro_status != "Todos":
        df_filtrado = df_filtrado[df_filtrado["status"] == filtro_status]
    if filtro_ano != "Todos":
        df_filtrado = df_filtrado[df_filtrado["ano_conclusao_aux"] == int(filtro_ano)]

    # CARDS VISUAIS DE PERFORMANCE (KPIs)
    totais = df_filtrado["status"].value_counts() if not df_filtrado.empty else pd.Series()
    qtd_verde = totais.get("🟢 Verde - Atendido", 0)
    qtd_amarelo = totais.get("🟡 Amarelo - Em análise", 0)
    qtd_vermelho = totais.get("🔴 Vermelho - Pendente", 0)
    
    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.metric(label="📋 Total de Ações Filtradas", value=len(df_filtrado))
    with m2:
        st.markdown(f"<div style='border-left: 5px solid #28a745; padding-left: 10px;'><strong>Atendidas</strong><h2 style='color:#28a745; margin:0;'>{qtd_verde}</h2></div>", unsafe_allow_html=True)
    with m3:
        st.markdown(f"<div style='border-left: 5px solid #ffc107; padding-left: 10px;'><strong>Em Análise</strong><h2 style='color:#ffc107; margin:0;'>{qtd_amarelo}</h2></div>", unsafe_allow_html=True)
    with m4:
        st.markdown(f"<div style='border-left: 5px solid #dc3545; padding-left: 10px;'><strong>Pendentes (Riscos)</strong><h2 style='color:#dc3545; margin:0;'>{qtd_vermelho}</h2></div>", unsafe_allow_html=True)
        
    st.markdown("---")

    # BOTÃO DO RELATÓRIO PDF DINÂMICO
    if not df_filtrado.empty:
        pdf_data = gerar_pdf_relatorio(df_filtrado, filtro_ano)
        rotulo_botao_pdf = f"📄 Baixar Plano de Ação - Ano {filtro_ano} (PDF Oficial)" if filtro_ano != "Todos" else "📄 Baixar Plano de Ação - Plurianual (PDF Oficial)"
        st.download_button(
            label=rotulo_botao_pdf,
            data=pdf_data,
            file_name=f"Plano_de_Acao_IEGM_Ano_{filtro_ano}_{date.today().strftime('%Y%m%d')}.pdf",
            mime="application/pdf",
            type="primary",
            use_container_width=True
        )
    else:
        st.button("📄 Gerar Relatório PDF Consolidado (Filtros sem resultados)", disabled=True, use_container_width=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ABAS INTERNAS (Adicionadas as duas novas abas pedidas)
    tab_dashboard, tab_metas, tab_graficos, tab_cronograma, tab_cadastrar, tab_import_export = st.tabs([
        "📊 Banco de Dados & Edição Directa", 
        "🎯 Consolidação de Metas",
        "📊 Indicadores Visuais",
        "📅 Cronograma Plurianual",
        "➕ Nova Ação Estratégica", 
        "💾 Backups Externos (.CSV)"
    ])

    # ABA 1: GERENCIADOR E EDIÇÃO
    with tab_dashboard:
        st.markdown("### 🏛️ Matriz Completa de Linhas de Ação")
        if df_filtrado.empty:
            st.warning("Nenhum item localizado para os filtros selecionados.")
        else:
            for index, row in df_filtrado.iterrows():
                cor_status = "#28a745" if "Verde" in row["status"] else "#ffc107" if "Amarelo" in row["status"] else "#dc3545"
                
                with st.container(border=True):
                    c_cab1, c_cab2 = st.columns([6, 2])
                    with c_cab1:
                        st.markdown(f"""
                        <div style="display: flex; align-items: center; gap: 10px;">
                            <span style="background-color: {cor_status}; color: white; padding: 4px 12px; border-radius: 20px; font-size: 11px; font-weight: bold;">
                                {row['dimensao'].upper()}
                            </span>
                            <h3 style="margin: 0; padding: 0; font-size: 18px;">{row['acao']}</h3>
                        </div>
                        """, unsafe_allow_html=True)
                    with c_cab2:
                        st.markdown(f"<div style='text-align: right; font-weight: bold; color: {cor_status};'>{row['status']}</div>", unsafe_allow_html=True)
                    
                    st.markdown("<hr style='margin: 10px 0; border: 0; border-top: 1px solid rgba(255,255,255,0.1);'>", unsafe_allow_html=True)
                    
                    bloco_institucional, bloco_execucao, bloco_governanca = st.columns(3)
                    
                    with bloco_institucional:
                        st.markdown("##### 🔍 1. Alinhamento")
                        st.markdown(f"**🎯 Meta:** {row['meta_estrategica']}")
                        st.markdown(f"**📈 Indicador:** {row['indicador_desempenho']}")
                        st.markdown(f"**🇺🇳 ODS:** {row['alinhamento_ods']}")
                        
                    with bloco_execucao:
                        st.markdown("##### ⚙️ 2. Diagnóstico")
                        st.markdown(f"**📝 Descrição:** {row['descricao_acao']}")
                        st.markdown(f"**⚠️ Fragilidades:** <span style='color:#dc3545; font-weight:bold;'>{row['fragilidades']}</span>", unsafe_allow_html=True)
                        st.markdown(f"**🎯 Esperado:** {row['resultados_esperados']}")
                        
                    with bloco_governanca:
                        st.markdown("##### 📅 3. Governança")
                        st.markdown(f"**📅 Prazo Final:** {row['data_conclusao'].strftime('%d/%m/%Y') if row['data_conclusao'] else 'Não definido'}")
                        st.markdown(f"**👤 Responsável:** {row['responsavel']}")
                        
                        links_texto = str(row['links_evidencias']).strip()
                        if links_texto:
                            lista_links = [lnk.strip() for lnk in links_texto.split(",") if lnk.strip()]
                            for idx_link, link_url in enumerate(lista_links, start=1):
                                st.link_button(f"🔗 Evidência {idx_link}", link_url, use_container_width=True)
                    
                    with st.expander(f"🛠️ Editar / Remover Registro"):
                        with st.form(f"form_editar_{index}"):
                            ed_c1, ed_c2, ed_c3 = st.columns(3)
                            with ed_c1:
                                nova_dim = st.selectbox("Dimensão IEG-M", dimensoes_iegm, index=dimensoes_iegm.index(row['dimensao']))
                                nova_meta_est = st.text_input("Meta Estratégica", value=row['meta_estrategica'])
                                novo_ind = st.text_input("Indicador de Desempenho", value=row['indicador_desempenho'])
                                nova_acao = st.text_input("Título Prático da Ação", value=row['acao'])
                                novo_status = st.selectbox("Status Atual", lista_status, index=lista_status.index(row['status']))
                            with ed_c2:
                                nova_desc = st.text_area("Descrição da Operação", value=row['descricao_acao'])
                                novas_frag = st.text_area("Fragilidades Identificadas", value=row['fragilidades'])
                                nova_meta_alvo = st.text_input("Meta Alvo", value=row['meta'])
                                novo_resultados = st.text_input("Resultados Esperados", value=row['resultados_esperados'])
                            with ed_c3:
                                nova_dt_ini = st.date_input("Início da Execução", value=row['data_inicio'], format="DD/MM/YYYY", key=f"ini_{index}")
                                nova_dt_fim = st.date_input("Prazo Limite", value=row['data_conclusao'], format="DD/MM/YYYY", key=f"fim_{index}")
                                novo_report = st.selectbox("Período de Report", periodos_report, index=periodos_report.index(row['periodo_report']))
                                novo_resp = st.text_input("Responsável Principal", value=row['responsavel'])
                                nova_forma = st.text_input("Forma de Execução", value=row['forma_execucao'])
                                novas_evid = st.text_input("Evidências (Texto)", value=row['evidencias'])
                                novo_links_evid = st.text_input("🔗 Links das Evidências (Separados por vírgula)", value=row['links_evidencias'])
                                nova_integ = st.text_input("Integração Planejamento", value=row['integracao_planejamento_municipal'])
                                novo_ods = st.text_input("Alinhamento ODS", value=row['alinhamento_ods'])
                            
                            b_salvar, b_deletar = st.columns([5, 1])
                            with b_salvar:
                                btn_atualizar = st.form_submit_button("💾 Salvar Alterações", use_container_width=True, type="primary")
                            with b_deletar:
                                btn_excluir = st.form_submit_button("🗑️ Deletar", use_container_width=True)
                            
                            if btn_atualizar:
                                st.session_state.plano_acao_db[index] = {
                                    "dimensao": nova_dim, "meta_estrategica": nova_meta_est, "indicador_desempenho": novo_ind,
                                    "acao": nova_acao, "descricao_acao": nova_desc, "fragilidades": novas_frag, "meta": nova_meta_alvo,
                                    "resultados_esperados": novo_resultados, "integracao_planejamento_municipal": nova_integ,
                                    "alinhamento_ods": novo_ods, "data_inicio": nova_dt_ini, "data_conclusao": nova_dt_fim,
                                    "periodo_report": novo_report, "responsavel": novo_resp, "forma_execucao": nova_forma,
                                    "evidencias": novas_evid, "links_evidencias": novo_links_evid, "status": novo_status
                                }
                                salvar_dados_locais()
                                st.success("✨ Salvo com sucesso no banco!")
                                st.rerun()
                                
                            if btn_excluir:
                                st.session_state.plano_acao_db.pop(index)
                                salvar_dados_locais()
                                st.rerun()

    # NOVA ABA: CONSOLIDAÇÃO DE METAS E CONTAGEM
    with tab_metas:
        st.markdown("### 🎯 Metas Estratégicas e Volume de Ações")
        if df_filtrado.empty:
            st.info("Nenhum dado disponível para consolidar metas com os filtros atuais.")
        else:
            # Agrupamento por Meta Estratégica e contagem do número de ações
            df_agrupado_metas = df_filtrado.groupby("meta_estrategica").size().reset_index(name="Total de Ações")
            df_agrupado_metas = df_agrupado_metas.sort_values(by="Total de Ações", ascending=False)
            
            # Formatação visual com tabela interativa limpa
            st.dataframe(
                df_agrupado_metas, 
                column_config={
                    "meta_estrategica": st.column_config.TextColumn("🎯 Meta Estratégica"),
                    "Total de Ações": st.column_config.NumberColumn("📋 Total de Ações Associadas", format="%d")
                },
                use_container_width=True,
                hide_index=True
            )

    # NOVA ABA: GRÁFICO EM PIZZA DOS STATUS
    with tab_graficos:
        st.markdown("### 📊 Distribuição e Percentual por Status")
        if df_filtrado.empty:
            st.info("Insira dados ou limpe os filtros para visualizar os gráficos de performance.")
        else:
            # Preparação dos dados para o gráfico de pizza
            df_status_chart = df_filtrado["status"].value_counts().reset_index()
            df_status_chart.columns = ["Status", "Quantidade"]
            
            # Mapeamento estrito de cores corporativas para combinar com os status cadastrados
            color_map = {
                "🟢 Verde - Atendido": "#28a745",
                "🟡 Amarelo - Em análise": "#ffc107",
                "🔴 Vermelho - Pendente": "#dc3545"
            }
            
            fig = px.pie(
                df_status_chart, 
                values="Quantidade", 
                names="Status", 
                hole=0.4, # Estilo Donut moderno
                color="Status",
                color_discrete_map=color_map,
                labels={"Quantidade": "Ações"}
            )
            
            # Configuração das legendas externas e exibição de percentagem exata
            fig.update_traces(textposition='inside', textinfo='percent+value', hovertemplate="%{label}<br>Total: %{value} ações<br>Percentual: %{percent}")
            fig.update_layout(margin=dict(t=20, b=20, l=20, r=20), showlegend=True)
            
            # Divisão em duas colunas para dar suporte visual ao gráfico
            c_graf1, c_graf2 = st.columns([5, 3])
            with c_graf1:
                st.plotly_chart(fig, use_container_width=True)
            with c_graf2:
                st.markdown("##### Resumo Executivo da Janela Selecionada")
                total_acoes_graf = df_status_chart["Quantidade"].sum()
                for _, r_graf in df_status_chart.iterrows():
                    pct = (r_graf['Quantidade'] / total_acoes_graf) * 100
                    st.write(f"- **{r_graf['Status']}**: {r_graf['Quantidade']} ações ({pct:.1f}%)")

    # ABA 2: CRONOGRAMA VISUAL (Agora mapeada como ABA 4 na ordem sequencial)
    with tab_cronograma:
        st.markdown("### 📅 Cronograma de Prazos Críticos")
        if df_filtrado.empty:
            st.info("Insira ações ou mude as opções de filtros na lateral.")
        else:
            df_cronograma = df_filtrado.copy().sort_values(by="data_conclusao")
            for index, row in df_cronograma.iterrows():
                cor_alerta = "#28a745" if "Verde" in row["status"] else "#ffc107" if "Amarelo" in row["status"] else "#dc3545"
                st.markdown(f"""
                <div style="border-left: 4px solid {cor_alerta}; padding-left: 15px; margin-bottom: 20px; background-color: rgba(255,255,255,0.05); padding-top: 10px; padding-bottom: 10px; border-radius: 0 8px 8px 0;">
                    <span style="background-color: {cor_alerta}; color: white; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: bold;">{row['dimensao'].upper()}</span>
                    <h4 style="margin: 5px 0 2px 0;">{row['acao']}</h4>
                    <p style="margin: 0; font-size: 13px; color: #a3a3a3;"><strong>Responsável:</strong> {row['responsavel']}</p>
                    <div style="margin-top: 8px; font-size: 12px; font-weight: bold;">📅 Período Executivo: {row['data_inicio'].strftime('%d/%m/%Y')} até {row['data_conclusao'].strftime('%d/%m/%Y')}</div>
                </div>
                """, unsafe_allow_html=True)

    # ABA 3: CADASTRO COM SALVAMENTO LOCAL AUTOMÁTICO (Agora mapeada como ABA 5)
    with tab_cadastrar:
        st.markdown("### ⚡ Cadastro de Metas e Linhas de Ação Executivas")
        with st.form("form_novo_item_v15", clear_on_submit=True):
            c1, c2 = st.columns(2)
            with c1:
                dimensao_sel = st.selectbox("📌 Dimensão Vinculada (IEG-M)", dimensoes_iegm)
                meta_estrategica = st.text_input("🎯 Meta Estratégica")
            with c2:
                indicador_desempenho = st.text_input("📈 Indicador de Desempenho")
                alinhamento_ods = st.text_input("🇺🇳 Alinhamento ODS")

            c3, c4 = st.columns(2)
            with c3:
                acao = st.text_input("⚡ Título Prático da Ação")
                meta = st.text_input("🏁 Meta Alvo")
                resultados_esperados = st.text_input("🎯 Resultados Esperados")
                responsavel = st.text_input("👤 Responsável Principal")
            with c4:
                descricao_acao = st.text_area("📝 Descrição detalhada")
                fragilidades = st.text_area("⚠️ Fragilidades / Riscos Mapeados")

            c5, c6, c7 = st.columns(3)
            with c5:
                data_ini = st.date_input("📅 Início da Execução", value=date.today(), format="DD/MM/YYYY")
                data_fim = st.date_input("📅 Prazo Limite (Conclusão)", value=date.today(), format="DD/MM/YYYY")
            with c6:
                periodo_rep_sel = st.selectbox("🔄 Frequência de Report", periodos_report)
                integracao = st.selectbox("🗺️ Integração ao Planejamento", ["Sim (PPA/LDO/LOA)", "Parcial", "Não Integrado"])
            with c7:
                forma_execucao = st.text_input("⚙️ Forma de Execução")
                evidencias = st.text_input("📂 Comprovações/Evidências")
                links_evid_sel = st.text_input("🔗 Links das Evidências (Separados por vírgula)")
            
            status_sel = st.selectbox("🚥 Status Inicial da Demanda", lista_status)
            submit_btn = st.form_submit_button("🚀 Publicar Nova Ação no Plano", use_container_width=True)
            
            if submit_btn:
                if not acao or not responsavel:
                    st.error("❌ Os campos 'Título Prático da Ação' e 'Responsável' são obrigatórios.")
                else:
                    novo_item = {
                        "dimensao": dimensao_sel, "meta_estrategica": meta_estrategica, "indicador_desempenho": indicador_desempenho,
                        "acao": acao, "descricao_acao": descricao_acao, "fragilidades": fragilidades, "meta": meta,
                        "resultados_esperados": resultados_esperados, "integracao_planejamento_municipal": integracao,
                        "alinhamento_ods": alinhamento_ods, "data_inicio": data_ini, "data_conclusao": data_fim,
                        "periodo_report": periodo_rep_sel, "responsavel": responsavel, "forma_execucao": forma_execucao,
                        "evidencias": evidencias, "links_evidencias": links_evid_sel, "status": status_sel
                    }
                    st.session_state.plano_acao_db.append(novo_item)
                    salvar_dados_locais()
                    st.success("🎉 Item adicionado e persistido localmente no JSON!")
                    st.rerun()

    # ABA 4: INTEGRALIZAÇÃO EXTERNA (CSV) (Agora mapeada como ABA 6)
    with tab_import_export:
        st.markdown("### 📂 Central de Importação e Exportação de Backups")
        headers = [
            "dimensao", "meta_estrategica", "indicador_desempenho", "acao", "descricao_acao", 
            "fragilidades", "meta", "resultados_esperados", "integracao_planejamento_municipal", 
            "alinhamento_ods", "data_inicio", "data_conclusao", "periodo_report",
            "responsavel", "forma_execucao", "evidencias", "links_evidencias", "status"
        ]
        
        col_down, col_up = st.columns(2)
        with col_down:
            template_df = pd.DataFrame(columns=headers)
            csv_buffer = io.StringIO()
            template_df.to_csv(csv_buffer, sep="\t", index=False)
            st.download_button(label="📥 Baixar Template Estrutural (.CSV)", data=csv_buffer.getvalue(), file_name="layout_plano_acao.csv", mime="text/csv", use_container_width=True)
        with col_up:
            csv_backup = io.StringIO()
            converter_para_df().to_csv(csv_backup, sep="\t", index=False)
            st.download_button(label="📦 Exportar Backup de Segurança (.CSV)", data=csv_backup.getvalue(), file_name="backup_plano_acao.csv", mime="text/csv", use_container_width=True)
            
        st.markdown("---")
        uploaded_file = st.file_uploader("Upload em lote para substituição de registros", type=["csv"])
        if uploaded_file is not None:
            try:
                df_importado = pd.read_csv(uploaded_file, sep="\t")
                if set(headers).issubset(df_importado.columns):
                    if st.button("🚨 Substituir Base e Salvar Físico", use_container_width=True, type="primary"):
                        df_importado['data_inicio'] = pd.to_datetime(df_importado['data_inicio']).dt.date
                        df_importado['data_conclusao'] = pd.to_datetime(df_importado['data_conclusao']).dt.date
                        st.session_state.plano_acao_db = df_importado.to_dict(orient="records")
                        salvar_dados_locais()
                        st.success("🔥 Nova base activa sincronizada no arquivo JSON!")
                        st.rerun()
            except Exception as e:
                st.error(f"Erro no processamento da carga: {e}")

if __name__ == "__main__":
    mostrar_formulario_plano_acao()