# 01 — Fichier de règlement absent (arrêt silencieux de l'import)

> Scénario du lab : `make inject SCENARIO=missing_file` / `make recover SCENARIO=missing_file`

Le cas le plus dangereux de la nuit : **rien n'échoue**. Le job `import_settlement_file` tourne
toutes les 5 minutes, ne trouve aucun fichier dans `./inbox`, termine avec le code retour 0… et ne
charge rien. Une supervision qui ne regarde que les échecs ne voit rien. Le matin, la réconciliation
et l'extraction sont incomplètes.

## Symptômes / Détection

- **Alerte** : `BatchJobSilentStop{job="import_settlement_file"}` (critique) — aucun import ayant
  réellement chargé un fichier depuis plus de 3 intervalles (15 min avec la planification par défaut).
- **Effet secondaire** : `SyntheticCheckFailed` — la page de statut passe à `DEGRADED`, ligne
  `import_settlement_file` en `LATE`.
- **Grafana** (*Night Shift — Batch production*) :
  - panneau *Last success age (× schedule interval)* : la barre de l'import dépasse 3 (rouge) ;
  - panneau *Last settlement file received* : l'âge du dernier fichier ne cesse d'augmenter ;
  - panneau *Rows processed per run* : l'import tombe à 0 ;
  - panneau *Last run status per job* : reste **OK** — c'est normal, et c'est tout le problème.
- **Kibana** (Discover, vue *Job logs*) :
  `job : "import_settlement_file" and error_type : "no_input_file"`
  → un WARNING « no settlement file in inbox » à chaque exécution.

## Diagnostic

1. Confirmer que le job tourne mais ne trouve rien (et n'est donc pas lui-même en panne) :
   ```bash
   docker compose logs --since 30m jobs | grep import_settlement_file | tail -n 5
   ```
2. Vérifier la boîte de réception et le dernier fichier archivé :
   ```bash
   ls -la inbox/                       # vide ?
   ls -lt archive/*.csv | head -n 3    # heure du dernier fichier reçu
   find archive -name '*.csv' -mmin -30 | wc -l   # fichiers reçus dans les 30 dernières minutes
   ```
3. Côté base, heure du dernier chargement :
   ```bash
   docker compose exec -T postgres psql -U lab -d payments -c \
     "SELECT file_name, row_count, loaded_at FROM settlement_files ORDER BY loaded_at DESC LIMIT 3;"
   ```
4. Vérifier l'émetteur (dans le lab : le conteneur `generator`, qui simule le partenaire) :
   ```bash
   docker compose ps generator         # "exited" ou absent = l'amont n'envoie plus
   docker compose logs --tail 20 generator
   ```
5. Vérifier que le planificateur n'est pas en cause :
   ```bash
   docker compose exec jobs pgrep -a supercronic
   ```

**Arbre de décision**
- Le job ne tourne plus du tout (pas de log depuis > 1 intervalle) → problème d'ordonnancement,
  redémarrer `jobs` (`docker compose restart jobs`) puis escalader N2.
- Le job tourne, l'inbox est vide, l'émetteur est arrêté → l'amont n'envoie plus : résolution ci-dessous.
- Des fichiers sont présents dans l'inbox mais ne sont pas chargés → ce n'est pas ce runbook :
  chercher `level : "ERROR" and job : "import_settlement_file"` dans Kibana.

## Résolution

Dans le lab, l'émetteur est sous notre contrôle :
```bash
docker compose start generator
docker compose exec -T jobs run-job import_settlement_file   # charger sans attendre le cron
```
(équivalent : `make recover SCENARIO=missing_file`)

En production réelle, l'émetteur est un partenaire externe : **ne pas « fabriquer » de fichier**.
Le N1 constate, trace et escalade (voir ci-dessous) ; le rattrapage se fait quand le fichier arrive,
par une exécution manuelle de l'import.

## Critères d'escalade

- **Immédiatement** si aucun fichier n'est reçu à l'heure de fin de la fenêtre de traitement
  (ici : 3 intervalles), ou si l'émetteur est externe.
- **Vers** : astreinte applicative N2 *Batch Paiements*, qui contacte le partenaire. Informer le
  responsable de production si le retard risque de dépasser l'heure de l'extraction du matin.

Exemple de message :
> **[INC] Import des fichiers de règlement — aucun fichier reçu depuis 01:40**
> Alerte `BatchJobSilentStop` depuis 02:05. Le job `import_settlement_file` s'exécute normalement
> (code retour 0) mais l'inbox est vide depuis 01:40 ; dernier fichier chargé :
> `SETTLEMENT_20261024_013958_ab12.csv`. Le processus émetteur ne produit plus de fichiers.
> Impact : rapprochement et extraction du matin incomplets si non résolu avant 06:00.
> Action N1 : constat + traces jointes. Demande : contact du partenaire / relance de l'émission.
> Je relance l'import manuellement dès réception.

## Vérification après correction

1. Un nouveau fichier apparaît puis disparaît de l'inbox (chargé et archivé) :
   `ls inbox/ archive/ | tail`
2. Kibana : `job : "import_settlement_file" and message : "settlement file loaded*"` → nouvelles lignes.
3. Grafana : *Last success age* repasse sous 1 ; *Rows processed per run* > 0.
4. Alertes résolues : `make alerts` → `BatchJobSilentStop` et `SyntheticCheckFailed` absents
   (Prometheus et Grafana).
5. Page de statut http://localhost:8088 : **OK**.
6. Contrôler que la réconciliation suivante a traité les lignes rattrapées
   (`docker compose exec -T jobs run-job reconcile_transactions`).
