# Post-mortem — Arrêt silencieux de l'import des fichiers de règlement

> **Exercice.** Incident simulé dans `night-shift-production-lab` (scénario `missing_file`), rédigé
> comme un vrai post-mortem. Aucun système, client ni partenaire réel. Les horaires sont ceux de
> l'exercice, joué avec la planification de production (import toutes les 5 min).

| | |
|---|---|
| **Date** | nuit du 23 au 24 octobre 2026 |
| **Durée de l'incident** | 01:40 → 04:12 (2 h 32) |
| **Détection** | 04:05 — par un contrôle manuel, **pas par la supervision** |
| **Sévérité** | Majeure (2 h 32 sans données amont, détection tardive) |
| **Rédaction** | Ingénieur de production de nuit — format *blameless* |
| **Statut** | Actions correctives terminées (voir fin du document) |

## Résumé

Entre 01:40 et 04:12, aucun fichier de règlement n'a été chargé. L'émetteur amont avait cessé de
déposer ses fichiers. Le job `import_settlement_file` a continué à s'exécuter toutes les 5 minutes
et à **terminer avec succès** (code retour 0) en constatant une boîte de réception vide.
La supervision de l'époque ne surveillait que les **échecs** des jobs : elle est restée verte
pendant 2 h 25. L'anomalie a été détectée par hasard lors d'un contrôle du volume de lignes
traitées. Le flux a repris à 04:12 ; le rattrapage n'a créé aucun doublon.

## Impact

- 29 cycles d'import consécutifs (01:45 → 04:05) sans aucun fichier chargé.
- Aucune transaction ni aucun règlement reçus de l'amont pendant 2 h 32 : le rapprochement et
  l'extraction de 03:00 ont tourné « à vide », sans que rien ne le signale.
- La période manquante n'a pas été réémise par l'amont (limite du simulateur). En production,
  la demande de réémission fait partie de l'escalade (runbook 01).
- Aucun impact client ; aucun doublon au rattrapage (vérifié : `count(*) - count(DISTINCT rrn) = 0`).

## Chronologie (heure locale)

| Heure | Événement |
|---|---|
| 01:38 | Dernier fichier reçu et chargé (`SETTLEMENT_20261024_013758_*.csv`). |
| 01:40 | L'émetteur amont s'arrête (conteneur `generator` arrêté). Aucun message d'erreur. |
| 01:45 | Premier import sur inbox vide : WARNING `no_input_file`, **code retour 0**. |
| 01:45 → 04:05 | 29 exécutions identiques. Tableau de bord : tous les jobs **OK** (vert). |
| 03:00 | `daily_extract` s'exécute normalement sur des données incomplètes. |
| 04:05 | Contrôle de routine : le panneau *Rows processed* de l'import est à 0 depuis 01:45. Début de l'analyse. |
| 04:07 | `ls -lt archive/` : dernier fichier à 01:38. `docker compose ps generator` : `exited`. |
| 04:09 | Escalade N2 *Batch Paiements* (message type du runbook 01). |
| 04:12 | Émetteur redémarré par le N2. Premier nouveau fichier reçu. |
| 04:13 | Import relancé manuellement : le nouveau fichier est chargé et archivé. |
| 04:14 | Rapprochement relancé : les nouvelles lignes sont rapprochées, aucun doublon. |
| 04:30 | Extraction complète produite. Clôture de l'incident. |

## Cause racine

**Cause déclenchante** : arrêt de l'émetteur amont, sans signal d'erreur.

**Cause racine** : la supervision mesurait *« le job a-t-il échoué ? »* au lieu de *« le job
a-t-il fait son travail ? »*. Un import qui ne trouve rien à charger se terminait en succès,
était enregistré comme succès et mettait à jour l'horodatage du « dernier succès ». Un arrêt de
l'amont était donc, par construction, invisible.

Les 5 pourquoi :
1. Pourquoi l'incident a-t-il duré 2 h 32 ? — Parce qu'aucune alerte ne s'est déclenchée.
2. Pourquoi aucune alerte ? — Parce que toutes les exécutions étaient en succès.
3. Pourquoi en succès ? — Parce qu'une inbox vide n'était pas considérée comme une anomalie.
4. Pourquoi ? — Parce que la notion de « succès » ne distinguait pas « a tourné » de « a travaillé ».
5. Pourquoi ? — Parce que la supervision avait été conçue pour les pannes bruyantes (échecs,
   erreurs) et jamais testée contre une panne silencieuse.

## Ce qui a bien fonctionné

- L'import est idempotent : le rattrapage n'a créé aucun doublon et n'a demandé aucune
  manipulation de données.
- Les logs JSON ont permis de reconstituer la chronologie en quelques minutes
  (`job : "import_settlement_file" and error_type : "no_input_file"` dans Kibana).

## Ce qui a mal fonctionné

- 2 h 25 entre le début de l'incident et sa détection.
- Détection due au hasard d'un contrôle visuel.
- Le tableau de bord affichait les jobs en vert pendant tout l'incident.

## Actions correctives

| # | Action | Type | Responsable | Échéance | Statut |
|---|---|---|---|---|---|
| 1 | Séparer « a tourné » de « a travaillé » : un import sans fichier termine en succès mais **ne met plus à jour** `last_success_timestamp` (`did_work = false`). | Correctif | Équipe batch | 24/10 | ✅ Fait |
| 2 | Créer l'alerte `BatchJobSilentStop` : aucun succès *utile* depuis 3 intervalles de planification, pour **tous** les jobs. | Détection | Production | 24/10 | ✅ Fait |
| 3 | Ajouter au tableau de bord *Last success age* (en multiples de l'intervalle) et *Last settlement file received*. | Détection | Production | 25/10 | ✅ Fait |
| 4 | Faire refléter cet état par la page de statut (`LATE`) et donc par le contrôle synthétique. | Détection | Production | 25/10 | ✅ Fait |
| 5 | Rédiger le runbook 01 (diagnostic, escalade, message type). | Procédure | Production | 25/10 | ✅ Fait |
| 6 | Tester chaque alerte en conditions réelles : scénario `missing_file` intégré à `scripts/verify.sh`, rejoué à chaque évolution. | Prévention | Production | 26/10 | ✅ Fait |
| 7 | Demander à l'amont un signal explicite « pas de fichier aujourd'hui » pour distinguer absence normale et panne. | Prévention | N2 / partenaire | 15/11 | En cours |

## Délai de détection après correction

Rejoué après les actions 1 à 4 (`scripts/verify.sh missing_file`, planification de production) :
`BatchJobSilentStop` s'est déclenchée **17 min 38 s** après l'arrêt de l'émetteur (3 intervalles
de 5 min, plus le temps d'atteindre l'exécution suivante), contre 2 h 25 de détection fortuite
lors de l'incident.
