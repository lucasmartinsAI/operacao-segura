import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest

AQUI = os.path.dirname(os.path.abspath(__file__))
TMP = tempfile.mkdtemp()
for arq in ("config.json", "catalogo.json"):
    shutil.copy(os.path.join(AQUI, arq), os.path.join(TMP, arq))
os.environ["RODADAS_BASE"] = TMP          # todas as escritas dos testes vao para uma pasta temporaria

import rodadas  # noqa: E402


def roda(*argv):
    saida = io.StringIO()
    with contextlib.redirect_stdout(saida):
        codigo = rodadas.main(list(argv))
    return codigo, saida.getvalue()


def estado(maquina):
    return rodadas.contexto()[2].estado(maquina)["status"]


def limpa():
    for pasta in ("estado", "saidas", "auditoria"):
        shutil.rmtree(os.path.join(TMP, pasta), ignore_errors=True)


def linhas_auditoria():
    pasta = os.path.join(TMP, "auditoria")
    out = []
    for nome in sorted(os.listdir(pasta)) if os.path.isdir(pasta) else []:
        with open(os.path.join(pasta, nome), encoding="utf-8") as f:
            out += [json.loads(l) for l in f]
    return out


class TestOperacaoSegura(unittest.TestCase):
    def setUp(self):
        limpa()

    def test_dry_run_nao_liga_nada_e_e_auditado(self):
        codigo, texto = roda("lancar", "prazo-rapida")
        self.assertEqual(codigo, 0)
        self.assertIn("DRY-RUN", texto)
        self.assertEqual(estado("maquina-a"), "DESLIGADA")
        self.assertFalse(os.path.isdir(os.path.join(TMP, "saidas")))
        ult = linhas_auditoria()[-1]
        self.assertEqual((ult["comando"], ult["muda_algo"], ult["resultado"]["executado"]), ("lancar", False, False))

    def test_rodada_fora_do_catalogo_e_recusada(self):
        codigo, texto = roda("lancar", "rodada-inexistente", "--confirmo")
        self.assertEqual(codigo, 1)
        self.assertIn("fora do catalogo", texto)

    def test_maquina_fora_da_lista_e_recusada(self):
        codigo, texto = roda("desligar", "maquina-x", "--confirmo")
        self.assertEqual(codigo, 1)
        self.assertIn("fora da lista permitida", texto)

    def test_corte_sem_margem_e_recusado(self):
        codigo, texto = roda("lancar", "prazo-rapida", "--corte-horas", "2.1", "--confirmo")   # estimativa 2,0 h; minimo 2,4 h
        self.assertEqual(codigo, 1)
        self.assertIn("RECUSADO", texto)
        self.assertEqual(estado("maquina-a"), "DESLIGADA")

    def test_execucao_concluida(self):
        codigo, texto = roda("lancar", "prazo-rapida", "--confirmo")
        self.assertEqual(codigo, 0)
        self.assertIn("CONCLUIDA", texto)
        self.assertEqual(estado("maquina-a"), "DESLIGADA")             # desliga sozinha
        ult = linhas_auditoria()[-1]
        self.assertTrue(ult["muda_algo"])
        self.assertAlmostEqual(ult["resultado"]["custo"], 2.0 * 4.0)    # 2 h x 4 creditos/h
        pasta = os.path.join(TMP, "saidas", ult["resultado"]["id"])
        self.assertTrue(os.path.exists(os.path.join(pasta, "resultado.json")))

    def test_provedor_corta_antes_do_fim_e_nao_ha_resultado(self):
        codigo, texto = roda("lancar", "prazo-rapida", "--corte-horas", "1.0", "--sem-margem", "--confirmo")
        self.assertEqual(codigo, 2)
        self.assertIn("CORTADA PELO PROVEDOR", texto)
        self.assertEqual(estado("maquina-a"), "DESLIGADA")
        ult = linhas_auditoria()[-1]
        self.assertFalse(ult["resultado"]["concluida"])
        self.assertAlmostEqual(ult["resultado"]["custo"], 1.0 * 4.0)    # paga ate o corte e nao recebe resultado
        self.assertTrue(ult["parametros"]["sem_margem"])                 # a excecao fica registrada
        pasta = os.path.join(TMP, "saidas", ult["resultado"]["id"])
        self.assertFalse(os.path.exists(os.path.join(pasta, "resultado.json")))

    def test_nao_liga_maquina_ja_ligada(self):
        rodadas.contexto()[2].ligar("maquina-a")
        codigo, texto = roda("lancar", "prazo-rapida", "--confirmo")
        self.assertEqual(codigo, 1)
        self.assertIn("ja esta ligada", texto)

    def test_resultado_reprodutivel_pela_semente(self):
        roda("lancar", "prazo-rapida", "--confirmo")
        primeiro = linhas_auditoria()[-1]["resultado"]["resultado"]
        limpa()
        roda("lancar", "prazo-rapida", "--confirmo")
        self.assertEqual(primeiro, linhas_auditoria()[-1]["resultado"]["resultado"])

    def test_progresso_diagnostica_finalizada_e_corte(self):
        roda("lancar", "prazo-rapida", "--confirmo")
        _, texto = roda("progresso")
        self.assertIn("FINALIZADA", texto)
        limpa()
        roda("lancar", "prazo-rapida", "--corte-horas", "1.0", "--sem-margem", "--confirmo")
        _, texto = roda("progresso")
        self.assertIn("NAO finalizou", texto)

    def test_auditoria_so_acrescenta(self):
        roda("status")
        antes = len(linhas_auditoria())
        roda("estimar", "prazo-completa")
        roda("lancar", "prazo-completa")
        depois = linhas_auditoria()
        self.assertEqual(len(depois), antes + 2)
        self.assertEqual([l["comando"] for l in depois][-2:], ["estimar", "lancar"])


if __name__ == "__main__":
    unittest.main()
