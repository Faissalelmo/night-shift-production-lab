# Runbooks — équipe de production de nuit

Un runbook par incident. Chacun suit le même plan : **Symptômes / Détection → Diagnostic →
Résolution → Critères d'escalade → Vérification après correction**.

## Quelle alerte → quel runbook

| Alerte (Prometheus + Grafana) | Sévérité | Runbook |
|---|---|---|
| `BatchJobSilentStop` | critique | [01 — Fichier de règlement absent](01-missing-file.md) |
| `BatchJobFailed` avec `error_type=db_connection` / `PostgresDown` | critique | [02 — Base de données indisponible](02-db-down.md) |
| `BatchJobFailed` avec `error_type=disk_full` / `OutboxAlmostFull` | critique / avertissement | [03 — Disque plein (outbox)](03-disk-full.md) |
| `BatchJobTooSlow` | avertissement | [04 — Requête lente](04-slow-query.md) |
| WARNING `error_type=duplicate_file` (pas d'alerte) | info | [05 — Fichier rejoué](05-duplicate-rerun.md) |
| `ReconciliationMismatchesHigh` | avertissement | [06 — Pic d'écarts de rapprochement](06-mismatch-spike.md) |
| `SyntheticCheckSlow` | avertissement | [07 — Page de statut lente](07-slow-page.md) |
| `SyntheticCheckFailed` | critique | Symptôme, pas une cause : la page de statut reflète les batchs. Partir de l'alerte batch déclenchée en même temps. |

`BatchJobFailed` couvre tous les échecs : le champ `error_type` du dernier log ERROR du job
(Kibana, recherche enregistrée **Errors by job**) indique le bon runbook.

## Outils

| Outil | URL | Usage |
|---|---|---|
| Grafana | http://localhost:3000 | Tableau de bord *Night Shift — Batch production*, alertes Grafana |
| Prometheus | http://localhost:9090/alerts | État brut des règles d'alerte |
| Kibana | http://localhost:5601 | Logs JSON des jobs (*Discover*, recherche *Errors by job*, dashboard *Night shift — job errors*) |
| Page de statut | http://localhost:8088 | Vue « utilisateur » de la santé des batchs |

Toutes les commandes se lancent depuis la racine du dépôt.
Sous Windows, utiliser Git Bash (`export MSYS_NO_PATHCONV=1` avant les commandes `docker compose exec`
qui contiennent des chemins `/data/...`).

## Niveaux d'escalade (fictifs)

| Niveau | Qui | Quand |
|---|---|---|
| N1 | Ingénieur de production de nuit (vous) | Détection, diagnostic, actions documentées dans les runbooks |
| N2 | Astreinte applicative *Batch Paiements* | Correction hors runbook, décision de relance manuelle hors procédure |
| N2 | DBA d'astreinte | Base indisponible ou dégradée au-delà des actions N1 |
| N3 | Éditeur / partenaire (chambre de compensation) — via N2 uniquement | Fichier non émis, contenu erroné |
| Manager | Responsable de production | Impact client ou réglementaire, incident > 1 h, décision de communication |

Règle générale : **toute action non décrite dans un runbook est escaladée avant d'être faite**, et toute
escalade est tracée (heure, interlocuteur, décision) dans le ticket d'incident.
