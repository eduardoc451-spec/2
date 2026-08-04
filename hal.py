import psycopg2
import psycopg2.extras
import streamlit as st

# URL DIRETA DO SEU NEON
NEON_URI = "postgresql://neondb_owner:npg_beMKhVR2N4wo@ep-divine-sky-awx1636y-pooler.c-12.us-east-1.aws.neon.tech/neondb?sslmode=require"


def criar_conexao_direta():
    """Função isolada para garantir conexão sem depender de estado do objeto"""
    try:
        conn = psycopg2.connect(NEON_URI)
        return conn, None
    except Exception as e:
        return None, str(e)


class SistemaHAL:

    def __init__(self):
        self.questoes_por_dimensao = {}
        self.carregar_dicionarios_globais()

    def carregar_dicionarios_globais(self):
        self.questoes_por_dimensao = {
            "iCidade": {
                "1.0": (
                    "Foi criada a Coordenadoria Municipal de Proteção e Defesa"
                    " Civil (COMPDEC)..."
                ),
                "1.3": (
                    "A COMPDEC ou órgão similar está associada ou subordinada"
                    " a qual secretaria/diretoria?"
                ),
            },
            "iGov-Ti": {
                "1.0": (
                    "A Prefeitura possui uma área ou setor que cuida de"
                    " Tecnologia da Informação..."
                ),
            },
            "i-Amb": {
                "1.0": (
                    "Existe estrutura organizacional instalada para tratar de"
                    " assuntos ligados ao Meio Ambiente Municipal?"
                ),
            },
        }

    def get_db_connection(self):
        return criar_conexao_direta()

    def get_dimensoes(self):
        if hasattr(self, "questoes_por_dimensao") and isinstance(
            self.questoes_por_dimensao, dict
        ):
            return list(self.questoes_por_dimensao.keys())
        return ["iCidade", "iGov-Ti", "i-Amb"]

    def get_quesitos_por_dimensao(self, dimensao):
        if (
            hasattr(self, "questoes_por_dimensao")
            and dimensao in self.questoes_por_dimensao
        ):
            return [
                f"{codigo} - {texto}"
                for codigo, texto in self.questoes_por_dimensao[
                    dimensao
                ].items()
            ]
        return []

    def get_resposta_municipio(self, dimensao, codigo_quesito, ano):
        """Busca a resposta real no banco de dados Neon consultando a tabela específica de cada dimensão."""
        mapa_tabelas = {
            "iGov-Ti": "respostas_igov",
            "i-Amb": "respostas_iamb",
            "iCidade": "respostas_iplan",
        }

        tabela = mapa_tabelas.get(dimensao)
        if not tabela:
            return {
                "resposta": "Dimensão desconhecida",
                "detalhes": f"Tabela para a dimensão {dimensao} não configurada.",
                "pontuacao_obtida": 0,
            }

        conn, erro = criar_conexao_direta()
        if not conn:
            return {
                "resposta": "Sem conexão",
                "detalhes": (
                    f"Não foi possível conectar ao banco de dados Neon: {erro}"
                ),
                "pontuacao_obtida": 0,
            }

        try:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                query = f"""
                    SELECT id, ano, valor, pontos, link, comentarios 
                    FROM {tabela} 
                    WHERE id = %s AND ano = %s;
                """
                cur.execute(query, (str(codigo_quesito), int(ano)))
                resultado = cur.fetchone()

                if resultado:
                    detalhe_texto = []
                    link = resultado.get("link")
                    comentarios = resultado.get("comentarios")

                    if link and link != "EMPTY_STRING":
                        detalhe_texto.append(f"Link: {link}")
                    if comentarios and comentarios != "EMPTY_STRING":
                        detalhe_texto.append(f"Comentários: {comentarios}")

                    txt_detalhes = (
                        " | ".join(detalhe_texto)
                        if detalhe_texto
                        else "Sem observações adicionais."
                    )

                    return {
                        "resposta": (
                            resultado.get("valor")
                            if resultado.get("valor")
                            else "Sem resposta"
                        ),
                        "detalhes": txt_detalhes,
                        "pontuacao_obtida": (
                            resultado.get("pontos")
                            if resultado.get("pontos") is not None
                            else 0
                        ),
                    }
                else:
                    return {
                        "resposta": "Sem registro",
                        "detalhes": (
                            f"Nenhum registro encontrado na tabela {tabela}"
                            f" para o item {codigo_quesito} em {ano}."
                        ),
                        "pontuacao_obtida": 0,
                    }
        except Exception as e:
            return {
                "resposta": "Erro na consulta",
                "detalhes": f"Erro SQL ao consultar {tabela}: {e}",
                "pontuacao_obtida": 0,
            }
        finally:
            if conn:
                conn.close()


def mostrar_chat_hal():
    st.title("🤖 Assistente HAL - Análise & Diagnóstico")

    if (
        "sistema_hal" not in st.session_state
        or "seu_host.neon.tech" in str(st.session_state.sistema_hal)
    ):
        st.session_state.sistema_hal = SistemaHAL()

    sistema = st.session_state.sistema_hal

    with st.expander("🔌 Status da Conexão com o Banco", expanded=True):
        conn, erro_conexao = criar_conexao_direta()
        if conn:
            st.success("✅ Conectado ao PostgreSQL (Neon) com sucesso!")
            conn.close()
        else:
            st.error("❌ Falha ao conectar no banco Neon!")
            st.code(f"Erro: {erro_conexao}", language="bash")

    st.subheader("📊 Consulta por Dimensão e Quesito")

    lista_dimensoes = sistema.get_dimensoes()
    lista_anos = [2026, 2025, 2024, 2023]

    col1, col2, col3 = st.columns([1, 2.5, 1])

    with col1:
        dimensao_sel = st.selectbox("Dimensão:", options=lista_dimensoes)

    with col2:
        lista_quesitos_formatados = sistema.get_quesitos_por_dimensao(
            dimensao_sel
        )
        quesito_formatado_sel = st.selectbox(
            "Quesito / Pergunta:", options=lista_quesitos_formatados
        )
        codigo_quesito_sel = (
            quesito_formatado_sel.split(" - ")[0]
            if quesito_formatado_sel
            else ""
        )

    with col3:
        ano_sel = st.selectbox("Ano:", options=lista_anos)

    if quesito_formatado_sel:
        dados_resposta = sistema.get_resposta_municipio(
            dimensao_sel, codigo_quesito_sel, ano_sel
        )

        with st.container(border=True):
            st.markdown(f"### 📍 Resposta do Município ({ano_sel})")
            st.caption(f"**Item:** {quesito_formatado_sel}")
            st.divider()

            col_res1, col_res2 = st.columns([3, 1])
            with col_res1:
                st.write(
                    "**Resposta Cadastrada:**"
                    f" {dados_resposta.get('resposta', 'Sem registro')}"
                )
                st.write(
                    "**Detalhamento:**"
                    f" {dados_resposta.get('detalhes', 'Sem observações')}"
                )
            with col_res2:
                pontos = dados_resposta.get("pontuacao_obtida", 0)
                st.metric("Pontuação", pontos)

    st.divider()

    st.subheader("💬 Diagnóstico com o Assistente HAL")

    if "mensagens" not in st.session_state:
        st.session_state.mensagens = []

    for msg in st.session_state.mensagens:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])

    if prompt := st.chat_input(
        f"Pergunte ao HAL sobre o quesito {codigo_quesito_sel} ({ano_sel})..."
    ):
        st.session_state.mensagens.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.write(prompt)

        with st.chat_message("assistant"):
            texto_pergunta = sistema.questoes_por_dimensao.get(
                dimensao_sel, {}
            ).get(codigo_quesito_sel, "")

            prompt_contextualizado = (
                f"Contexto: Dimensão {dimensao_sel}, Quesito"
                f" {codigo_quesito_sel} ('{texto_pergunta}'), Ano"
                f" {ano_sel}.\nPergunta do usuário: {prompt}"
            )

            resposta = (
                f"Analisando **{dimensao_sel}** (Item {codigo_quesito_sel} -"
                f" {ano_sel}):\n\nRecebi sua pergunta: *\"{prompt}\"*."
            )

            st.write(resposta)
            st.session_state.mensagens.append(
                {"role": "assistant", "content": resposta}
            )


if __name__ == "__main__":
    mostrar_chat_hal()
