"""Pipeline diario: recorre Tecnoempleo y guarda en Postgres.

Uso: python -m jobhunting.pipeline [--dry-run]   (DATABASE_URL por entorno; nunca se imprime)
Salida: 0 ok; 2 bloqueado; 1 error / parser roto.
"""
from __future__ import annotations

import argparse
import dataclasses
import os
import sys
from datetime import datetime, timezone

from jobhunting import db
from jobhunting.descarga import descargar
from jobhunting.portales.tecnoempleo.parser import PORTAL, ParserRoto
from jobhunting.portales.tecnoempleo.scraper import recorrer


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _resumen(estado, rec, n_nuevas, n_vistas, extra=None, n_unicas=None) -> str:
    n = len(rec.ofertas) if rec else 0
    lineas = [f"## Tecnoempleo: {estado}",
              f"- paginas: {rec.paginas if rec else 0}",
              f"- n_ofertas: {n}",
              f"- n_nuevas: {n_nuevas if n_nuevas is not None else '-'}",
              f"- n_unicas: {n_unicas if n_unicas is not None else '-'} (puestos unicos)",
              f"- total_anunciado: {rec.total_anunciado if rec else None}",
              f"- n_descartadas: {rec.n_descartadas if rec else 0}",
              f"- parada: {rec.motivo_parada if rec else '-'}"]
    if rec and rec.motivos_descarte:
        lineas += [f"  - descarte: {k} x{v}" for k, v in sorted(rec.motivos_descarte.items())]
    if rec and rec.total_anunciado and abs(n - rec.total_anunciado) > 0.10 * rec.total_anunciado:
        lineas.append(f"- AVISO: n_ofertas ({n}) difiere >10% del total anunciado "
                      f"({rec.total_anunciado})")
    if extra:
        lineas.append(f"- detalle: {extra}")
    return "\n".join(lineas) + "\n"


def ejecutar(fetch=descargar, dry_run=False, database_url=None, max_paginas=30, pausa_s=5,
             sleep=None, ahora=_ahora) -> int:
    kw = {"sleep": sleep} if sleep else {}
    inicio = ahora()
    conn = None
    if not dry_run:
        if not database_url:
            print("Falta DATABASE_URL", file=sys.stderr)
            return 1
        try:
            conn = db.conectar(database_url)
            db.migrar(conn)
            conn.commit()
        except Exception as e:
            print(f"Error de BD: {type(e).__name__}", file=sys.stderr)
            return 1
    rec, estado, codigo, detalle, n_nuevas, n_vistas = None, "ok", 0, None, None, None
    n_unicas = None
    try:
        rec = recorrer(fetch=fetch, max_paginas=max_paginas, pausa_s=pausa_s, **kw)
        if rec.bloqueado:
            estado, codigo, detalle = "bloqueado", 2, rec.detalle
        if rec.ofertas and conn is not None:
            capt = ahora()
            ofertas = [dataclasses.replace(o, capturada_en=capt) for o in rec.ofertas]
            n_vistas, n_nuevas = db.guardar_ofertas(conn, ofertas, capt)
            # Un recorrido bloqueado a medias guarda ofertas pero no el recuento del dia.
            if not rec.bloqueado:
                _, _, n_unicas = db.registrar_recuento(conn, capt.date(), PORTAL)
    except ParserRoto as e:
        conn and conn.rollback()
        estado, codigo, detalle = "error", 1, f"parser roto: {e}"
    except Exception as e:
        conn and conn.rollback()
        estado, codigo, detalle = "error", 1, f"{type(e).__name__}"
    if conn is not None:
        try:
            db.registrar_ejecucion(conn, PORTAL, inicio, ahora(), estado,
                                   len(rec.ofertas) if rec else 0, detalle)
            conn.commit()
        except Exception as e:
            print(f"No se pudo registrar la ejecucion: {type(e).__name__}", file=sys.stderr)
            codigo = codigo or 1
        conn.close()
    texto = _resumen(estado, rec, n_nuevas, n_vistas, detalle, n_unicas)
    print(texto)
    ruta = os.environ.get("GITHUB_STEP_SUMMARY")
    if ruta:
        with open(ruta, "a", encoding="utf-8") as f:
            f.write(texto + "\n")
    return codigo


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="jobhunting.pipeline")
    ap.add_argument("--dry-run", action="store_true", help="sin BD: solo recorre e imprime")
    a = ap.parse_args(argv)
    return ejecutar(dry_run=a.dry_run, database_url=os.environ.get("DATABASE_URL"))


if __name__ == "__main__":
    sys.exit(main())
