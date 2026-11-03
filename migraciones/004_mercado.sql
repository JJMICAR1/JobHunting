-- Fase 6 (control de mercado): desaparecidas y vistas con deltas 1d/7d.
ALTER TABLE recuento_diario ADD COLUMN IF NOT EXISTS n_desaparecidas integer;

CREATE OR REPLACE VIEW v_mercado_diario AS
SELECT r.dia, r.portal, r.n_vistas, r.n_nuevas, r.n_desaparecidas, r.n_unicas,
       r.n_vistas - p1.n_vistas AS d_vistas_1d,
       r.n_vistas - p7.n_vistas AS d_vistas_7d,
       r.n_unicas - p1.n_unicas AS d_unicas_1d,
       r.n_unicas - p7.n_unicas AS d_unicas_7d
FROM recuento_diario r
LEFT JOIN recuento_diario p1 ON p1.portal = r.portal AND p1.dia = r.dia - 1
LEFT JOIN recuento_diario p7 ON p7.portal = r.portal AND p7.dia = r.dia - 7;

CREATE OR REPLACE VIEW v_mercado_hoy AS
SELECT v.* FROM v_mercado_diario v
WHERE v.dia = (SELECT max(dia) FROM recuento_diario r WHERE r.portal = v.portal);
