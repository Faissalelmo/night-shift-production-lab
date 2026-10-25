# 03 — Disque plein sur le répertoire de sortie (outbox)

> Scénario du lab : `make inject SCENARIO=disk_full` / `make recover SCENARIO=disk_full`

`daily_extract` écrit les écarts de rapprochement dans l'outbox (volume de 5 Mo dans le lab).
Quand le volume est plein, l'écriture échoue (`ENOSPC`). Le job annule sa transaction : rien
n'est marqué « exporté », donc aucune donnée n'est perdue, mais le fichier attendu par l'aval
n'est pas produit.

## Symptômes / Détection

- **Alertes** :
  - `BatchJobFailed{job="daily_extract"}` (critique) ;
  - `OutboxAlmostFull{job="daily_extract"}` (avertissement, > 90 % utilisé) ;
  - `SyntheticCheckFailed` : la page de statut passe à `DEGRADED` (`daily_extract` en `FAILED`).
- **Grafana** : jauge *Outbox volume used* à ~100 % (rouge) ; *Last run status per job* :
  `daily_extract` = **FAILED**.
- **Kibana** : `job : "daily_extract" and error_type : "disk_full"`
  → `run failed: OSError: [Errno 28] No space left on device`.

## Diagnostic

1. Taux de remplissage du système de fichiers :
   ```bash
   docker compose exec jobs df -h /data/outbox
   ```
2. Qu'est-ce qui occupe la place ? (fichiers cachés compris)
   ```bash
   docker compose exec jobs sh -c 'du -ah /data/outbox | sort -rh | head -n 10'
   docker compose exec jobs ls -la /data/outbox
   ```
3. Fichiers partiels laissés par un échec (ne doivent pas exister : le job les supprime) :
   ```bash
   docker compose exec jobs find /data/outbox -name '*.part'
   ```
4. Les écarts en attente d'export sont-ils toujours en base (preuve qu'aucune donnée n'est perdue) ?
   ```bash
   docker compose exec -T postgres psql -U lab -d payments -c \
     "SELECT count(*) AS en_attente FROM reconciliation_results WHERE status <> 'MATCHED' AND exported_at IS NULL;"
   ```

**Arbre de décision**
- Un fichier inattendu et volumineux occupe le volume (dans le lab : `.ballast`) → le supprimer
  après avoir identifié son origine.
- Le volume est rempli par les extractions légitimes → **ne rien supprimer** : archiver / déplacer
  selon la procédure de purge, ou escalader N2 pour agrandir le volume.

## Résolution

```bash
docker compose exec jobs rm -f /data/outbox/.ballast      # fichier parasite identifié au diagnostic
docker compose exec jobs df -h /data/outbox               # confirmer l'espace libéré
docker compose exec -T jobs run-job daily_extract         # relance immédiate
```
(équivalent : `make recover SCENARIO=disk_full`)

La relance exporte toutes les lignes en attente, y compris celles du run en échec : rien n'est
perdu ni exporté deux fois.

## Critères d'escalade

- **N2 Batch Paiements** : si l'espace ne peut pas être libéré sans supprimer des extractions
  légitimes, ou si le volume se remplit de nouveau en moins d'une heure (cause active).
- **Responsable de production** : si le fichier ne peut pas être produit avant l'heure de mise
  à disposition à l'aval.

Exemple de message :
> **[INC] daily_extract en échec — outbox plein (100 %)**
> Alertes `BatchJobFailed` (daily_extract) et `OutboxAlmostFull` depuis 03:31.
> `df -h /data/outbox` : 5,0M utilisés sur 5,0M. 4,9 Mo occupés par un fichier `.ballast`
> d'origine inconnue (créé 03:29). Aucune donnée perdue : 23 écarts en attente d'export en base.
> Demande : validation de la suppression du fichier / de la purge. Je relance l'extraction dès
> que l'espace est libéré.

## Vérification après correction

1. `docker compose exec jobs df -h /data/outbox` : utilisation basse.
2. Un nouveau fichier `mismatches_*.csv` est présent : `docker compose exec jobs ls -lt /data/outbox | head -n 3`
   (copie locale : `make outbox` puis `ls outbox-copy/`).
3. Plus aucune ligne en attente : la requête du diagnostic (4) renvoie 0.
4. `make alerts` : plus de `BatchJobFailed`, `OutboxAlmostFull`, `SyntheticCheckFailed`.
5. Grafana : jauge *Outbox volume used* verte, `daily_extract` = OK.
