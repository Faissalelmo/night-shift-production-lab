# 06 — Pic d'écarts de rapprochement (scénario bonus)

> Scénario du lab : `make inject SCENARIO=mismatch_spike` / `make recover SCENARIO=mismatch_spike`

Les jobs fonctionnent, mais le rapprochement trouve beaucoup plus d'écarts que d'habitude
(quelques-uns par run en temps normal). C'est un incident **métier** détecté par la production :
fichier du partenaire erroné, problème de devise ou d'arrondi, transactions en double côté émetteur…

## Symptômes / Détection

- **Alerte** : `ReconciliationMismatchesHigh` (avertissement) — un run des 5 dernières minutes a
  trouvé plus de 30 écarts. C'est un **événement** : l'alerte se résout seule 5 min après le pic,
  même si rien n'a été traité. Sa résolution ne veut donc pas dire « problème réglé » : la
  qualification et l'escalade restent à faire.
- **Grafana** : *Mismatches in last reconciliation run* dépasse la ligne rouge à 30.
- **Kibana** : `job : "reconcile_transactions" and message : "reconciliation done*"`
  → le champ `by_status` détaille les écarts (`AMOUNT_MISMATCH`, `UNKNOWN_RRN`…).

## Diagnostic

1. Quel type d'écart, quel fichier ?
   ```bash
   docker compose exec -T postgres psql -U lab -d payments -c \
     "SELECT r.status, f.file_name, count(*)
        FROM reconciliation_results r
        LEFT JOIN settlement_rows s ON s.rrn = r.rrn
        LEFT JOIN settlement_files f ON f.id = s.file_id
       WHERE r.detected_at > now() - interval '1 hour' AND r.status <> 'MATCHED'
       GROUP BY 1, 2 ORDER BY 3 DESC;"
   ```
2. Échantillon d'écarts pour qualifier le problème (montant décalé ? toujours le même écart ?) :
   ```bash
   docker compose exec -T postgres psql -U lab -d payments -c \
     "SELECT rrn, txn_amount, settled_amount, settled_amount - txn_amount AS ecart
        FROM reconciliation_results
       WHERE status = 'AMOUNT_MISMATCH' AND detected_at > now() - interval '1 hour' LIMIT 10;"
   ```

## Résolution

**Le N1 ne corrige pas de données de paiement.** Les écarts sont exportés par `daily_extract`
pour traitement par l'équipe métier. La production : qualifie, isole le fichier en cause, escalade.

Dans le lab, le run de rapprochement suivant revient à la normale :
`make recover SCENARIO=mismatch_spike`.

## Critères d'escalade

- **N2 Batch Paiements** immédiatement si plus de 30 écarts concentrés sur **un seul fichier**
  (fichier probablement erroné : le partenaire doit être contacté avant le prochain envoi).
- **Responsable de production** + équipe métier si le volume ou le montant total des écarts est
  significatif.

Exemple de message :
> **[INC] 120 écarts de montant sur le fichier SETTLEMENT_20261024_032210_BURST_1f0a.csv**
> Alerte `ReconciliationMismatchesHigh` à 03:24. Les 120 lignes du fichier sont en
> `AMOUNT_MISMATCH` (écarts de +1,00 à +99,99 MAD) ; les autres fichiers de la nuit sont normaux.
> Le fichier a été chargé et les écarts seront dans l'extraction de 03:30. Demande : contact du
> partenaire pour vérification du fichier ; aucune correction de données effectuée côté production.

## Vérification après correction

1. Le run suivant repasse sous le seuil : Grafana / log `reconciliation done: …`.
2. `make alerts` : plus de `ReconciliationMismatchesHigh` (5 min après le pic).
3. Les écarts du pic sont présents dans un fichier de l'outbox (`make outbox`), pour l'équipe métier.
