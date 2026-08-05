import json
import sqlite3
import pandas as pd
import streamlit as st
from datetime import datetime

# --- DICIONÁRIO DE ESCOLAS E SUAS MODALIDADES ---
ESCOLAS_DATA = {
    "E.M. Alfredo Volpi": "Creche",
    "E.M. Almeida Júnior": "Creche",
    "E.M. Anita Malfatti": "Creche e Pré-Escola",
    "E.M. Antonio Federzoni": "Creche",
    "E.M. Antonio Muniz": "Creche",
    "E.M. Antônio Pacheco do Nascimento": "Pré-Escola",
    "E.M. Anísio Spínola Teixeira": "Ensino Fundamental",
    "E.M. Brigadeiro Roberto Brandini": "Ensino Fundamental",
    "E.M. Cândido Portinari": "Creche e Pré-Escola",
    "E.M. Carlos Drummond de Andrade": "Ensino Fundamental",
    "E.M. Castro Alves": "Creche e Pré-Escola",
    "E.M. Clarice Lispector": "Creche e Pré-Escola",
    "E.M. Cora Coralina": "Pré-Escola e Ensino Fundamental",
    "E.M. Dr. Francisco Morato": "Ensino Fundamental e EJAI",
    "E.M. Dr. Ulisses Silveira Guimarães": "Ensino Fundamental",
    "E.M. Edite Pereira de Arruda": "Pré-Escola",
    "E.M. Egon Schaden": "Ensino Fundamental",
    "E.M. Elba Nóbrega Sobral": "Pré-Escola",
    "E.M. Eliane Maria de Paula Oliveira": "Creche e Pré-Escola",
    "E.M. Érico Veríssimo": "Pré-Escola e Ensino Fundamental",
    "E.M. Fanny Goldberg": "Ensino Fundamental",
    "E.M. Fernando Pessoa": "Creche",
    "E.M. Giuliano Cecchettini": "Ensino Fundamental",
    "E.M. Graciliano Ramos": "Creche e Pré-Escola",
    "E.M. Isabel Lupianhes Romera Ryan": "Ensino Fundamental e EJAI",
    "E.M. João Guimarães Rosa": "Creche e Pré-Escola",
    "E.M. Leonardo da Vinci": "Pré-Escola",
    "E.M. Lima Barreto": "Creche e Pré-Escola",
    "E.M. Machado de Assis": "Ensino Fundamental",
    "E.M. Monteiro Lobato": "Creche e Pré-Escola",
    "E.M. Olavo Bilac": "Creche",
    "E.M. Padre Luiz Sérgio Pacheco do Nascimento": "Ensino Fundamental",
    "E.M. Paulo Freire": "Ensino Fundamental e EJAI",
    "E.M. Pref. Bezerra Sanches": "Ensino Fundamental",
    "E.M. Profa Hely Mara da Silva": "EJAI",
    "E.M. Profa Hosue Morita Aoki": "Ensino Fundamental",
    "E.M. Profa Lairce dos Santos Lupianha": "Ensino Fundamental",
    "E.M. Profa Tânia Fernandes": "Ensino Fundamental",
    "E.M. Radialista Jaime Gonçalves": "Creche e Pré-Escola",
    "E.M. Ruth Rocha": "Creche",
    "E.M. Sandra Regina de Oliveira": "Ensino Fundamental",
    "E.M. Sonia Regina Francisco de Oliveira": "Creche e Pré-Escola",
    "E.M. Tarsila do Amaral": "Pré-Escola",
    "E.M. Tatiana Belinky": "Creche e Pré-Escola",
    "E.M. Vanda Terezinha Nalin": "Ensino Fundamental",
    "E.M. Vereador Amado Pinto de Santana": "Pré-Escola",
    "E.M. Vereador Heitor Hartmann": "Creche",
    "E.M. Vinícius de Moraes": "Creche",
    "E.M. Zélia Gattai": "Creche e Pré-Escola",
}

# --- ESTRUTURA COMPLETA DO QUESTIONÁRIO DE VISTORIA ---
QUESTIONARIO_SECOES = {
    "1. ESTRUTURA ORGANIZACIONAL": [
        "1.1 Teve manutenção preventiva nos últimos 6 meses",
        "1.2 Teve manutenção corretiva nos últimos 6 meses",
        "1.3 Existe programação de alguma reforma estrutural",
        "1.4 Possuir Certificado do Corpo de Bombeiros com AVCB na validade?",
        "1.5 Validade dos Extintores",
    ],
    "2. ESTRUTURA FÍSICA E INSTALAÇÕES": [
        "2.1 Instituição com identificação externa visível",
        "2.2 Construção com mais de um pavimento, possuem rampas/escadas para circulação vertical",
        "2.3 Escadas dotadas de guarda-corpo, corrimão e piso antiderrapante",
        "2.4 Acesso independente, sendo um para a criança e outro para o serviço",
        "2.5 Fácil acesso e independente",
        "2.6 Pisos em bom estado de conservação",
        "2.7 Paredes sem umidades, pintadas e bom estado de conservação",
        "2.8 Teto sem infiltrações, telhados em bom estado de conservação",
        "2.9 Piso antiderrapante, de material resistente, de fácil limpeza, inclinação suficiente para escoamento e ralo escamoteado",
        "2.10 Teto e paredes lisos, de cor clara e de fácil higienização",
        "2.11 Instalações elétricas em bom estado de conservação, com fiação embutida e longe do acesso de crianças",
        "2.12 Pias em bom estado de conservação e sem vazamentos",
        "2.13 Lavatório para higienização das mãos, provido de sabão líquido, papel toalha e lixeira acionada de pedal e saco plástico",
        "2.14 Bancadas fixas ou móveis para auxílio das atividades",
        "2.15 Mesas e cadeiras em bom estado",
    ],
    "3. CLIMATIZAÇÃO E ILUMINAÇÃO": [
        "3.1 Estabelecimento com ventilação adequada",
        "3.2 Ventilação natural, com janelas em bom estado de conservação",
        "3.3 Ventilação artificial (ventilador)",
        "3.4 Limpeza dos filtros (possuem registros e atualizados)",
        "3.5 Áreas iluminadas naturally ou artificialmente",
        "3.6 Nas chuvas, as salas de aula estão protegidas contra a água",
    ],
    "4. SALA DE ATIVIDADES EDUCATIVAS, UNIFORME E EQUIPAMENTOS": [
        "4.1 Salas de atividades em quantidade suficiente para atender as diferentes turmas inscritas",
        "4.2 Possui acesso à internet",
        "4.3 O material didático está atualizado e utilizado periodicamente",
        "4.4 O uniforme foi distribuído de acordo com os tamanhos e há o controle da quantidade excedente",
        "4.5 Condição de armazenamento dos uniformes excedentes se houver",
    ],
    "5. ÁREA DE RECREAÇÃO E SANITÁRIOS": [
        "5.1 Brinquedos estão em bom estado de conservação",
        "5.2 Possui pátio de recreação",
        "5.3 Brinquedos e materiais de esporte são Utilizados e em bom estado",
        "5.4 Existem instalações sanitárias em números suficientes e separados por sexo, dotadas de lavatório, chuveiro e vaso sanitário, com dimensões e altura adequadas",
        "5.5 Sanitários são providos de sabão líquido, toalhas descartáveis, papel higiênico e lixeira acionada por pedal",
        "5.6 Sanitários com acesso à deficiente e em bom estado tanto para o masculino quanto ao feminino",
        "5.7 Instalações sanitárias atendem às normas de edificação quanto ao piso, paredes, teto e instalações hidráulicas/elétricas",
        "5.8 A higienização dos banheiros é frequente",
    ],
    "6. COZINHA / REFEITÓRIO / DESPENSA": [
        "6.1 Cozinha, refeitório e despensa atendem às normas sanitárias quanto à edificação",
        "6.2 Acesso à cozinha e despensa é restrito aos funcionários do local",
        "6.3 Bebedouro em bom estado de higiene e conservação, providos de copos descartáveis",
        "6.4 Móveis, equipamentos e utensílios são suficientes e estão em bom estado de conservação",
        "6.5 Fogão possui coifa ou outro sistema de exaustão",
        "6.6 Pias adequadas em número suficiente e sifão na sua canalização",
        "6.7 Tanque adequado e exclusivo para lavagem das panelas e utensílios",
        "6.8 Utensílios e talheres são guardados em armários impermeáveis com portas ou local protegido de poeira e insetos",
        "6.9 Alimentos são acondicionados de forma adequada em freezer, geladeiras, prateleiras, armários e estrados",
        "6.10 Mantêm controle rigoroso dos alimentos quanto ao registro, procedência, manipulação, validade e conservação",
        "6.11 Carnes são fracionadas em porções para uso diário, embaladas em sacos plásticos transparentes e rotuladas",
        "6.12 Funcionários fazem uso de EPI’s, jaleco ou avental de cor clara e proteção nos cabelos",
        "6.13 Lixo acondicionado em recipiente lavável, com saco plástico e tampa. Mantido afastado de alimentos e utensílios",
    ],
    "7. DEPÓSITO DE MATERIAL DE LIMPEZA (DML)": [
        "7.1 Local adequado, restrito e ventilado para guarda do material de limpeza (DML) com identificação",
        "7.2 Tanque exclusivo para esta atividade",
        "7.3 Armários para guarda de produtos e materiais",
    ],
    "8. ABASTECIMENTO DE ÁGUA": [
        "8.1 Sistema público",
        "8.2 Poço artesiano é protegido e distante de fontes de contaminação",
        "8.3 Reservatório de água possui registro de desinfecção por produtos químicos no mínimo de 6 em 6 meses",
        "8.4 Reservatórios sem rachaduras e tampados",
        "8.5 A quantidade e qualidade da água são satisfatórias",
        "8.6 Realiza monitoramento da qualidade da água",
        "8.7 Laudo de limpeza da Caixa D'água está em dia?",
    ],
    "9. LIXO": [
        "9.1 Recipiente para o lixo com tampa impermeável e revestido com saco plástico",
        "9.2 Acondicionamento e armazenamento adequado",
        "9.3 Destino adequado",
        "9.4 Há acúmulo de lixo, entulhos, poluição ambiental na área externa",
    ],
    "10. SANITIZAÇÃO DO AMBIENTE": [
        "10.1 Possui Atestado Técnico da realização dos processos de sanitização",
        "10.2 Possui registro dos processos de sanitização",
        "10.3 Possui controle periódico de pragas (insetos e roedores, etc.) com comprovante e registro",
        "10.4 A empresa que realiza este procedimento está cadastrada na Vigilância Sanitária",
    ],
}

# --- SEÇÕES ESPECÍFICAS PARA CRECHES ---
QUESTIONARIO_CRECHE = {
    "11. BERÇÁRIO": [
        "11.1 Atende as normas de edificação quanto a piso, paredes, teto e ventilação",
        "11.2 Tem dimensão adequada e comporta todos os berços mantendo-os afastados das paredes e entre si",
        "11.3 Móveis em condições de higiene e conservação",
        "11.4 Possui dormitório ou local exclusivo para repouso das crianças, limpo e arejado",
        "11.5 Possui berços em número igual ao de crianças atendidas e colchões revestidos com material impermeável",
        "11.6 Número de colchonetes igual ao de crianças inscritas, cobertas com capas impermeáveis, limpas e conservadas",
        "11.7 Vestiário adequado para uso exclusivo dos bebês (pia, vaso com tampa, bancada de banho, mesa de troca)",
        "11.8 Armários em bom estado e suficientes para a guarda de lençóis, roupas e pertences dos bebês",
        "11.9 Lençóis em número suficiente, íntegros, limpos e identificados para uso individual",
        "11.10 Toalha, sabonete, bucha, pente, escova, copo e mamadeira identificados para uso individual",
    ],
    "12. FRALDÁRIO": [
        "12.1 Local adequado com bancada para troca e higienização do bebê",
        "12.2 Lavatório com sabão líquido, toalha descartável e lixeira acionada por pedal",
    ],
    "13. LACTÁRIO": [
        "13.1 Armários adequados para guarda de mamadeira, leite, farinha, adoçante e outras matérias primas",
        "13.2 Geladeira de uso exclusivo para acondicionar leite e mamadeiras",
        "13.3 Após cada uso, os bicos e mamadeiras são submetidos à higienização e fervura",
        "13.4 Bancada exclusiva para o preparo de mamadeiras",
        "13.5 Mamadeiras acondicionadas em recipiente próprio, limpos e com tampa",
        "13.6 O espaço é isolado do trânsito de pessoas e das visitas",
        "13.7 Ventilação adequada e aberturas teladas",
    ],
}

def init_db():
    """Inicializa a tabela de vistorias estruturada no banco SQLite."""
    conn = sqlite3.connect("sistema_gestao.db")
    c = conn.cursor()
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS vistorias (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ano INTEGER,
            data_vistoria TEXT,
            tipo_local TEXT,
            nome_local TEXT,
            modalidade TEXT,
            auditor TEXT,
            status TEXT,
            resumo_apontamentos TEXT,
            dados_questionario TEXT
        )
    """
    )
    conn.commit()
    conn.close()

def salvar_vistoria(ano, data_vistoria, tipo_local, nome_local, modalidade, auditor, status, resumo_apontamentos, dados_questionario):
    """Salva a vistoria completa e o questionario em formato JSON."""
    conn = sqlite3.connect("sistema_gestao.db")
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO vistorias (ano, data_vistoria, tipo_local, nome_local, modalidade, auditor, status, resumo_apontamentos, dados_questionario)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
        (ano, data_vistoria, tipo_local, nome_local, modalidade, auditor, status, resumo_apontamentos, json.dumps(dados_questionario, ensure_ascii=False)),
    )
    conn.commit()
    conn.close()

def carregar_vistorias(ano):
    """Carrega o histórico de vistorias."""
    conn = sqlite3.connect("sistema_gestao.db")
    df = pd.read_sql_query("SELECT id, data_vistoria, tipo_local, nome_local, modalidade, auditor, status, resumo_apontamentos FROM vistorias WHERE ano = ? ORDER BY id DESC", conn, params=(ano,))
    conn.close()
    return df

def mostrar_painel_vistoria(year):
    init_db()
    st.markdown("## 🔍 Controle Interno — Módulo de Vistorias In Loco")
    st.caption(f"Exercício: **{year}**")

    tab1, tab2 = st.tabs(["📝 Novo Checklist de Vistoria", "📊 Painel & Histórico"])

    with tab1:
        st.subheader("Ficha de Fiscalização da Unidade")
        
        # --- CABEÇALHO DO FORMULÁRIO ---
        col1, col2 = st.columns(2)
        with col1:
            tipo_local = st.selectbox("Tipo de Local", ["Escola Municipal", "Equipamento Esportivo / Outro"])
            data_vistoria = st.date_input("Data da Vistoria", datetime.now())
            auditor = st.text_input("Auditor / Fiscal Responsável", placeholder="Ex: Maria Oliveira")

        with col2:
            if tipo_local == "Escola Municipal":
                nome_local = st.selectbox("Selecione a Unidade Escolar", list(ESCOLAS_DATA.keys()))
                modalidade = ESCOLAS_DATA[nome_local]
                st.info(f"🏫 **Modalidade:** {modalidade}")
            else:
                nome_local = st.text_input("Nome do Equipamento Esportivo / Local", placeholder="Ex: Ginásio de Esportes do Centro")
                modalidade = "Equipamento Esportivo"

            status = st.selectbox(
                "Status da Vistoria",
                [
                    "✅ Concluída (Regular)",
                    "⚠️ Concluída (Com Apontamentos)",
                    "❌ Irregularidade Grave",
                    "🟡 Em Andamento",
                ],
            )

        st.markdown("---")
        st.subheader("📋 Questionário Avaliativo")

        # Monta a estrutura de perguntas
        estrutura_perguntas = QUESTIONARIO_SECOES.copy()
        
        # Se for creche, inclui as seções de Berçário, Fraldário e Lactário
        if "Creche" in modalidade:
            st.warning("👶 Unidade do tipo Creche identificada: As seções 11 (Berçário), 12 (Fraldário) e 13 (Lactário) foram ativadas automaticamente.")
            estrutura_perguntas.update(QUESTIONARIO_CRECHE)

        respostas_questionario = {}

        # Renderização dinâmica das seções e perguntas
        for secao, itens in estrutura_perguntas.items():
            with st.expander(f"📌 {secao}", expanded=False):
                for idx, item in enumerate(itens):
                    st.markdown(f"**{item}**")
                    col_resp, col_obs = st.columns([1, 2])
                    
                    with col_resp:
                        status_item = st.radio(
                            "Situação:",
                            ["Adequado", "Parcialmente adequado", "Inadequado"],
                            key=f"rad_{secao}_{idx}",
                            horizontal=True,
                        )
                    with col_obs:
                        obs_item = st.text_input("Observações:", key=f"obs_{secao}_{idx}", placeholder="Detalhes ou inconformidades...")
                    
                    respostas_questionario[item] = {
                        "status": status_item,
                        "observacao": obs_item
                    }
                    st.markdown("<hr style='margin: 5px 0;'>", unsafe_allow_html=True)

        st.markdown("---")
        st.subheader("📌 Principais Apontamentos e Evidências")

        texto_padrao_apontamentos = (
            "Infiltrações, janelas que não fecham, caixa de distribuição de disjuntores abertos, "
            "Extintor de incêndio no chão, rampas inadequadas para acesso de crianças com deficiência, "
            "sem corrimãos duplos e piso tátil."
        )
        resumo_apontamentos = st.text_area(
            "Principais apontamentos registrados na unidade:",
            value=texto_padrao_apontamentos,
            height=100,
        )

        # Upload de Imagens / Evidências Fotográficas
        fotos_evidencia = st.file_uploader(
            "📷 Adicionar Fotos da Vistoria (Evidências Visual):",
            type=["png", "jpg", "jpeg"],
            accept_multiple_files=True,
        )

        if fotos_evidencia:
            st.write(f"🖼️ **{len(fotos_evidencia)} foto(s) anexada(s):**")
            cols_img = st.columns(min(len(fotos_evidencia), 4))
            for idx, foto in enumerate(fotos_evidencia):
                with cols_img[idx % 4]:
                    st.image(foto, caption=foto.name, use_column_width=True)

        st.markdown("---")
        if st.button("💾 Finalizar e Salvar Relatório de Vistoria", use_container_width=True):
            if not auditor:
                st.error("Por favor, preencha o nome do auditor responsável antes de salvar.")
            else:
                salvar_vistoria(
                    year,
                    data_vistoria.strftime("%d/%m/%Y"),
                    tipo_local,
                    nome_local,
                    modalidade,
                    auditor,
                    status,
                    resumo_apontamentos,
                    respostas_questionario,
                )
                st.balloons()
                st.success(f"Vistoria na unidade **{nome_local}** salva com sucesso no sistema!")

    with tab2:
        st.subheader("Histórico de Fiscalizações")
        df = carregar_vistorias(year)

        if df.empty:
            st.info(f"Nenhum relatório de vistoria cadastrado em {year}.")
        else:
            col_m1, col_m2, col_m3 = st.columns(3)
            col_m1.metric("Total de Vistorias", len(df))
            col_m2.metric("Regulares", len(df[df["status"].str.contains("Regular")]))
            col_m3.metric("Com Apontamentos/Irregularidades", len(df[df["status"].str.contains("Apontamentos|Irregularidade")]))

            st.markdown("---")
            st.dataframe(
                df,
                column_config={
                    "id": "ID",
                    "data_vistoria": "Data",
                    "tipo_local": "Tipo",
                    "nome_local": "Unidade / Local",
                    "modalidade": "Modalidade",
                    "auditor": "Auditor",
                    "status": "Status Geral",
                    "resumo_apontamentos": "Resumo de Inconformidades",
                },
                use_container_width=True,
                hide_index=True,
            )

def main():
    mostrar_painel_vistoria(datetime.now().year)

if __name__ == "__main__":
    main()