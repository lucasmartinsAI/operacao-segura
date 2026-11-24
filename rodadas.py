#!/usr/bin/env python3
"""
rodadas.py - operar rodadas pagas com controle humano. Sem dependencias (so biblioteca padrao).

Comandos:
  status                         estado das maquinas
  estimar  <rodada>              tempo, custo estimado, teto de custo e checagem do corte
  lancar   <rodada> [--confirmo] liga a maquina, roda a carga e desliga. SEM --confirmo so mostra o plano (dry-run)
  progresso                      le o ultimo sinal de progresso e diz se esta tudo bem
  desligar <maquina> [--confirmo]
  auditoria [--ultimas N]        ultimas linhas do registro de operacoes

Travas: lista fechada de rodadas e de maquinas; dry-run por padrao; corte de tempo definido no provedor,
com margem minima sobre a estimativa; registro de auditoria de tudo, inclusive dos dry-runs.
"""
import argparse
import datetime
import json
import os
import random
import sys
import time

import carga_montecarlo as carga
from provedor_simulado import ErroProvedor, ProvedorSimulado

BASE = os.environ.get("RODADAS_BASE", os.path.dirname(os.path.abspath(__file__)))


def agora():
    return datetime.datetime.now(datetime.timezone.utc)


def le_json(*partes):
    with open(os.path.join(BASE, *partes), encoding="utf-8") as f:
        return json.load(f)


def contexto():
    cfg, cat = le_json("config.json"), le_json("catalogo.json")
    return cfg, cat["rodadas"], ProvedorSimulado(BASE, cfg["maquinas"].keys())


def auditar(comando, parametros, resultado, mudou):
    """Registro so de acrescimo: uma linha JSON por operacao, inclusive dry-runs."""
    pasta = os.path.join(BASE, "auditoria")
    os.makedirs(pasta, exist_ok=True)
    linha = {"quando_utc": agora().isoformat(), "comando": comando, "parametros": parametros,
             "muda_algo": mudou, "resultado": resultado}
    with open(os.path.join(pasta, agora().strftime("%Y-%m") + ".jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(linha, ensure_ascii=False) + "\n")


def horas_estimadas(r):
    return round(r["lotes"] * r["horas_por_lote"], 4)


def cmd_status(args):
    cfg, _, prov = contexto()
    for m, d in cfg["maquinas"].items():
        e = prov.estado(m)
        aviso = "  <-- LIGADA = COBRANDO" if e["status"] == "LIGADA" else ""
        corte = f" corte={e['corte_horas']}h" if e["corte_horas"] else ""
        print(f"{m:<10} {e['status']:<9} {d['preco_hora']:>5.2f}/h{corte}{aviso}")
    auditar("status", {}, {"ok": True}, False)
    return 0


def plano(rodada_id, r, cfg, corte):
    preco = cfg["maquinas"][r["maquina"]]["preco_hora"]
    est = horas_estimadas(r)
    return {"rodada": rodada_id, "maquina": r["maquina"], "horas_estimadas": est, "custo_estimado": round(est * preco, 2),
            "corte_horas": corte, "custo_teto": round(corte * preco, 2),
            "margem_ok": corte >= cfg["margem_minima_corte"] * est, "margem_minima": cfg["margem_minima_corte"]}


def escolhe_rodada(rodada_id, rodadas):
    if rodada_id not in rodadas:
        raise ErroProvedor(f"rodada '{rodada_id}' fora do catalogo: {', '.join(rodadas)}")
    return rodadas[rodada_id]


def cmd_estimar(args):
    cfg, rodadas, _ = contexto()
    r = escolhe_rodada(args.rodada, rodadas)
    p = plano(args.rodada, r, cfg, args.corte_horas or r["corte_horas"])
    print(f"Rodada:   {args.rodada} - {r['descricao']}")
    print(f"Maquina:  {p['maquina']}")
    print(f"Estimativa: {p['horas_estimadas']} h  ->  ~{p['custo_estimado']} creditos")
    print(f"Corte:      {p['corte_horas']} h  ->  teto {p['custo_teto']} creditos")
    print(f"Margem do corte sobre a estimativa: {'OK' if p['margem_ok'] else 'INSUFICIENTE'} (minimo {p['margem_minima']}x)")
    auditar("estimar", {"rodada": args.rodada}, p, False)
    return 0


def escreve_farol(pasta, exec_id, maquina, prontos, total, horas):
    farol = {"id": exec_id, "maquina": maquina, "hora_utc": agora().isoformat(),
             "lotes_prontos": prontos, "lotes_total": total, "horas_simuladas": round(horas, 4)}
    with open(os.path.join(pasta, "farol.json"), "w", encoding="utf-8") as f:
        json.dump(farol, f, ensure_ascii=False)


def executa(rodada_id, r, cfg, prov, corte, ritmo):
    maquina = r["maquina"]
    exec_id = f"{rodada_id}_{agora().strftime('%Y%m%dT%H%M%S')}"
    pasta = os.path.join(BASE, "saidas", exec_id)
    os.makedirs(pasta, exist_ok=True)
    prov.definir_corte(maquina, corte)          # 1) corte definido ANTES de ligar, no provedor
    prov.ligar(maquina)                         # 2) liga
    rng, amostras, horas, concluida = random.Random(r["semente"]), [], 0.0, True
    try:
        for i in range(1, r["lotes"] + 1):      # 3) roda a carga, lote a lote
            horas = round(horas + r["horas_por_lote"], 6)
            if horas > corte + 1e-9:            # o provedor corta, mesmo que a carga ainda nao tenha terminado
                horas, concluida = corte, False
                break
            amostras.extend(carga.simular_lote(rng, r["simulacoes_por_lote"], r["etapas"]))
            escreve_farol(pasta, exec_id, maquina, i, r["lotes"], horas)
            if ritmo:
                time.sleep(ritmo)
    finally:
        prov.desligar(maquina)                  # 4) desliga sempre, inclusive em erro
    custo = round(horas * cfg["maquinas"][maquina]["preco_hora"], 2)
    resultado = None
    if concluida:
        resultado = carga.resumir(amostras)
        with open(os.path.join(pasta, "resultado.json"), "w", encoding="utf-8") as f:
            json.dump(resultado, f, ensure_ascii=False, indent=2)
    return {"id": exec_id, "concluida": concluida, "horas_cobradas": horas, "custo": custo, "resultado": resultado}


def cmd_lancar(args):
    cfg, rodadas, prov = contexto()
    r = escolhe_rodada(args.rodada, rodadas)
    corte = args.corte_horas or r["corte_horas"]
    p = plano(args.rodada, r, cfg, corte)
    params = {"rodada": args.rodada, "corte_horas": corte, "sem_margem": args.sem_margem, "confirmo": args.confirmo}
    print(f"PLANO: {args.rodada} na {p['maquina']} | estimativa {p['horas_estimadas']} h (~{p['custo_estimado']} cred.) | "
          f"corte {corte} h (teto {p['custo_teto']} cred.)")
    if not p["margem_ok"] and not args.sem_margem:
        print(f"RECUSADO: o corte ({corte} h) e menor que {p['margem_minima']}x a estimativa ({p['horas_estimadas']} h). "
              f"A maquina seria desligada antes de a rodada terminar. Aumente o corte, ou use --sem-margem (fica registrado).")
        auditar("lancar", params, {"recusado": "corte sem margem"}, False)
        return 1
    if prov.estado(p["maquina"])["status"] != "DESLIGADA":
        print("RECUSADO: a maquina ja esta ligada.")
        auditar("lancar", params, {"recusado": "maquina ligada"}, False)
        return 1
    if not args.confirmo:
        print("DRY-RUN: nada foi ligado nem executado. Para executar, repita com --confirmo.")
        auditar("lancar", params, {"executado": False, **p}, False)
        return 0
    res = executa(args.rodada, r, cfg, prov, corte, args.ritmo_segundos)
    if res["concluida"]:
        print(f"CONCLUIDA ({res['id']}): {res['horas_cobradas']} h cobradas, custo {res['custo']} creditos")
        print(f"  resultado: {json.dumps(res['resultado'], ensure_ascii=False)}")
    else:
        print(f"CORTADA PELO PROVEDOR ({res['id']}) apos {res['horas_cobradas']} h; custo {res['custo']} creditos; SEM resultado.")
    auditar("lancar", params, res, True)
    return 0 if res["concluida"] else 2


def cmd_progresso(args):
    cfg, _, prov = contexto()
    pasta_saidas = os.path.join(BASE, "saidas")
    if not os.path.isdir(pasta_saidas) or not os.listdir(pasta_saidas):
        print("Nenhuma execucao ainda.")
        return 0
    ultimo = sorted(os.listdir(pasta_saidas))[-1]
    pasta = os.path.join(pasta_saidas, ultimo)
    terminou = os.path.exists(os.path.join(pasta, "resultado.json"))
    farol_arq = os.path.join(pasta, "farol.json")
    if not os.path.exists(farol_arq):
        print(f"{ultimo}: ainda sem sinal.")
        return 0
    with open(farol_arq, encoding="utf-8") as f:
        farol = json.load(f)
    idade = (agora() - datetime.datetime.fromisoformat(farol["hora_utc"])).total_seconds() / 60
    ligada = prov.estado(farol["maquina"])["status"] == "LIGADA"
    print(f"{ultimo}: {farol['lotes_prontos']}/{farol['lotes_total']} lotes | {farol['horas_simuladas']} h | ultimo sinal ha {idade:.1f} min")
    if terminou:
        diag = "OK: rodada FINALIZADA."
    elif ligada and idade <= cfg["limite_sem_sinal_minutos"]:
        diag = "OK: maquina ligada e dando sinal (rodando)."
    elif ligada:
        diag = f"ALERTA: maquina ligada mas SEM SINAL ha {idade:.1f} min (pode ter travado)."
    else:
        diag = "ALERTA: maquina desligada e a rodada NAO finalizou (caiu ou foi cortada)."
    print(diag)
    auditar("progresso", {"execucao": ultimo}, {"diagnostico": diag}, False)
    return 0


def cmd_desligar(args):
    _, _, prov = contexto()
    estado = prov.estado(args.maquina)
    print(f"PLANO: desligar {args.maquina} (estado atual: {estado['status']}). Se houver rodada em andamento, sera interrompida.")
    if not args.confirmo:
        print("DRY-RUN: nada foi executado. Para executar, repita com --confirmo.")
        auditar("desligar", {"maquina": args.maquina, "confirmo": False}, {"executado": False}, False)
        return 0
    prov.desligar(args.maquina)
    print(f"{args.maquina} desligada.")
    auditar("desligar", {"maquina": args.maquina, "confirmo": True}, {"executado": True}, True)
    return 0


def cmd_auditoria(args):
    pasta = os.path.join(BASE, "auditoria")
    linhas = []
    if os.path.isdir(pasta):
        for nome in sorted(os.listdir(pasta)):
            with open(os.path.join(pasta, nome), encoding="utf-8") as f:
                linhas += f.read().splitlines()
    for linha in linhas[-args.ultimas:]:
        d = json.loads(linha)
        print(f"{d['quando_utc'][:19]}  {d['comando']:<10} muda_algo={d['muda_algo']}  {json.dumps(d['parametros'], ensure_ascii=False)}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Operacao segura de rodadas (provedor simulado)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status").set_defaults(f=cmd_status)
    e = sub.add_parser("estimar"); e.add_argument("rodada"); e.add_argument("--corte-horas", type=float); e.set_defaults(f=cmd_estimar)
    l = sub.add_parser("lancar"); l.add_argument("rodada"); l.add_argument("--confirmo", action="store_true")
    l.add_argument("--corte-horas", type=float); l.add_argument("--sem-margem", action="store_true")
    l.add_argument("--ritmo-segundos", type=float, default=0.0, help="pausa por lote, para acompanhar com 'progresso'")
    l.set_defaults(f=cmd_lancar)
    sub.add_parser("progresso").set_defaults(f=cmd_progresso)
    d = sub.add_parser("desligar"); d.add_argument("maquina"); d.add_argument("--confirmo", action="store_true"); d.set_defaults(f=cmd_desligar)
    a = sub.add_parser("auditoria"); a.add_argument("--ultimas", type=int, default=10); a.set_defaults(f=cmd_auditoria)
    args = ap.parse_args(argv)
    try:
        return args.f(args)
    except ErroProvedor as erro:
        print(f"ERRO: {erro}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
