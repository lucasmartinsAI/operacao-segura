"""
provedor_simulado.py - um "provedor de nuvem" de brinquedo, para praticar a operacao segura sem gastar nada.

Guarda o estado de cada maquina num arquivo JSON (estado/maquinas.json). Faz o que um provedor real faz,
nos pontos que importam para a seguranca:
  - so existem as maquinas da lista permitida (a lista fechada vem do config.json);
  - uma maquina so liga se estiver desligada;
  - o corte de tempo e definido ANTES de ligar e e aplicado pelo provedor, fora da carga de trabalho.

Para usar um provedor real, troque esta classe por outra com os mesmos quatro metodos
(estado, definir_corte, ligar, desligar), chamando a CLI ou a API do provedor.
"""
import json
import os


class ErroProvedor(Exception):
    pass


class ProvedorSimulado:
    def __init__(self, base, maquinas):
        self.arquivo = os.path.join(base, "estado", "maquinas.json")
        self.maquinas = list(maquinas)

    def _le(self):
        if os.path.exists(self.arquivo):
            with open(self.arquivo, encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _grava(self, dados):
        os.makedirs(os.path.dirname(self.arquivo), exist_ok=True)
        with open(self.arquivo, "w", encoding="utf-8") as f:
            json.dump(dados, f, indent=2, ensure_ascii=False)

    def _valida(self, maquina):
        if maquina not in self.maquinas:
            raise ErroProvedor(f"maquina '{maquina}' fora da lista permitida: {', '.join(self.maquinas)}")

    def estado(self, maquina):
        self._valida(maquina)
        return self._le().get(maquina, {"status": "DESLIGADA", "corte_horas": None})

    def definir_corte(self, maquina, horas):
        self._valida(maquina)
        if self.estado(maquina)["status"] != "DESLIGADA":
            raise ErroProvedor("o corte so pode ser definido com a maquina desligada")
        dados = self._le()
        dados[maquina] = {"status": "DESLIGADA", "corte_horas": horas}
        self._grava(dados)

    def ligar(self, maquina):
        self._valida(maquina)
        atual = self.estado(maquina)
        if atual["status"] != "DESLIGADA":
            raise ErroProvedor(f"a maquina '{maquina}' ja esta ligada")
        dados = self._le()
        dados[maquina] = {"status": "LIGADA", "corte_horas": atual["corte_horas"]}
        self._grava(dados)

    def desligar(self, maquina):
        self._valida(maquina)
        dados = self._le()
        dados[maquina] = {"status": "DESLIGADA", "corte_horas": None}
        self._grava(dados)
