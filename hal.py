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
        """Busca a resposta real consultando a tabela específica da dimensão selecionada."""
        mapa_tabelas = {
            "iCidade": "respostas_iplan",
            "iGov-Ti": "respostas_igov",
            "i-Amb": "respostas_iamb",
            "iEduc": "respostas_ieduc",
            "iFiscal": "respostas_ifiscal",
            "iSaude": "respostas_isaude",
        }

        tabela = mapa_tabelas.get(dimensao)
        if not tabela:
            return {
                "resposta": "Dimensão desconhecida",
                "detalhes": (
                    f"Tabela para a dimensão '{dimensao}' não foi configurada."
                ),
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
                # Consulta SQL apontando para a tabela específica e usando 'id'
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

                    if (
                        comentarios
                        and comentarios != "EMPTY_STRING"
                        and comentarios != "[]"
                    ):
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
                            f"Nenhum registro encontrado na tabela '{tabela}'"
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
