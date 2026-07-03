"""
ingest_metrics.py — Instrumentação da ingestão (em memória, sem dependências)

Coleta contadores e latências de cada POST /api/v1/ingest para dar visibilidade
de *desempenho* da central: quantos payloads chegam, quantos persistem, quanto
tempo a persistência leva e qual a vazão recente. Serve tanto para operação
(observabilidade) quanto para a coleta de evidências de carga.

Por que em memória e não no banco: a medição do custo de ingestão não pode
depender do próprio banco que está sendo medido, nem competir com ele por I/O.
São números operacionais efêmeros (zeram ao reiniciar), expostos em
GET /api/v1/ingest/stats.

Concorrência: a API é single-threaded (event loop asyncio). Os métodos abaixo
não têm pontos de `await`, então cada `record()`/`snapshot()` é atômico em
relação aos outros — sem necessidade de lock.
"""

import time
from collections import Counter, deque
from dataclasses import dataclass, field

# Janela deslizante de eventos para percentis de latência. Limita memória e faz
# as estatísticas refletirem o comportamento *recente*, não a média histórica.
_WINDOW_MAXLEN = 1000
# Vazão é reportada sobre esta janela temporal (segundos).
_THROUGHPUT_WINDOW_S = 60


def _percentile(sorted_values: list[float], pct: float) -> float:
    """Percentil (interpolação linear) de uma lista JÁ ordenada. pct em [0, 100]."""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (pct / 100) * (len(sorted_values) - 1)
    low = int(rank)
    high = min(low + 1, len(sorted_values) - 1)
    frac = rank - low
    return sorted_values[low] + (sorted_values[high] - sorted_values[low]) * frac


@dataclass
class _Event:
    wall: float        # time.time() do evento (para janela de vazão)
    total_ms: float    # tempo total do handler de ingest
    persist_ms: float  # tempo só da persistência (crud.insert_metric)
    ok: bool           # persistiu com sucesso?


@dataclass
class IngestMetrics:
    started_at: float = field(default_factory=time.time)
    total_received: int = 0
    total_persisted: int = 0
    total_failed: int = 0
    per_pilar: Counter = field(default_factory=Counter)
    _events: deque[_Event] = field(default_factory=lambda: deque(maxlen=_WINDOW_MAXLEN))

    def record(
        self, *, pilar: str, total_ms: float, persist_ms: float, ok: bool
    ) -> None:
        """Registra um evento de ingestão. Chamado uma vez por POST /ingest."""
        self.total_received += 1
        if ok:
            self.total_persisted += 1
            self.per_pilar[pilar] += 1
        else:
            self.total_failed += 1
        self._events.append(
            _Event(wall=time.time(), total_ms=total_ms, persist_ms=persist_ms, ok=ok)
        )

    def snapshot(self) -> dict:
        """Estatísticas agregadas atuais (consumidas pelo endpoint /ingest/stats)."""
        now = time.time()
        window_start = now - _THROUGHPUT_WINDOW_S

        persist_latencies = sorted(
            e.persist_ms for e in self._events if e.ok
        )
        recent = sum(1 for e in self._events if e.ok and e.wall >= window_start)

        return {
            "uptime_seconds": round(now - self.started_at, 1),
            "total_received": self.total_received,
            "total_persisted": self.total_persisted,
            "total_failed": self.total_failed,
            "per_pilar": dict(self.per_pilar),
            "throughput_per_min": recent,
            "sample_size": len(persist_latencies),
            "persist_ms_avg": round(
                sum(persist_latencies) / len(persist_latencies), 2
            ) if persist_latencies else 0.0,
            "persist_ms_p50": round(_percentile(persist_latencies, 50), 2),
            "persist_ms_p95": round(_percentile(persist_latencies, 95), 2),
            "persist_ms_max": round(max(persist_latencies), 2) if persist_latencies else 0.0,
        }

    def reset(self) -> None:
        """Zera tudo. Usado nos testes; sem endpoint de reset em produção."""
        self.started_at = time.time()
        self.total_received = 0
        self.total_persisted = 0
        self.total_failed = 0
        self.per_pilar.clear()
        self._events.clear()


# Singleton de processo. Reiniciar a API zera as métricas (efêmeras por projeto).
metrics = IngestMetrics()
