# 04 — Rapprochement anormalement lent

> Scénario du lab : `make inject SCENARIO=slow_query` / `make recover SCENARIO=slow_query`

Le job `reconcile_transactions` dure habituellement moins d'une seconde. Il est soudainement
beaucoup plus long : requête dégradée (index perdu, verrou, plan d'exécution changé). Dans le lab,
le ralentissement est simulé par un `pg_sleep` injecté dans la transaction de rapprochement.

## Symptômes / Détection

- **Alerte** : `BatchJobTooSlow{job="reconcile_transactions"}` (avertissement). Elle se déclenche
  **pendant** l'exécution, dès que la durée dépasse 2× la durée habituelle (médiane sur 6 h),
  avec un plancher de 30 s pour ignorer le bruit des jobs très courts.
- **Grafana** : *Running now* = `running` pour `reconcile_transactions` de façon prolongée ;
  *Run duration* : pic à la fin du run.
- **Kibana** : `job : "reconcile_transactions" and error_type : "overlapping_run"`
  → les exécutions planifiées suivantes sont sautées car la précédente tourne toujours.

## Diagnostic

1. Le job tourne-t-il encore ? Depuis quand ?
   ```bash
   docker compose exec jobs ps -eo pid,etime,cmd | grep reconcile
   ```
2. Que fait la base ? Requêtes actives, durée, attente :
   ```bash
   docker compose exec -T postgres psql -U lab -d payments -c \
     "SELECT pid, now() - query_start AS duree, state, wait_event_type, wait_event,
             left(query, 60) AS requete
        FROM pg_stat_activity
       WHERE datname = 'payments' AND state <> 'idle'
       ORDER BY duree DESC;"
   ```
   - `wait_event = PgSleep` : ralentissement injecté (lab).
   - `wait_event_type = Lock` : verrou — chercher le bloqueur :
     `SELECT pid, pg_blocking_pids(pid) FROM pg_stat_activity WHERE cardinality(pg_blocking_pids(pid)) > 0;`
3. Interrupteurs de panne du lab :
   ```bash
   docker compose exec -T postgres psql -U lab -d payments -c "SELECT * FROM lab_faults;"
   ```
4. Charge de la machine (CPU / mémoire des conteneurs) :
   ```bash
   docker stats --no-stream
   ```

## Résolution

Dans le lab, retirer la cause puis laisser le run en cours finir (ou l'annuler) :
```bash
docker compose exec -T postgres psql -U lab -d payments -c "DELETE FROM lab_faults WHERE name = 'slow_query';"
# optionnel : annuler la requête en cours — la transaction est annulée proprement, aucune donnée partielle
docker compose exec -T postgres psql -U lab -d payments -c \
  "SELECT pg_cancel_backend(pid) FROM pg_stat_activity WHERE wait_event = 'PgSleep';"
docker compose exec -T -e LAB_LOCK_WAIT=1 jobs run-job reconcile_transactions   # run normal
```
(équivalent : `make recover SCENARIO=slow_query`)

En production : **le N1 n'annule une requête qu'avec l'accord du N2 / DBA**. `pg_cancel_backend`
(annulation de la requête) est toujours préféré à `pg_terminate_backend` (coupure de la session).

## Critères d'escalade

- **DBA d'astreinte** : un verrou bloque le rapprochement, ou la lenteur persiste après la fin
  du run en cours (la requête est structurellement dégradée).
- **N2 Batch Paiements** : si le rapprochement n'a pas abouti à temps pour l'extraction suivante.

Exemple de message :
> **[INC] reconcile_transactions anormalement long (4 min au lieu de < 1 s)**
> Alerte `BatchJobTooSlow` depuis 04:12. `pg_stat_activity` : la requête de rapprochement est
> active depuis 4 min, `wait_event_type = Lock`, bloquée par le PID 4182 (session `psql` ouverte
> depuis 03:58, état *idle in transaction*). Deux exécutions planifiées ont été sautées
> (`overlapping_run`). Demande : accord pour annuler la session bloquante, ou prise en charge DBA.

## Vérification après correction

1. `pg_stat_activity` ne montre plus de requête longue.
2. Le run suivant dure à nouveau moins d'une seconde (`duration_ms` dans le log `run finished`).
3. `make alerts` : plus de `BatchJobTooSlow`.
4. Grafana : *Running now* = idle ; *Run duration* revenu à la normale.
5. Les écarts sont à jour : pas d'exécution `overlapping_run` après la correction dans Kibana.
