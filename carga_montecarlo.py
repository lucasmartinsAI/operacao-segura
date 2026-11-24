"""
carga_montecarlo.py - a carga de trabalho do exemplo: risco de prazo de um projeto fictivo (Monte Carlo).

O projeto tem etapas em sequencia; dentro de uma etapa, as tarefas correm em paralelo (a etapa dura o tempo da mais lenta).
Cada tarefa tem duracao incerta, descrita por (minimo, mais provavel, maximo) em dias, com distribuicao triangular.
Todos os numeros sao sinteticos.
"""
import random


def simular_prazo(rng, etapas):
    total = 0.0
    for tarefas in etapas:
        total += max(rng.triangular(minimo, maximo, provavel) for minimo, provavel, maximo in tarefas)
    return total


def simular_lote(rng, n, etapas):
    return [simular_prazo(rng, etapas) for _ in range(n)]


def percentil(valores_ordenados, p):
    i = min(len(valores_ordenados) - 1, int(p * len(valores_ordenados)))
    return valores_ordenados[i]


def resumir(amostras):
    v = sorted(amostras)
    return {
        "simulacoes": len(v),
        "media_dias": round(sum(v) / len(v), 2),
        "p50_dias": round(percentil(v, 0.50), 2),
        "p80_dias": round(percentil(v, 0.80), 2),
        "p95_dias": round(percentil(v, 0.95), 2),
    }


if __name__ == "__main__":
    etapas = [[(2, 4, 8)], [(3, 5, 10), (2, 3, 6)], [(1, 2, 5)]]
    print(resumir(simular_lote(random.Random(1), 10000, etapas)))
