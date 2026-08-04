import streamlit as st
import sqlite3
import time
import os
import re
import json
import plotly.graph_objects as go

class SistemaHAL:
    def __init__(self):
        self.questoes_por_dimensao = {}
        self.pontuacoes_maximas_por_dimensao = {}
        self.carregar_dicionarios_globais()
        # Inicializa mapeamento de conexões com os arquivos físicos corretos
        self.conexoes = self.inicializar_bancos_dados()

    def carregar_dicionarios_globais(self):
        # Dicionário unificado com as 3 dimensões operacionais
        self.questoes_por_dimensao = {
            "iCidade": {
                "1.0": "Foi criada a Coordenadoria Municipal de Proteção e Defesa Civil (COMPDEC) ou órgão similar responsável pela execução, coordenação e mobilização de todas as ações de defesa civil no município?",
                "1.3": "A COMPDEC ou órgão similar está associada ou subordinada a qual secretaria/diretoria?",
                "1.4": "Os órgãos e entidades da administração pública municipal atuam de forma sistêmica, articulados com a COMPDEC, nas ações de prevenção, mitigação, preparação, resposta e recuperação, de acordo com a Política Nacional de Proteção e Defesa Civil (PNPDEC)?",
                "2.0": "Sobre treinamento e capacitação em Proteção e Defesa Civil, a Prefeitura capacita seus agentes para ações municipais de Defesa Civil?",
                "2.1": "Qual a data da última classificação dos agentes municipais para ações de Defesa Civil?",
                "2.2": "A Prefeitura Municipal ofereceu cursos/treinamentos sobre Proteção e Defesa Civil para qual público?",
                "3.0": "O Município realiza ações para estimular a participação de entidades privadas, associações de voluntários, clubes de serviços, organizações não governamentais e associações de classe e comunitárias nas ações de proteção e defesa civil?",
                "3.1.1": "Qual a data do último treinamento de associações de voluntários?",
                "4.2": "A Carta Geotécnica de Suscetibilidade, Aptidão à Urbanização e Risco consta no Plano Diretor, conforme art. 42-A, §§ 1º, 2º e 3º, da Lei Federal nº 10.257, de 10 de julho de 2001?",
                "5.0": "O Município realizou, por conta própria, o mapeamento e identificação das principais ameaças existentes em seu território?",
                "5.1.1": "As secretarias setoriais realizam a fiscalização das áreas de risco?",
                "5.2": "A população foi informada sobre todas as ameaças identificadas pelo município?",
                "6.0": "A Secretaria responsável realizou vistorias in edificações vulneráveis com o objetivo de identificar a necessidade de intervenção preventiva nos imóveis?",
                "7.0": "O Município possui Plano de Contingência Municipal (PLANCON) de Defesa Civil?",
                "7.1": "Foi elaborado um PLANCON específico para cada ameaça identificada?",
                "7.2": "São realizados regularmente exercícios simulados para as contingências previstas no PLANCON?",
                "7.3": "O Município possui sistema de alerta para desastres?",
                "7.4": "O Município dispõe de sinal, dispositivo ou sistema de alarme para desastres?",
                "7.5": "Possui cadastro dos locais para abrigo da população em situação de desastre junto à Coordenadoria Estadual de Proteção e Defesa Civil (CEPDEC)?",
                "7.6": "O Município possui cadastro da lista de fornecedores para coleta e distribuição de suprimentos de ajuda humanitária para o caso de desastre?",
                "8.0": "O Município possui um canal de atendimento de emergência à população para registro de ocorrências de desastres?",
                "8.1.1.1": "O telefone 199 tem atendimento 24 horas por dia?",
                "8.2": "O Município registra as ocorrências de Defesa Civil de forma eletrônica?",
                "9.0": "O Município realizou estudo de avaliação da estrutura de todas as escolas e unidades de saúde para garantir que, em caso de desastre, esses locais estejam preparados para abrigar e atender a população afetada?",
                "10.0": "O Município elaborou seu Plano de Mobilidade Urbana?",
                "11.1": "Foram estabelecidas metas de qualidade e desempenho para o transporte público coletivo municipal?",
                "11.1.1": "As metas de qualidade e desempenho do transporte público coletivo estão sendo atingidas?",
                "11.2": "Foi realizada pesquisa de satisfação dos usuários do transporte público coletivo em 2025?",
                "12.1": "Informe o instrumento normativo, número e data da publicação do transporte regulamentado.",
                "12.1.3": "O Município fiscaliza regularmente o transporte remunerado privado individual de passageiros (táxi por aplicativo)?",
                "14.0": "O Município adequou os calçamentos públicos para acessibilidade das pessoas com deficiência e restrição de mobilidade?",
                "15.0": "As vias públicas pavimentadas estão devidamente sinalizadas (vertical e horizontalmente) de forma a garantir condições adequadas de segurança na circulação?",
                "16.0": "Há manutenção adequada das vias públicas no Município?",
                "C1.1": "Indique os pontos de controle externos da auditoria ou controle de metas vigentes."
            },
            "iGov-Ti": {
                "1.0": "A Prefeitura possui uma área ou setor que cuida de Tecnologia da Informação e Comunicação (TIC)?",
                "1.1": "Informe a quantidade de funcionários concursados, comissionados e estagiários no suporte e atendimento de primeiro nível.",
                "1.2": "A prefeitura municipal definiu formalmente as atribuições do pessoal do setor de Tecnologia da Informação e Comunicação (TIC)?",
                "1.3": "A prefeitura disponibilizou capacitação para o pessoal da área de Tecnologia da Informação e Comunicação (TIC)?",
                "1.3.1": "Informe em quais áreas houve capacitação.",
                "1.4": "Nas licitações e contratos que tenham como soluções o uso de TIC, houve participação formalizada do pessoal de TIC? (Verba municipal)",
                "1.4.1": "Assinale as etapas que o pessoal de TIC participa.",
                "1.4.2": "Sobre softwares adquiridos/licenciados nos últimos 5 anos, foi realizada análise ou estudo prévio com a participação de TIC?",
                "2.0": "A prefeitura municipal possui um PDTIC vigente que estabeleça diretrizes e metas de atingimento no futuro?",
                "2.1": "Informe a página eletrônica (link na internet) do PDTIC.",
                "2.2": "O plano de TIC vigente contempla as metas operacionais estratégicas municipais?",
                "2.3": "Qual a data da última atualização do PDTIC?",
                "3.0": "A Prefeitura dispõe de Política de Segurança da Informação formalmente instituída e de cumprimento obrigatório?",
                "3.1": "A Prefeitura establishes procedimentos e responsabilidades quanto ao uso de TI (Termo de Responsabilidade/Compromisso)?",
                "3.1.1": "O Termo de Responsabilidade/Compromisso dispõe sobre o uso da assinatura eletrônica pelos funcionários?",
                "3.1.1.1": "Informe o tipo de assinatura eletrônica utilizada nos documentos digitais.",
                "3.2": "Os riscos de TIC são identificados de acordo com as normas brasileiras da família ISO/IEC 27000?",
                "3.2.1": "As secretarias realizam a fiscalização das áreas de risco? Informe quais normas ISO/IEC 27000 são utilizadas.",
                "3.3": "Os riscos de TIC são identificados de acordo com as normas da ABNT NBR ISO/IEC 31000?",
                "3.4": "A Prefeitura possui um Plano de Continuidade dos Serviços de Tecnologia da Informação e Comunicação (TIC)?",
                "3.5": "A Prefeitura dispõe de política de cópias de segurança (backup) formalmente instituída como norma obrigatória?",
                "3.6": "A Prefeitura possui inventário atualizado dos ativos de TIC?",
                "3.6.1": "Como é composta a base de ativos?",
                "4.0": "O município regulamentou a Lei de Acesso à Informação (Lei Federal nº 12.527/2011)?",
                "4.1": "Informe o Instrumento normativo, Número e Data da publicação (LAI).",
                "4.2": "Página eletrônica (link na internet) do instrumento normativo da LAI.",
                "5.0": "O município regulamentou a Lei sobre Eficiência Pública (Governo Digital - Lei Federal nº 14.129/2021)?",
                "5.1": "Informe o Instrumento normativo, Número e Data da publicação (Governo Digital).",
                "5.2": "Página eletrônica (link na internet) do instrumento normativo (Governo Digital).",
                "5.3": "A Prefeitura implantou soluções digitais para trâmite de processos administrativos?",
                "6.0": "A prefeitura mantém site na internet com informações atualizadas?",
                "6.1": "O site eletrônico da prefeitura continha ferramenta de pesquisa/busca interna de conteúdo?",
                "6.2": "O site possibilita o download de dados e informações em formatos abertos e não proprietários?",
                "6.3": "O site disponibiliza as respostas a perguntas mais frequentes da sociedade?",
                "6.4": "O site disponibiliza acessibilidade de conteúdo para pessoas com deficiência?",
                "7.0": "A Prefeitura disponibiliza no site o Serviço de Informação ao Cidadão (e-SIC)?",
                "7.1": "A solicitação por meio do e-SIC é simplificada?",
                "7.2": "O e-SIC apresenta possibilidade de acompanhamento da solicitação?",
                "7.3": "Há necessidade de informar os motivos para a solicitação de informações de interesse público?",
                "8.0": "A Prefeitura possui programas de computador (softwares) para gestão de processos?",
                "8.1": "Os programas de computador (softwares) englobam quais processos/setores?",
                "8.2": "Informe quais sistemas encontram-se integrados ao Sistema de Contabilidade do município.",
                "8.2.1": "Informe o nível de integração entre o Sistema da Dívida Ativa e o de Contabilidade.",
                "8.2.2": "Informe o nível de integração entre o Sistema de Precatórios e o de Contabilidade.",
                "8.3": "Assinale quais bases de dados encontram-se sob gestão direta da Prefeitura (Risco de Perdas).",
                "8.4": "Assinale quais sistemas possuem controle de acesso à informação.",
                "9.0": "A Prefeitura ofereceu serviços de forma online?",
                "9.1": "Quais tipos de serviços são oferecidos online?",
                "9.2": "Quais as formas de atendimento à distância disponibilizadas ao público pela Prefeitura?",
                "10.0": "A Prefeitura Municipal regulamentou o tratamento de dados pessoais, inclusive nos meios digitais, segundo a LGPD (Lei Federal nº 13.709/2018)?",
                "10.1": "Informe o instrumento normativo, número e data da publicação.",
                "10.2": "Informe a página eletrônica (link na internet).",
                "10.3": "Os contratos com os prestadores de serviços contêm cláusulas de observância à LGPD?",
                "10.4": "A Prefeitura Municipal realizou mapeamento de dados (data mapping)?",
                "10.5": "Foram adotadas medidas de segurança, técnicas e administrativas para proteção dos dados pessoais?",
                "10.5.1": "Informe as medidas adotadas.",
                "11.0": "A Prefeitura Municipal designou um encarregado para as operações de tratamento de dados pessoais?",
                "11.1": "Informe a página eletrônica que contenha a identidade e as informações de contato do encarregado.",
                "12.0": "Gostaria de registrar suas impressões, comentários e sugestões a respeito do presente questionário?"
            },
            "i-Amb": {
                "1.0": "Existe estrutura organizacional instalada para tratar de assuntos ligados ao Meio Ambiente Municipal?",
                "1.1": "Informe a disponibilidade de recursos humanos para operacionalização dos assuntos ligados ao Meio Ambiente.",
                "1.1.1": "Informe o detalhamento e informações sobre os recursos humanos da área.",
                "1.1.2": "A prefeitura realizou treinamento específico voltado ao Meio Ambiente no ano de 2025?",
                "1.1.3": "Informe os cursos e treinamentos de educação ambiental ofertados pela Secretaria de Meio Ambiente.",
                "1.2": "Informe quais recursos foram disponibilizados para a operacionalização das atividades de meio ambiente.",
                "2.0": "O Município promove a participação em Programas de Educação Ambiental?",
                "2.1": "Há programas ou ações de educação ambiental implementadas na rede escolar municipal?",
                "3.0": "O Município promove estímulo a projetos e ações para o uso racional de recursos naturais?",
                "3.1": "Assinale quais tipos de ações são realizadas para o uso racional de recursos naturais.",
                "4.0": "Há fiscalização da emissão de poluentes de combustíveis fósseis (diesel) na frota municipal?",
                "5.0": "Existe contrato vigente para a prestação de serviços de poda e corte de árvores, arbustos e outras plantas lenhosas?",
                "5.1": "Informe o número do contrato e o respectivo prestador de serviço.",
                "5.2": "Qual a periodicidade definida para a realização de poda e manutenção das árvores?",
                "5.2.1": "Informe a destinação final dada aos resíduos decorrentes das podas de árvores.",
                "5.3": "Houve capacitação específica para os responsáveis pela execução da manutenção e poda de árvores?",
                "6.0": "O Município adota ações e medidas preventivas de contingenciamento para períodos de estiagem?",
                "6.1": "Informe os tipos de ações and medidas preventivas que foram executadas.",
                "6.2": "Indique os setores envolvidos com ações específicas para a provisão de água potável.",
                "7.0": "Existe Plano Municipal ou Regional de Saneamento Básico instituído e vigente?",
                "7.1": "Informe o instrumento normativo de aprovação do Plano.",
                "7.2": "Informe a página eletrônica (link na internet) para acesso ao Plano.",
                "7.3": "O Plano establishes metas específicas de abastecimento de água potável?",
                "7.3.1": "Informe detalhadamente as metas estabelecidas para o abastecimento de água.",
                "7.3.2": "Qual a data prevista para a universalização do atendimento de abastecimento de água?",
                "7.4": "O Plano estabelece metas de coleta de esgoto sanitário?",
                "7.4.1": "Informe as metas estabelecidas para o serviço de coleta de esgoto.",
                "7.4.2": "Qual a data prevista para a universalização da coleta de esgoto?",
                "7.5": "O Plano estabelece metas para o tratamento do esgoto coletado?",
                "7.5.1": "Qual a data prevista para a universalização do tratamento de esgoto?",
                "7.6": "O Plano contempla metas de drenagem e manejo de águas pluviais urbanas?",
                "7.6.1": "Informe as metas estabelecidas voltadas à drenagem e manejo de águas pluviais.",
                "7.7": "O Município realiza o monitoramento e avaliação das ações e metas de abastecimento de água e esgotamento sanitário?",
                "7.7.1": "Informe de qual forma é realizado este monitoramento e avaliação.",
                "7.8": "Existe um cronograma formalizado de metas para o saneamento básico?",
                "7.8.1": "As metas estabelecidas estão sendo cumpridas dentro do prazo estipulado?",
                "7.8.1.1": "Informe os principais motivos que justificam o não cumprimento das metas.",
                "7.9": "O Plano apresenta previsão de áreas prioritárias ou críticas para intervenções de abastecimento de água e esgotamento sanitário?",
                "7.10": "Qual a data da última revisão realizada no Plano de Saneamento Básico?",
                "8.0": "Existe Plano Municipal ou Regional de Gestão Integrada de Resíduos Sólidos instituído?",
                "8.1": "Informe o instrumento normativo de aprovação do Plano de Resíduos Sólidos.",
                "8.2": "Informe a página eletrônica (link na internet) para acesso ao Plano.",
                "8.3": "O Plano apresenta a caracterização qualitativa e quantitativa dos resíduos sólidos urbanos?",
                "8.3.1": "Informe a metodologia ou forma utilizada para a caracterização dos resíduos.",
                "8.4": "Existe um cronograma formalizado de metas para a gestão de resíduos sólidos?",
                "8.4.1": "Informe as metas que foram formalmente estabelecidas sobre os resíduos sólidos.",
                "8.4.2": "O Município realiza o monitoramento e avaliação das ações e metas deste Plano?",
                "8.4.2.1": "Informe de qual forma é realizado esse monitoramento e avaliação.",
                "8.4.3": "As metas estabelecidas estão sendo cumpridas dentro do prazo estipulado?",
                "8.4.3.1": "Informe os principais motivos para o não cumprimento das metas no prazo.",
                "8.4.4": "Qual a data da última revisão do Plano de Gestão Integrada de Resíduos Sólidos?",
                "9.0": "O Município realiza de forma efetiva a coleta seletiva de resíduos sólidos?",
                "9.1": "Existe um cronograma ou planejamento de coleta seletiva programada?",
                "9.2": "A prestação da coleta seletiva atende a todas as regiões do território municipal?",
                "9.3": "São promovidas ações e campanhas institucionais de incentivo à coleta seletiva?",
                "9.3.1": "Informe quais tipos de ações e campanhas de conscientização foram realizadas.",
                "10.0": "O Município realiza o serviço regular de coleta de lixo doméstico (resíduos domiciliares)?",
                "10.1": "Existe um cronograma de atendimento para a coleta programada?",
                "10.2": "O serviço regular de coleta de lixo domiciliar atende a todas as regiões do município?",
                "10.3": "O Município dispõe de Área de Transbordo e Triagem (ATT) para resíduos sólidos urbanos?",
                "10.3.1": "A referida ATT possui licença de operação ativa emitida pela CETESB?",
                "10.3.1.1": "Informe o prazo de validade da licença de operação da CETESB.",
                "11.0": "Existe Plano de Gerenciamento de Resíduos da Construção Civil (PGRCC) instituído?",
                "11.1": "Informe o instrumento normativo que regulamenta o PGRCC.",
                "11.2": "Informe a página eletrônica (link na internet) do PGRCC.",
                "11.3": "Existe um cronograma de metas definido no âmbito do PGRCC?",
                "11.3.1": "Informe as metas previstas no Plano de Resíduos da Construção Civil.",
                "11.3.2": "Há monitoramento e avaliação das ações e metas do PGRCC?",
                "11.3.2.1": "Informe de qual forma é realizado o monitoramento e a avaliação.",
                "11.3.3": "As metas estabelecidas no PGRCC estão sendo cumpridas no prazo estipulado?",
                "11.3.3.1": "Informe os motivos identificados para o não cumprimento das metas estruturadas.",
                "11.4": "Quem é o agente ou setor responsável pela triagem dos resíduos da construção civil?",
                "11.5": "O Município realiza a fiscalização activa das atividades relacionadas aos resíduos da construção civil?",
                "11.5.1": "Informe quais as principais atividades que são fiscalizadas pelo órgão municipal.",
                "11.6": "Existe Área de Transbordo e Triagem (ATT) específica para resíduos da construção civil?",
                "11.6.1": "A referida ATT de resíduos da construção civil possui licença de operação da CETESB?",
                "11.6.1.1": "Informe o prazo de validade da licença emitida pela CETESB.",
                "12.0": "O Município adota alguma forma de processamento de resíduos antes da sua disposição final?",
                "12.1": "Informe detalhadamente qual a forma de processamento utilizada nos resíduos.",
                "13.0": "Existe aterro sanitário ou industrial para destinação de resíduos sólidos urbanos no território municipal ou consorciado?",
                "13.1": "Informe as características e a situação atual do local de destinação final dos resíduos.",
                "13.1.1": "Informe a data provável estimada para o fechamento ou esgotamento do aterro.",
                "13.2": "O aterro utilizado possui licença de operação regular emitida pela CETESB?",
                "13.2.1": "Informe o prazo de validade da respectiva licença de operação.",
                "14.0": "Foram identificados pontos de descarte irregular de lixo ou entulho no município?",
                "14.1": "Informe a quantidade total de pontos de descarte irregular atualmente identificados.",
                "14.2": "Indique os endereços ou localizações dos pontos críticos identificados.",
                "14.3": "Quais ações práticas e fiscalizatórias foram promovidas para combater e mitigar o descarte irregular?",
                "15.0": "Está definida qual a entidade responsável pela regulação e fiscalização dos serviços de saneamento básico?",
                "15.1": "Assinale quais serviços municipais possuem entidade reguladora e fiscalizadora externa ou interna.",
                "15.1.1": "Informe a entidade responsável pela regulação do abastecimento de água potável.",
                "15.1.2": "Informe a entidade responsável pela regulação do esgotamento sanitário.",
                "15.1.3": "Informe a entidade responsável pela regulação da limpeza urbana e manejo de resíduos sólidos.",
                "15.1.4": "Informe a entidade responsável pela regulação da drenagem e manejo das águas pluviais urbanas.",
                "16.0": "Gostaria de registrar suas impressões, comentários e sugestões gerais a respeito deste bloco do questionário?",
                "A1": "O Município possui Zoneamento Ecológico-Econômico (ZEE) instituído ou em andamento?",
                "A2": "Há monitoramento sistemático da qualidade do ar nas zones urbanas ou industriais do município?",
                "A3": "O município possui mapeamento atualizado e proteção ativa de suas Áreas de Preservação Permanente (APP)?",
                "A4": "Existe programa municipal voltado para a proteção e bem-estar de animais domésticos e controle de zoonoses?",
                "A4.1.1": "Informe a capacidade física e operacional do abrigo ou canil municipal.",
                "A4.1.1.1": "Há veterinário responsável contratado em regime definitivo ou plantonista?",
                "A4.1.2": "O município realiza campanhas periódicas e gratuitas de castração de cães e gatos?",
                "A4.1.3": "Informe o número de procedimentos de esterilização animal realizados no último ano de exercício.",
                "A4.1.4": "Existem parcerias ativas com ONGs e protetores independentes locais registradas?",
                "A5": "O Município possui plano de prevenção e combate a incêndios florestais e queimadas urbanas?",
                "A6": "O órgão ambiental municipal possui equipamentos adequados para atendimento e contenção de emergências químicas ou derramamentos?"
            }
        }

        self.pontuacoes_maximas_por_dimensao = {
            "iCidade": {
                "1.0": 40, "1.3": 5, "1.4": 50, "2.0": 20, "2.1": 30, "2.2": 10,
                "3.0": 10, "3.1.1": 10, "5.0": 200, "7.0": 50, "7.1": 5, "7.2": 80,
                "7.3": 50, "7.4": 50, "7.5": 10, "7.6": 10, "8.0": 50, "8.1.1.1": 20,
                "8.2": 50, "9.0": 100, "15.0": 50, "16.0": 50, "C1.1": 50
            },
            "iGov-Ti": {
                "1.0": 30, "1.1": 30, "1.2": 30, "1.3": 30, "1.3.1": 30, "1.4.1": 40, "1.4.2": 20,
                "2.0": 40, "2.1": 20, "2.2": 40, "2.3": 20,
                "3.0": 50, "3.1": 20, "3.1.1": 40, "3.1.1.1": 10, "3.2.1": 10, "3.3": 30, "3.4": 30, "3.5": 30, "3.6": 20,
                "4.0": 40, "6.0": 20, "6.1": 20, "6.2": 20, "6.3": 10, "6.4": 30, "7.0": 25, "7.1": 10, "7.2": 10, "7.3": 5,
                "8.0": 40, "8.2.1": 50, "8.2.2": 30, "9.1": 120
            },
            "i-Amb": {
                "1.1.2": 20, "1.1.3": 5, "1.2": 20, "2.0": 10, "2.1": 50, "3.0": 10,
                "3.1": 20, "4.0": 20, "5.2.1": 20, "6.0": 20, "6.1": 50, "6.2": 25,
                "7.2": 2, "7.3": 10, "7.3.1": 20, "7.4": 10, "7.4.1": 20, "7.5": 30,
                "7.7": 30, "7.8": 20, "7.8.1": 50, "7.9": 3, "8.2": 2, "8.3": 10,
                "8.4": 20, "8.4.1": 10, "8.4.2": 30, "8.4.3": 50, "9.2": 100, "9.3": 5,
                "9.3.1": 5, "11.2": 2, "11.3": 30, "11.3.2": 20, "11.3.3": 40, "11.5": 10,
                "12.1": 54, "14.3": 30, "15": 2, "15.1": 3, "A4.1.1": 90, "A4.1.2": 20,
                "A4.1.3": 22, "A6": 5
            }
        }

    def inicializar_bancos_dados(self):
        bancos = {
            "iGov-Ti": "dados_igov_ti.db",
            "iCidade": "dados_iegm_web.db",
            "i-Amb": "dados_iamb.db"
        }
        conexoes = {}
        for dim, arq in bancos.items():
            try:
                conexoes[dim] = sqlite3.connect(arq, check_same_thread=False)
            except Exception:
                conexoes[dim] = None
        return conexoes

    def obter_conexao(self, dimensao):
        return self.conexoes.get(dimensao, self.conexoes.get("iCidade"))

    def consultar_anos(self, dimensao, quesito_id):
        conn = self.obter_conexao(dimensao)
        if not conn: return []
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT ano, valor FROM respostas WHERE id = ? ORDER BY ano ASC;", (quesito_id,))
            return cursor.fetchall()
        except Exception:
            return []

    def analisar_pontos_fracos(self, ano, dimensao):
        conn = self.obter_conexao(dimensao)
        if not conn: return [], []
        cursor = conn.cursor()
        pontos_fracos = []
        penalidades_detectadas = []
        
        questoes = self.questoes_por_dimensao.get(dimensao, {})
        pontuacoes_maximas = self.pontuacoes_maximas_por_dimensao.get(dimensao, {})
        
        try:
            cursor.execute("SELECT id, valor, pontos FROM respostas WHERE ano = ?;", (ano,))
            rows = cursor.fetchall()
            
            for qid, valor, pontos_reais in rows:
                if qid in questoes:
                    if pontos_reais < 0:
                        penalidades_detectadas.append({
                            "id": qid, "pergunta": questoes.get(qid),
                            "valor": valor, "penalidade": pontos_reais
                        })
                    elif qid in pontuacoes_maximas:
                        max_possivel = pontuacoes_maximas[qid]
                        if pontos_reais < max_possivel:
                            deficit = max_possivel - pontos_reais
                            pontos_fracos.append({
                                "id": qid, "pergunta": questoes.get(qid),
                                "valor": valor, "obtido": pontos_reais,
                                "maximo": max_possivel, "deficit": deficit
                            })
            
            pontos_fracos.sort(key=lambda x: x["deficit"], reverse=True)
            penalidades_detectadas.sort(key=lambda x: x["penalidade"])
            return pontos_fracos, penalidades_detectadas
        except Exception:
            return [], []

    def calcular_evolucao_pontos(self, dimensao):
        conn = self.obter_conexao(dimensao)
        if not conn: return []
        cursor = conn.cursor()
        anos_validos = [2023, 2024, 2025, 2026, 2027]
        dados_anos = []
        
        try:
            for ano in anos_validos:
                cursor.execute("SELECT SUM(pontos) FROM respostas WHERE ano = ? AND pontos > 0", (ano,))
                res_bruto = cursor.fetchone()[0]
                pontos_brutos = float(res_bruto) if res_bruto else 0.0

                cursor.execute("SELECT SUM(pontos) FROM respostas WHERE ano = ? AND pontos < 0", (ano,))
                res_penalidade = cursor.fetchone()[0]
                penalidades_negativas = float(res_penalidade) if res_penalidade else 0.0

                total_liquido = pontos_brutos + penalidades_negativas
                if total_liquido < 0: total_liquido = 0.0
                
                max_dim = sum(self.pontuacoes_maximas_por_dimensao.get(dimensao, {}).values()) or 100
                p_perc = (total_liquido / max_dim) * 100
                
                if p_perc <= 50:    faixa, cor = "C",  "rgba(239, 68, 68, 0.85)"
                elif p_perc <= 60:  faixa, cor = "C+", "rgba(249, 115, 22, 0.85)"
                elif p_perc <= 75:  faixa, cor = "B",  "rgba(229, 191, 5, 0.85)"
                elif p_perc <= 90:  faixa, cor = "B+", "rgba(34, 197, 94, 0.85)"
                else:               faixa, cor = "A",  "rgba(22, 163, 74, 0.85)"
                
                dados_anos.append({
                    "ano": ano, "bruto": pontos_brutos, "penalidade": penalidades_negativas,
                    "liquido": total_liquido, "faixa": faixa, "cor_faixa": cor
                })
            return dados_anos
        except Exception:
            return []

def mostrar_chat_hal():
    if "hal_sistema" not in st.session_state:
        st.session_state.hal_sistema = SistemaHAL()
    sistema = st.session_state.hal_sistema

    if "hal_chat_history" not in st.session_state:
        st.session_state.hal_chat_history = []

    st.markdown(
        """
        <style>
        .chat-wrapper { max-width: 850px; margin: 0 auto; font-family: -apple-system, sans-serif; }
        .chat-bubble-user { background-color: #f4f4f4; color: #1d1d1f; padding: 14px 18px; border-radius: 18px; display: inline-block; max-width: 80%; margin-bottom: 20px; float: right; clear: both; }
        .chat-bubble-ia { display: flex; gap: 16px; margin-bottom: 25px; clear: both; align-items: flex-start; }
        .avatar-ia { background-color: #10a37f; color: white; width: 36px; height: 36px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-weight: bold; font-size: 14px; flex-shrink: 0; }
        .content-ia { color: #2d3748; font-size: 15px; line-height: 1.6; width: 100%; }
        .card-ponto-fraco { background-color: #fff5f5; border-left: 4px solid #e53e3e; padding: 15px; border-radius: 6px; margin-bottom: 12px; font-size: 14px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }
        </style>
        """,
        unsafe_allow_html=True
    )

    st.markdown('<div class="chat-wrapper">', unsafe_allow_html=True)

    dimensoes_disponiveis = ["iGov-Ti", "iCidade", "i-Amb"]
    dimensao_selecionada = st.selectbox("📂 Selecione a Dimensão Operacional:", dimensoes_disponiveis, index=0)

    if dimensao_selecionada == "iGov-Ti":
        banco_ativo = "dados_igov_ti.db"
    elif dimensao_selecionada == "i-Amb":
        banco_ativo = "dados_iamb.db"
    else:
        banco_ativo = "dados_iegm_web.db"

    st.markdown(
        f"""
        <div class="chat-bubble-ia">
            <div class="avatar-ia">HAL</div>
            <div class="content-ia">
                Roteamento concluído com sucesso. Lendo dados de <b>{banco_ativo}</b> para processar o índice <b>{dimensao_selecionada}</b>.
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )

    st.markdown(f"### 📊 Histórico de Performance Real - {dimensao_selecionada}")
    historico_performance = sistema.calcular_evolucao_pontos(dimensao_selecionada)
    
    if historico_performance:
        eixo_x = [f"Ano {d['ano']}" for d in historico_performance]
        valores_liquidos = [d['liquido'] for d in historico_performance]
        cores = [d['cor_faixa'] for d in historico_performance]
        textos = [f"Faixa {d['faixa']}" for d in historico_performance]

        fig = go.Figure(data=[
            go.Bar(
                x=eixo_x, 
                y=valores_liquidos,
                text=textos,
                textposition='auto',
                marker_color=cores
            )
        ])
        fig.update_layout(
            margin=dict(l=20, r=20, t=20, b=20),
            height=300,
            yaxis_title="Pontuação Líquida",
            template="plotly_white"
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Nenhum dado estruturado foi retornado para a performance desta dimensão.")

    # ==============================================================================
    # PARTE RECUPERADA 1: Recuperação Segmentada de Respostas
    # ==============================================================================
    questoes_atuais = sistema.questoes_por_dimensao.get(dimensao_selecionada, {})
    ids_ordenados = sorted(list(questoes_atuais.keys()), key=lambda x: [float(n) for n in re.findall(r'\d+', x)] if re.search(r'\d+', x) else [0.0])
    opcoes_select = ["-- Selecione o item que deseja analisar --"] + [f"{q_id} - {questoes_atuais[q_id]}" for q_id in ids_ordenados]
    
    st.markdown("<br>", unsafe_allow_html=True)
    selecionado = st.selectbox(f"💬 Recuperar Resposta do Banco ({dimensao_selecionada}):", options=opcoes_select, key="sel_hal_split")

    if selecionado != "-- Selecione o item que deseja analisar --":
        id_alvo = selecionado.split(" - ")[0]
        historico = sistema.consultar_anos(dimensao_selecionada, id_alvo)
        dict_historico = dict(historico)

        st.markdown(f'<div class="chat-bubble-user">Qual o histórico do item {id_alvo}?</div>', unsafe_allow_html=True)

        anos_disponiveis = [2023, 2024, 2025, 2026, 2027]
        tabs = st.tabs([f"📅 Ano {ano}" for ano in anos_disponiveis])

        for i, ano in enumerate(anos_disponiveis):
            with tabs[i]:
                if ano in dict_historico:
                    st.success(f"**Resposta registrada:** {dict_historico[ano]}")
                elif str(ano) in dict_historico:
                    st.success(f"**Resposta registrada:** {dict_historico[str(ano)]}")
                else:
                    st.warning("Nenhum dado encontrado para este ano neste banco.")

    # ==============================================================================
    # PARTE RECUPERADA 2: Painel de Auditoria por Banco
    # ==============================================================================
    st.markdown("---")
    st.markdown(f"### 🚨 Painel de Diagnóstico de Gaps ({dimensao_selecionada})")
    ano_auditoria = st.selectbox("Selecione o Ano Fiscal para Auditar:", [2023, 2024, 2025, 2026, 2027], index=2)

    if st.button("🚀 Rastrear Vulnerabilidades", type="primary", use_container_width=True):
        dados_criticos, penalidades = sistema.analisar_pontos_fracos(ano_auditoria, dimensao_selecionada)
        
        if dados_criticos or penalidades:
            if penalidades:
                st.markdown("#### ⚠️ Penalidades Ativas")
                for pen in penalidades:
                    st.markdown(
                        f"""
                        <div class="card-ponto-fraco" style="border-left-color: #e53e3e; background-color: #fff5f5;">
                            <span style="font-weight:bold; color:#c53030; font-size:14px;">⚠️ ITEM {pen['id']} - PENALIDADE APLICADA</span><br>
                            <b>Valor salvo em banco:</b> "{pen['valor']}"<br>
                            Impacto financeiro/operacional: <span style="color:red; font-weight:bold;">{pen['penalidade']} pontos</span><br>
                            <small style="color:#4a5568;"><b>Enunciado:</b> {pen['pergunta']}</small>
                        </div>
                        """, unsafe_allow_html=True
                    )

            if dados_criticos:
                st.markdown("#### 📉 Gaps de Pontuação Máxima")
                for item in dados_criticos:
                    st.markdown(
                        f"""
                        <div class="card-ponto-fraco" style="border-left-color: #dd6b20; background-color: #fffaf0;">
                            <span style="font-weight:bold; color:#dd6b20; font-size:14px;">🔴 ITEM {item['id']} COM DEFICIT</span><br>
                            <b>Valor salvo em banco:</b> "{item['valor']}"<br>
                            Pontuação: {item['obtido']} de {item['maximo']} (Perda de <b>{item['deficit']}</b> pontos).<br>
                            <small style="color:#4a5568;"><b>Enunciado:</b> {item['pergunta']}</small>
                        </div>
                        """, unsafe_allow_html=True
                    )
        else:
            st.info(f"Nenhuma perda ou penalidade registrada para {dimensao_selecionada} no ano {ano_auditoria}.")

    # ==============================================================================
    # ÁREA DE DIÁLOGO DO ASSISTENTE CHAT
    # ==============================================================================
    st.markdown("---")
    st.markdown("### 💬 Conversar com Assistente HAL")

    for msg in st.session_state.hal_chat_history:
        if msg["role"] == "user":
            st.markdown(f'<div class="chat-bubble-user">{msg["content"]}</div>', unsafe_allow_html=True)
        else:
            st.markdown(
                f"""
                <div class="chat-bubble-ia">
                    <div class="avatar-ia">HAL</div>
                    <div class="content-ia">{msg["content"]}</div>
                </div>
                """,
                unsafe_allow_html=True
            )

    if prompt := st.chat_input("Pergunte algo ao HAL ou digite 'pontos fracos 2025'..."):
        st.markdown(f'<div class="chat-bubble-user">{prompt}</div>', unsafe_allow_html=True)
        st.session_state.hal_chat_history.append({"role": "user", "content": prompt})
        
        prompt_limpo = prompt.lower()
        match_ano = re.search(r'\b(202[3-7])\b', prompt_limpo)
        
        if "ponto" in prompt_limpo and match_ano:
            ano_busca = int(match_ano.group(1))
            pontos_fracos, penalidades = sistema.analisar_pontos_fracos(ano_busca, dimensao_selecionada)
            resposta_ia = f"### 🔍 Diagnóstico Rápido ({dimensao_selecionada} - {ano_busca})<br><br>"
            
            if penalidades:
                resposta_ia += "⚠️ **Penalidades cruciais:**<br>"
                for pen in penalidades[:2]:
                    resposta_ia += f"- **Item {pen['id']}**: {pen['pergunta']} ({pen['penalidade']} pts)<br>"
            if pontos_fracos:
                resposta_ia += "<br>📉 **Déficits prioritários:**<br>"
                for pt in pontos_fracos[:3]:
                    resposta_ia += f"- **Item {pt['id']}**: Defasagem de {pt['deficit']} pts.<br>"
            if not penalidades and not pontos_fracos:
                resposta_ia += "Tudo limpo! Não identifiquei perdas de pontuação estruturadas no banco."
        else:
            resposta_ia = f"Processando dados de **{dimensao_selecionada}**. Para auditoria automatizada via prompt, especifique comandos contendo o ano desejado."

        st.markdown(
            f"""
            <div class="chat-bubble-ia">
                <div class="avatar-ia">HAL</div>
                <div class="content-ia">{resposta_ia}</div>
            </div>
            """,
            unsafe_allow_html=True
        )
        st.session_state.hal_chat_history.append({"role": "assistant", "content": resposta_ia})
        
    st.markdown('</div>', unsafe_allow_html=True)