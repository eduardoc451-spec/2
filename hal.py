import json
import logging
import os
import re
import time
import plotly.graph_objects as go
import psycopg2
import psycopg2.extras
import streamlit as st

# ==============================================================================
# FUNÇÃO DE RENDERIZAÇÃO PARA O STREAMLIT
# ==============================================================================
def mostrar_chat_hal():
    st.title("🤖 HAL - Sistema de Diagnóstico TCESP")
    st.write("Conectado ao banco de dados PostgreSQL (Neon DB).")

    # Instancia o sistema HAL
    hal = SistemaHAL()

    # Seleção de ano e dimensão
    col1, col2 = st.columns(2)
    with col1:
        ano = st.number_input("Ano de Análise", min_value=2020, max_value=2026, value=2025)
    with col2:
        dimensao = st.selectbox("Dimensão", list(hal.questoes_por_dimensao.keys()))

    if st.button("Analisar Desempenho", type="primary"):
        nota = hal.puxar_nota_dimensao(dimensao, ano)
        st.metric(label=f"Nota na dimensão {dimensao} ({ano})", value=f"{nota:.2f}")

        fracos, penalidades = hal.analisar_pontos_fracos(ano, dimensao)

        if penalidades:
            st.error("⚠️ Penalidades Detectadas")
            for p in penalidades:
                st.write(f"- **[ID {p['id']}]** {p['pergunta']} (Penalidade: {p['penalidade']})")

        if fracos:
            st.warning("📉 Pontos com Déficit de Pontuação")
            for f in fracos:
                st.write(f"- **[ID {f['id']}]** Obtido: {f['obtido']} / Máx: {f['maximo']} (Déficit: {f['deficit']})")

# ==============================================================================
# CONFIGURAÇÃO DIRETA DO POSTGRESQL (NEON DB)
# ==============================================================================
DATABASE_URL = "postgresql://neondb_owner:npg_beMKhVR2N4wo@ep-divine-sky-awx1636y-pooler.c-12.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
# ==============================================================================


class SistemaHAL:

    def __init__(self):
        self.questoes_por_dimensao = {}
        self.pontuacoes_maximas_por_dimensao = {}
        # Mapeamento do nome da dimensão para a tabela correspondente no PostgreSQL
        self.mapeamento_tabelas = {
            "iCidade": "respostas_icidade",
            "iGov-Ti": "respostas_igov",
            "i-Amb": "respostas_iamb",
            "i-Plan": "respostas_iplan",
            "i-Fiscal": "respostas_ifiscal",
            "i-Educ": "respostas_ieduc",
            "i-Saude": "respostas_isaude",
        }
        self.carregar_dicionarios_globais()
        self.conn = self.inicializar_banco_postgres()

    def carregar_dicionarios_globais(self):
        # Dicionário unificado com as dimensões operacionais completas
        self.questoes_por_dimensao = {
            "iCidade": {
                "1.0": (
                    "Foi criada a Coordenadoria Municipal de Proteção e Defesa"
                    " Civil (COMPDEC) ou órgão similar responsável pela"
                    " execução, coordenação e mobilização de todas as ações de"
                    " defesa civil no município?"
                ),
                "1.3": (
                    "A COMPDEC ou órgão similar está associada ou subordinada a"
                    " qual secretaria/diretoria?"
                ),
                "1.4": (
                    "Os órgãos e entidades da administração pública municipal"
                    " atuam de forma sistêmica, articulados com a COMPDEC, nas"
                    " ações de prevenção, mitigação, preparação, resposta e"
                    " recuperação, de acordo com a Política Nacional de"
                    " Proteção e Defesa Civil (PNPDEC)?"
                ),
                "2.0": (
                    "Sobre treinamento e capacitação em Proteção e Defesa"
                    " Civil, a Prefeitura capacita seus agentes para ações"
                    " municipais de Defesa Civil?"
                ),
                "2.1": (
                    "Qual a data da última classificação dos agentes municipais"
                    " para ações de Defesa Civil?"
                ),
                "2.2": (
                    "A Prefeitura Municipal ofereceu cursos/treinamentos sobre"
                    " Proteção e Defesa Civil para qual público?"
                ),
                "3.0": (
                    "O Município realiza ações para estimular a participação de"
                    " entidades privadas, associações de voluntários, clubes de"
                    " serviços, organizações não governamentais e associações"
                    " de classe e comunitárias nas ações de proteção e defesa"
                    " civil?"
                ),
                "3.1.1": (
                    "Qual a data do último treinamento de associações de"
                    " voluntários?"
                ),
                "4.2": (
                    "A Carta Geotécnica de Suscetibilidade, Aptidão à"
                    " Urbanização e Risco consta no Plano Diretor, conforme"
                    " art. 42-A, §§ 1º, 2º e 3º, da Lei Federal nº 10.257, de 10"
                    " de julho de 2001?"
                ),
                "5.0": (
                    "O Município realizou, por conta própria, o mapeamento e"
                    " identificação das principais ameaças existentes em seu"
                    " território?"
                ),
                "5.1.1": (
                    "As secretarias setoriais realizam a fiscalização das"
                    " áreas de risco?"
                ),
                "5.2": (
                    "A população foi informada sobre todas as ameaças"
                    " identificadas pelo município?"
                ),
                "6.0": (
                    "A Secretaria responsável realizou vistorias em edificações"
                    " vulneráveis com o objetivo de identificar a necessidade de"
                    " intervenção preventiva nos imóveis?"
                ),
                "7.0": (
                    "O Município possui Plano de Contingência Municipal"
                    " (PLANCON) de Defesa Civil?"
                ),
                "7.1": (
                    "Foi elaborado um PLANCON específico para cada ameaça"
                    " identificada?"
                ),
                "7.2": (
                    "São realizados regularmente exercícios simulados para as"
                    " contingências previstas no PLANCON?"
                ),
                "7.3": "O Município possui sistema de alerta para desastres?",
                "7.4": (
                    "O Município dispõe de sinal, dispositivo ou sistema de"
                    " alarme para desastres?"
                ),
                "7.5": (
                    "Possui cadastro dos locais para abrigo da população em"
                    " situação de desastre junto à Coordenadoria Estadual de"
                    " Proteção e Defesa Civil (CEPDEC)?"
                ),
                "7.6": (
                    "O Município possui cadastro da lista de fornecedores para"
                    " coleta e distribuição de suprimentos de ajuda humanitária"
                    " para o caso de desastre?"
                ),
                "8.0": (
                    "O Município possui um canal de atendimento de emergência à"
                    " população para registro de ocorrências de desastres?"
                ),
                "8.1.1.1": "O telefone 199 tem atendimento 24 horas por dia?",
                "8.2": (
                    "O Município registra as ocorrências de Defesa Civil de"
                    " forma eletrônica?"
                ),
                "9.0": (
                    "O Município realizou estudo de avaliação da estrutura de"
                    " todas as escolas e unidades de saúde para garantir que, em"
                    " caso de desastre, esses locais estejam preparados para"
                    " abrigar e atender a população afetada?"
                ),
                "10.0": "O Município elaborou seu Plano de Mobilidade Urbana?",
                "11.1": (
                    "Foram estabelecidas metas de qualidade e desempenho para"
                    " o transporte público coletivo municipal?"
                ),
                "11.1.1": (
                    "As metas de qualidade e desempenho do transporte público"
                    " coletivo estão sendo atingidas?"
                ),
                "11.2": (
                    "Foi realizada pesquisa de satisfação dos usuários do"
                    " transporte público coletivo em 2025?"
                ),
                "12.1": (
                    "Informe o instrumento normativo, número e data da"
                    " publicação do transporte regulamentado."
                ),
                "12.1.3": (
                    "O Município fiscaliza regularmente o transporte remunerado"
                    " privado individual de passageiros (táxi por aplicativo)?"
                ),
                "14.0": (
                    "O Município adequou os calçamentos públicos para"
                    " acessibilidade das pessoas com deficiência e restrição de"
                    " mobilidade?"
                ),
                "15.0": (
                    "As vias públicas pavimentadas estão devidamente"
                    " sinalizadas (vertical e horizontalmente) de forma a"
                    " garantir condições adequadas de segurança na circulação?"
                ),
                "16.0": (
                    "Há manutenção adequada das vias públicas no Município?"
                ),
                "C1.1": (
                    "Indique os pontos de controle externos da auditoria ou"
                    " controle de metas vigentes."
                ),
            },
            "iGov-Ti": {
                "1.0": (
                    "A Prefeitura possui uma área ou setor que cuida de"
                    " Tecnologia da Informação e Comunicação (TIC)?"
                ),
                "1.1": (
                    "Informe a quantidade de funcionários concursados,"
                    " comissionados e estagiários no suporte e atendimento de"
                    " primeiro nível."
                ),
                "1.2": (
                    "A prefeitura municipal definiu formalmente as atribuições"
                    " do pessoal do setor de Tecnologia da Informação e"
                    " Comunicação (TIC)?"
                ),
                "1.3": (
                    "A prefeitura disponibilizou capacitação para o pessoal da"
                    " área de Tecnologia da Informação e Comunicação (TIC)?"
                ),
                "1.3.1": "Informe em quais áreas houve capacitação.",
                "1.4": (
                    "Nas licitações e contratos que tenham como soluções o uso"
                    " de TIC, houve participação formalizada do pessoal de TIC?"
                    " (Verba municipal)"
                ),
                "1.4.1": "Assinale as etapas que o pessoal de TIC participa.",
                "1.4.2": (
                    "Sobre softwares adquiridos/licenciados nos últimos 5"
                    " anos, foi realizada análise ou estudo prévio com a"
                    " participação de TIC?"
                ),
                "2.0": (
                    "A prefeitura municipal possui um PDTIC vigente que"
                    " estabeleça diretrizes e metas de atingimento no futuro?"
                ),
                "2.1": "Informe a página eletrônica (link na internet) do PDTIC.",
                "2.2": (
                    "O plano de TIC vigente contempla as metas operacionais"
                    " estratégicas municipais?"
                ),
                "2.3": "Qual a data da última atualização do PDTIC?",
                "3.0": (
                    "A Prefeitura dispõe de Política de Segurança da Informação"
                    " formalmente instituída e de cumprimento obrigatório?"
                ),
                "3.1": (
                    "A Prefeitura estabelece procedimentos e"
                    " responsabilidades quanto ao uso de TI (Termo de"
                    " Responsabilidade/Compromisso)?"
                ),
                "3.1.1": (
                    "O Termo de Responsabilidade/Compromisso dispõe sobre o uso"
                    " da assinatura eletrônica pelos funcionários?"
                ),
                "3.1.1.1": (
                    "Informe o tipo de assinatura eletrônica utilizada nos"
                    " documentos digitais."
                ),
                "3.2": (
                    "Os riscos de TIC são identificados de acordo com as normas"
                    " brasileiras da família ISO/IEC 27000?"
                ),
                "3.2.1": (
                    "As secretarias realizam a fiscalização das áreas de risco?"
                    " Informe quais normas ISO/IEC 27000 são utilizadas."
                ),
                "3.3": (
                    "Os riscos de TIC são identificados de acordo com as normas"
                    " da ABNT NBR ISO/IEC 31000?"
                ),
                "3.4": (
                    "A Prefeitura possui um Plano de Continuidade dos Serviços"
                    " de Tecnologia da Informação e Comunicação (TIC)?"
                ),
                "3.5": (
                    "A Prefeitura dispõe de política de cópias de segurança"
                    " (backup) formalmente instituída como norma obrigatória?"
                ),
                "3.6": "A Prefeitura possui inventário atualizado dos ativos de TIC?",
                "3.6.1": "Como é composta a base de ativos?",
                "4.0": (
                    "O município regulamentou a Lei de Acesso à Informação"
                    " (Lei Federal nº 12.527/2011)?"
                ),
                "4.1": (
                    "Informe o Instrumento normativo, Número e Data da"
                    " publicação (LAI)."
                ),
                "4.2": (
                    "Página eletrônica (link na internet) do instrumento"
                    " normativo da LAI."
                ),
                "5.0": (
                    "O município regulamentou a Lei sobre Eficiência Pública"
                    " (Governo Digital - Lei Federal nº 14.129/2021)?"
                ),
                "5.1": (
                    "Informe o Instrumento normativo, Número e Data da"
                    " publicação (Governo Digital)."
                ),
                "5.2": (
                    "Página eletrônica (link na internet) do instrumento"
                    " normativo (Governo Digital)."
                ),
                "5.3": (
                    "A Prefeitura implantou soluções digitais para trâmite de"
                    " processos administrativos?"
                ),
                "6.0": (
                    "A prefeitura mantém site na internet com informações"
                    " atualizadas?"
                ),
                "6.1": (
                    "O site eletrônico da prefeitura continha ferramenta de"
                    " pesquisa/busca interna de conteúdo?"
                ),
                "6.2": (
                    "O site possibilita o download de dados e informações em"
                    " formatos abertos e não proprietários?"
                ),
                "6.3": (
                    "O site disponibiliza as respostas a perguntas mais"
                    " frequentes da sociedade?"
                ),
                "6.4": (
                    "O site disponibiliza acessibilidade de conteúdo para"
                    " pessoas com deficiência?"
                ),
                "7.0": (
                    "A Prefeitura disponibiliza no site o Serviço de Informação"
                    " ao Cidadão (e-SIC)?"
                ),
                "7.1": "A solicitação por meio do e-SIC é simplificada?",
                "7.2": (
                    "O e-SIC apresenta possibilidade de acompanhamento da"
                    " solicitação?"
                ),
                "7.3": (
                    "Há necessidade de informar os motivos para a solicitação de"
                    " informações de interesse público?"
                ),
                "8.0": (
                    "A Prefeitura possui programas de computador (softwares)"
                    " para gestão de processos?"
                ),
                "8.1": (
                    "Os programas de computador (softwares) englobam quais"
                    " processos/setores?"
                ),
                "8.2": (
                    "Informe quais sistemas encontram-se integrados ao Sistema"
                    " de Contabilidade do município."
                ),
                "8.2.1": (
                    "Informe o nível de integração entre o Sistema da Dívida"
                    " Ativa e o de Contabilidade."
                ),
                "8.2.2": (
                    "Informe o nível de integração entre o Sistema de"
                    " Precatórios e o de Contabilidade."
                ),
                "8.3": (
                    "Assinale quais bases de dados encontram-se sob gestão"
                    " direta da Prefeitura (Risco de Perdas)."
                ),
                "8.4": (
                    "Assinale quais sistemas possuem controle de acesso à"
                    " informação."
                ),
                "9.0": "A Prefeitura ofereceu serviços de forma online?",
                "9.1": "Quais tipos de serviços são oferecidos online?",
                "9.2": (
                    "Quais as formas de atendimento à distância disponibilizadas"
                    " ao público pela Prefeitura?"
                ),
                "10.0": (
                    "A Prefeitura Municipal regulamentou o tratamento de dados"
                    " pessoais, inclusive nos meios digitais, segundo a LGPD"
                    " (Lei Federal nº 13.709/2018)?"
                ),
                "10.1": (
                    "Informe o instrumento normativo, número e data da"
                    " publicação."
                ),
                "10.2": "Informe a página eletrônica (link na internet).",
                "10.3": (
                    "Os contratos com os prestadores de serviços contêm"
                    " cláusulas de observância à LGPD?"
                ),
                "10.4": (
                    "A Prefeitura Municipal realizou mapeamento de dados (data"
                    " mapping)?"
                ),
                "10.5": (
                    "Foram adotadas medidas de segurança, técnicas e"
                    " administrativas para proteção dos dados pessoais?"
                ),
                "10.5.1": "Informe as medidas adotadas.",
                "11.0": (
                    "A Prefeitura Municipal designou um encarregado para as"
                    " operações de tratamento de dados pessoais?"
                ),
                "11.1": (
                    "Informe a página eletrônica que contenha a identidade e"
                    " as informações de contato do encarregado."
                ),
                "12.0": (
                    "Gostaria de registrar suas impressões, comentários e"
                    " sugestões a respeito do presente questionário?"
                ),
            },
            "i-Amb": {
                "1.0": (
                    "Existe estrutura organizacional instalada para tratar de"
                    " assuntos ligados ao Meio Ambiente Municipal?"
                ),
                "1.1": (
                    "Informe a disponibilidade de recursos humanos para"
                    " operacionalização dos assuntos ligados ao Meio Ambiente."
                ),
                "1.1.1": (
                    "Informe o detalhamento e informações sobre os recursos"
                    " humanos da área."
                ),
                "1.1.2": (
                    "A prefeitura realizou treinamento específico voltado ao"
                    " Meio Ambiente no ano de 2025?"
                ),
                "1.1.3": (
                    "Informe os cursos e treinamentos de educação ambiental"
                    " ofertados pela Secretaria de Meio Ambiente."
                ),
                "1.2": (
                    "Informe quais recursos foram disponibilizados para a"
                    " operacionalização das atividades de meio ambiente."
                ),
                "2.0": (
                    "O Município promove a participação em Programas de Educação"
                    " Ambiental?"
                ),
                "2.1": (
                    "Há programas ou ações de educação ambiental implementadas"
                    " na rede escolar municipal?"
                ),
                "3.0": (
                    "O Município promove estímulo a projetos e ações para o uso"
                    " racional de recursos naturais?"
                ),
                "3.1": (
                    "Assinale quais tipos de ações são realizadas para o uso"
                    " racional de recursos naturais."
                ),
                "4.0": (
                    "Há fiscalização da emissão de poluentes de combustíveis"
                    " fósseis (diesel) na frota municipal?"
                ),
                "5.0": (
                    "Existe contrato vigente para a prestação de serviços de"
                    " poda e corte de árvores, arbustos e outras plantas"
                    " lenhosas?"
                ),
                "5.1": (
                    "Informe o número do contrato e o respectivo prestador de"
                    " serviço."
                ),
                "5.2": (
                    "Qual a periodicidade definida para a realização de poda e"
                    " manutenção das árvores?"
                ),
                "5.2.1": (
                    "Informe a destinação final dada aos resíduos decorrentes"
                    " das podas de árvores."
                ),
                "5.3": (
                    "Houve capacitação específica para os responsáveis pela"
                    " execução da manutenção e poda de árvores?"
                ),
                "6.0": (
                    "O Município adota ações e medidas preventivas de"
                    " contingenciamento para períodos de estiagem?"
                ),
                "6.1": (
                    "Informe os tipos de ações e medidas preventivas que foram"
                    " executadas."
                ),
                "6.2": (
                    "Indique os setores envolvidos com ações específicas para a"
                    " provisão de água potável."
                ),
                "7.0": (
                    "Existe Plano Municipal ou Regional de Saneamento Básico"
                    " instituído e vigente?"
                ),
                "7.1": "Informe o instrumento normativo de aprovação do Plano.",
                "7.2": (
                    "Informe a página eletrônica (link na internet) para acesso"
                    " ao Plano."
                ),
                "7.3": (
                    "O Plano estabelece metas específicas de abastecimento de"
                    " água potável?"
                ),
                "7.3.1": (
                    "Informe detalhadamente as metas estabelecidas para o"
                    " abastecimento de água."
                ),
                "7.3.2": (
                    "Qual a data prevista para a universalização do"
                    " atendimento de abastecimento de água?"
                ),
                "7.4": (
                    "O Plano estabelece metas de coleta de esgoto sanitário?"
                ),
                "7.4.1": (
                    "Informe as metas estabelecidas para o serviço de coleta de"
                    " esgoto."
                ),
                "7.4.2": (
                    "Qual a data prevista para a universalização da coleta de"
                    " esgoto?"
                ),
                "7.5": (
                    "O Plano estabelece metas para o tratamento do esgoto"
                    " coletado?"
                ),
                "7.5.1": (
                    "Qual a data prevista para a universalização do tratamento"
                    " de esgoto?"
                ),
                "7.6": (
                    "O Plano contempla metas de drenagem e manejo de águas"
                    " pluviais urbanas?"
                ),
                "7.6.1": (
                    "Informe as metas estabelecidas voltadas à drenagem e"
                    " manejo de águas pluviais."
                ),
                "7.7": (
                    "O Município realiza o monitoramento e avaliação das ações"
                    " e metas de abastecimento de água e esgotamento"
                    " sanitário?"
                ),
                "7.7.1": (
                    "Informe de qual forma é realizado este monitoramento e"
                    " avaliação."
                ),
                "7.8": (
                    "Existe um cronograma formalizado de metas para o"
                    " saneamento básico?"
                ),
                "7.8.1": (
                    "As metas estabelecidas estão sendo cumpridas dentro do"
                    " prazo estipulado?"
                ),
                "7.8.1.1": (
                    "Informe os principais motivos que justificam o não"
                    " cumprimento das metas."
                ),
                "7.9": (
                    "O Plano apresenta previsão de áreas prioritárias ou"
                    " críticas para intervenções de abastecimento de água e"
                    " esgotamento sanitário?"
                ),
                "7.10": (
                    "Qual a data da última revisão realizada no Plano de"
                    " Saneamento Básico?"
                ),
                "8.0": (
                    "Existe Plano Municipal ou Regional de Gestão Integrada de"
                    " Resíduos Sólidos instituído?"
                ),
                "8.1": (
                    "Informe o instrumento normativo de aprovação do Plano de"
                    " Resíduos Sólidos."
                ),
                "8.2": (
                    "Informe a página eletrônica (link na internet) para acesso"
                    " ao Plano."
                ),
                "8.3": (
                    "O Plano apresenta a caracterização qualitativa e"
                    " quantitativa dos resíduos sólidos urbanos?"
                ),
                "8.3.1": (
                    "Informe a metodologia ou forma utilizada para a"
                    " caracterização dos resíduos."
                ),
                "8.4": (
                    "Existe um cronograma formalizado de metas para a gestão de"
                    " resíduos sólidos?"
                ),
                "8.4.1": (
                    "Informe as metas que foram formalmente estabelecidas sobre"
                    " os resíduos sólidos."
                ),
                "8.4.2": (
                    "O Município realiza o monitoramento e avaliação das ações"
                    " e metas deste Plano?"
                ),
                "8.4.2.1": (
                    "Informe de qual forma é realizado esse monitoramento e"
                    " avaliação."
                ),
                "8.4.3": (
                    "As metas estabelecidas estão sendo cumpridas dentro do"
                    " prazo estipulado?"
                ),
                "8.4.3.1": (
                    "Informe os principais motivos para o não cumprimento das"
                    " metas no prazo."
                ),
                "8.4.4": (
                    "Qual a data da última revisão do Plano de Gestão Integrada"
                    " de Resíduos Sólidos?"
                ),
                "9.0": (
                    "O Município realiza de forma efetiva a coleta seletiva de"
                    " resíduos sólidos?"
                ),
                "9.1": (
                    "Existe um cronograma ou planejamento de coleta seletiva"
                    " programada?"
                ),
                "9.2": (
                    "A prestação da coleta seletiva atende a todas as regiões"
                    " do território municipal?"
                ),
                "9.3": (
                    "São promovidas ações e campanhas institucionais de"
                    " incentivo à coleta seletiva?"
                ),
                "9.3.1": (
                    "Informe quais tipos de ações e campanhas de"
                    " conscientização foram realizadas."
                ),
                "10.0": (
                    "O Município realiza o serviço regular de coleta de lixo"
                    " doméstico (resíduos domiciliares)?"
                ),
                "10.1": (
                    "Existe um cronograma de atendimento para a coleta"
                    " programada?"
                ),
                "10.2": (
                    "O serviço regular de coleta de lixo domiciliar atende a"
                    " todas as regiões do município?"
                ),
                "10.3": (
                    "O Município dispõe de Área de Transbordo e Triagem (ATT)"
                    " para resíduos sólidos urbanos?"
                ),
                "10.3.1": (
                    "A referida ATT possui licença de operação ativa emitida"
                    " pela CETESB?"
                ),
                "10.3.1.1": (
                    "Informe o prazo de validade da licença de operação da"
                    " CETESB."
                ),
                "11.0": (
                    "Existe Plano de Gerenciamento de Resíduos da Construção"
                    " Civil (PGRCC) instituído?"
                ),
                "11.1": (
                    "Informe o instrumento normativo que regulamenta o PGRCC."
                ),
                "11.2": "Informe a página eletrônica (link na internet) do PGRCC.",
                "11.3": (
                    "Existe um cronograma de metas definido no âmbito do PGRCC?"
                ),
                "11.3.1": (
                    "Informe as metas previstas no Plano de Resíduos da"
                    " Construção Civil."
                ),
                "11.3.2": (
                    "Há monitoramento e avaliação das ações e metas do PGRCC?"
                ),
                "11.3.2.1": (
                    "Informe de qual forma é realizado o monitoramento e a"
                    " avaliação."
                ),
                "11.3.3": (
                    "As metas estabelecidas no PGRCC estão sendo cumpridas no"
                    " prazo estipulado?"
                ),
                "11.3.3.1": (
                    "Informe os motivos identificados para o não cumprimento"
                    " das metas estruturadas."
                ),
                "11.4": (
                    "Quem é o agente ou setor responsável pela triagem dos"
                    " resíduos da construção civil?"
                ),
                "11.5": (
                    "O Município realiza a fiscalização ativa das atividades"
                    " relacionadas aos resíduos da construção civil?"
                ),
                "11.5.1": (
                    "Informe quais as principais atividades que são"
                    " fiscalizadas pelo órgão municipal."
                ),
                "11.6": (
                    "Existe Área de Transbordo e Triagem (ATT) específica para"
                    " resíduos da construção civil?"
                ),
                "11.6.1": (
                    "A referida ATT de resíduos da construção civil possui"
                    " licença de operação da CETESB?"
                ),
                "11.6.1.1": (
                    "Informe o prazo de validade da licença emitida pela"
                    " CETESB."
                ),
                "12.0": (
                    "O Município adota alguma forma de processamento de"
                    " resíduos antes da sua disposição final?"
                ),
                "12.1": (
                    "Informe detalhadamente qual a forma de processamento"
                    " utilizada nos resíduos."
                ),
                "13.0": (
                    "Existe aterro sanitário ou industrial para destinação de"
                    " resíduos sólidos urbanos no território municipal ou"
                    " consorciado?"
                ),
                "13.1": (
                    "Informe as características e a situação atual do local de"
                    " destinação final dos resíduos."
                ),
                "13.1.1": (
                    "Informe a data provável estimada para o fechamento ou"
                    " esgotamento do aterro."
                ),
                "13.2": (
                    "O aterro utilizado possui licença de operação regular"
                    " emitida pela CETESB?"
                ),
                "13.2.1": (
                    "Informe o prazo de validade da respectiva licença de"
                    " operação."
                ),
                "14.0": (
                    "Foram identificados pontos de descarte irregular de lixo"
                    " ou entulho no município?"
                ),
                "14.1": (
                    "Informe a quantidade total de pontos de descarte irregular"
                    " atualmente identificados."
                ),
                "14.2": (
                    "Indique os endereços ou localizações dos pontos críticos"
                    " identificados."
                ),
                "14.3": (
                    "Quais ações práticas e fiscalizatórias foram promovidas"
                    " para combater e mitigar o descarte irregular?"
                ),
                "15.0": (
                    "Está definida qual a entidade responsável pela regulação"
                    " e fiscalização dos serviços de saneamento básico?"
                ),
                "15.1": (
                    "Assinale quais serviços municipais possuem entidade"
                    " reguladora e fiscalizadora externa ou interna."
                ),
                "15.1.1": (
                    "Informe a entidade responsável pela regulação do"
                    " abastecimento de água potável."
                ),
                "15.1.2": (
                    "Informe a entidade responsável pela regulação do"
                    " esgotamento sanitário."
                ),
                "15.1.3": (
                    "Informe a entidade responsável pela regulação da limpeza"
                    " urbana e manejo de resíduos sólidos."
                ),
                "15.1.4": (
                    "Informe a entidade responsável pela regulação da drenagem"
                    " e manejo das águas pluviais urbanas."
                ),
                "16.0": (
                    "Gostaria de registrar suas impressões, comentários e"
                    " sugestões gerais a respeito deste bloco do questionário?"
                ),
                "A1": (
                    "O Município possui Zoneamento Ecológico-Econômico (ZEE)"
                    " instituído ou em andamento?"
                ),
                "A2": (
                    "Há monitoramento sistemático da qualidade do ar nas zonas"
                    " urbanas ou industriais do município?"
                ),
                "A3": (
                    "O município possui mapeamento atualizado e proteção ativa"
                    " de suas Áreas de Preservação Permanente (APP)?"
                ),
                "A4": (
                    "Existe programa municipal voltado para a proteção e"
                    " bem-estar de animais domésticos e controle de zoonoses?"
                ),
                "A4.1.1": (
                    "Informe a capacidade física e operacional do abrigo ou"
                    " canil municipal."
                ),
                "A4.1.1.1": (
                    "Há veterinário responsável contratado em regime definitivo"
                    " ou plantonista?"
                ),
                "A4.1.2": (
                    "O município realiza campanhas periódicas e gratuitas de"
                    " castração de cães e gatos?"
                ),
                "A4.1.3": (
                    "Informe o número de procedimentos de esterilização animal"
                    " realizados no último ano de exercício."
                ),
                "A4.1.4": (
                    "Existem parcerias ativas com ONGs e protetores"
                    " independentes locais registradas?"
                ),
                "A5": (
                    "O Município possui plano de prevenção e combate a"
                    " incêndios florestais e queimadas urbanas?"
                ),
                "A6": (
                    "O órgão ambiental municipal possui equipamentos adequados"
                    " para atendimento e contenção de emergências químicas ou"
                    " derramamentos?"
                ),
            },
        }

        self.pontuacoes_maximas_por_dimensao = {
            "iCidade": {
                "1.0": 40,
                "1.3": 5,
                "1.4": 50,
                "2.0": 20,
                "2.1": 30,
                "2.2": 10,
                "3.0": 10,
                "3.1.1": 10,
                "5.0": 200,
                "7.0": 50,
                "7.1": 5,
                "7.2": 80,
                "7.3": 50,
                "7.4": 50,
                "7.5": 10,
                "7.6": 10,
                "8.0": 50,
                "8.1.1.1": 20,
                "8.2": 50,
                "9.0": 100,
                "15.0": 50,
                "16.0": 50,
                "C1.1": 50,
            },
            "iGov-Ti": {
                "1.0": 30,
                "1.1": 30,
                "1.2": 30,
                "1.3": 30,
                "1.3.1": 30,
                "1.4.1": 40,
                "1.4.2": 20,
                "2.0": 40,
                "2.1": 20,
                "2.2": 40,
                "2.3": 20,
                "3.0": 50,
                "3.1": 20,
                "3.1.1": 40,
                "3.1.1.1": 10,
                "3.2.1": 10,
                "3.3": 30,
                "3.4": 30,
                "3.5": 30,
                "3.6": 20,
                "4.0": 40,
                "6.0": 20,
                "6.1": 20,
                "6.2": 20,
                "6.3": 10,
                "6.4": 30,
                "7.0": 25,
                "7.1": 10,
                "7.2": 10,
                "7.3": 5,
                "8.0": 40,
                "8.2.1": 50,
                "8.2.2": 30,
                "9.1": 120,
            },
            "i-Amb": {
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
                "A6": 5,
            },
        }

    @st.cache_resource
    def inicializar_banco_postgres(_self):
        """Conecta diretamente ao Neon PostgreSQL via Connection String"""
        try:
            conn = psycopg2.connect(DATABASE_URL)
            return conn
        except Exception as e:
            st.error(f"Erro ao conectar ao Neon PostgreSQL: {e}")
            return None

    def obter_conexao(self):
        """Garante conexão ativa"""
        if self.conn is None or self.conn.closed != 0:
            self.conn = self.inicializar_banco_postgres()
        return self.conn

    def _obter_nome_tabela(self, dimensao: str) -> str:
        """Mapeia o nome da dimensão para a tabela real no banco."""
        return self.mapeamento_tabelas.get(
            dimensao, f"respostas_{dimensao.lower().replace('-', '')}"
        )

    def puxar_nota_dimensao(self, dimensao: str, ano: int) -> float:
        """Calcula a nota aplicando a regra TCESP:

        - Se houver item crítico (pontos <= -100.0), a nota final é 0.0.
        - Caso contrário, soma os pontos e garante nota mínima de 0.0.
        """
        conn = self.obter_conexao()
        if not conn:
            return 0.0

        tabela = self._obter_nome_tabela(dimensao)

        try:
            with conn.cursor() as cursor:
                # Tenta primeiro na tabela dedicada (ex: respostas_iamb)
                try:
                    sql = f"SELECT pontos FROM {tabela} WHERE ano = %s;"
                    cursor.execute(sql, (int(ano),))
                    rows = cursor.fetchall()
                except Exception:
                    # Fallback em respostas (caso exista a tabela central com filtro de dimensao)
                    conn.rollback()
                    sql = (
                        "SELECT pontos FROM respostas WHERE LOWER(dimensao) ="
                        " %s AND ano = %s;"
                    )
                    cursor.execute(sql, (dimensao.lower(), int(ano)))
                    rows = cursor.fetchall()

                if not rows:
                    return 0.0

                pontos_lista = [
                    float(r[0]) for r in rows if r[0] is not None
                ]

                # Regra de rebaixamento crítico TCESP (pontos <= -100.0 zeram a nota)
                if any(p <= -100.0 for p in pontos_lista):
                    return 0.0

                total = sum(p for p in pontos_lista if p > -100.0)
                return float(max(0.0, total))

        except Exception as e:
            logging.warning(
                f"[{dimensao}] Erro ao ler nota do ano {ano}: {e}"
            )
            return 0.0

    def consultar_anos(self, dimensao: str, quesito_id: str):
        conn = self.obter_conexao()
        if not conn:
            return []
        tabela = self._obter_nome_tabela(dimensao)
        try:
            with conn.cursor() as cursor:
                try:
                    cursor.execute(
                        f"SELECT ano, valor FROM {tabela} WHERE id = %s ORDER"
                        " BY ano ASC;",
                        (quesito_id,),
                    )
                    return cursor.fetchall()
                except Exception:
                    conn.rollback()
                    cursor.execute(
                        "SELECT ano, valor FROM respostas WHERE LOWER(dimensao)"
                        " = %s AND id = %s ORDER BY ano ASC;",
                        (dimensao.lower(), quesito_id),
                    )
                    return cursor.fetchall()
        except Exception:
            return []

    def analisar_pontos_fracos(self, ano: int, dimensao: str):
        conn = self.obter_conexao()
        if not conn:
            return [], []

        tabela = self._obter_nome_tabela(dimensao)
        pontos_fracos = []
        penalidades_detectadas = []

        questoes = self.questoes_por_dimensao.get(dimensao, {})
        pontuacoes_maximas = self.pontuacoes_maximas_por_dimensao.get(
            dimensao, {}
        )

        try:
            with conn.cursor() as cursor:
                try:
                    cursor.execute(
                        f"SELECT id, valor, pontos FROM {tabela} WHERE ano ="
                        " %s;",
                        (int(ano),),
                    )
                    rows = cursor.fetchall()
                except Exception:
                    conn.rollback()
                    cursor.execute(
                        "SELECT id, valor, pontos FROM respostas WHERE"
                        " LOWER(dimensao) = %s AND ano = %s;",
                        (dimensao.lower(), int(ano)),
                    )
                    rows = cursor.fetchall()

                for qid, valor, pontos_reais in rows:
                    pontos_reais = (
                        float(pontos_reais) if pontos_reais is not None else 0.0
                    )
                    if qid in questoes:
                        if pontos_reais < 0:
                            penalidades_detectadas.append({
                                "id": qid,
                                "pergunta": questoes.get(qid),
                                "valor": valor,
                                "penalidade": pontos_reais,
                                "is_critico": pontos_reais <= -100.0,
                            })
                        elif qid in pontuacoes_maximas:
                            max_possivel = pontuacoes_maximas[qid]
                            if pontos_reais < max_possivel:
                                deficit = max_possivel - pontos_reais
                                pontos_fracos.append({
                                    "id": qid,
                                    "pergunta": questoes.get(qid),
                                    "valor": valor,
                                    "obtido": pontos_reais,
                                    "maximo": max_possivel,
                                    "deficit": deficit,
                                })

                pontos_fracos.sort(key=lambda x: x["deficit"], reverse=True)
                penalidades_detectadas.sort(key=lambda x: x["penalidade"])
                return pontos_fracos, penalidades_detectadas

        except Exception as e:
            logging.error(f"Erro ao analisar pontos fracos em {dimensao}: {e}")
            return [], []
