# 05 — Fichier de règlement rejoué (doublon)

> Scénario du lab : `make inject SCENARIO=duplicate_rerun` / `make recover SCENARIO=duplicate_rerun`

Un fichier déjà traité est redéposé dans l'inbox : renvoi du partenaire, relance manuelle,
reprise après incident. Le risque est de charger deux fois les mêmes règlements et de fausser
le rapprochement. L'import est **idempotent** : ce runbook sert à le **prouver** et à tracer
l'événement, pas à réparer.

Deux protections, testées par le scénario :
1. le fichier est reconnu par son **nom** *et* par son **empreinte SHA-256** (un renvoi sous un
   autre nom est détecté) → ignoré, déplacé dans `archive/rejected/`, WARNING `duplicate_file` ;
2. chaque ligne est insérée avec `ON CONFLICT (rrn) DO NOTHING` : même si un doublon passait
   le premier contrôle, aucun RRN ne peut être chargé deux fois.

## Symptômes / Détection

- **Pas d'alerte** : un doublon correctement rejeté n'est pas un incident de production.
- **Kibana** : `error_type : "duplicate_file"` → WARNING
  « duplicate settlement file skipped: X was already loaded as Y at … ».
- Fichiers `*.duplicate` dans `archive/rejected/`.

## Diagnostic

1. Quels fichiers ont été rejetés, quand ?
   ```bash
   ls -lt archive/rejected/ | head
   ```
2. Le contenu est-il identique à l'original ? (même empreinte = même contenu)
   ```bash
   sha256sum archive/rejected/<fichier>.duplicate archive/<fichier>
   docker compose exec -T postgres psql -U lab -d payments -c \
     "SELECT file_name, sha256, row_count, loaded_at FROM settlement_files ORDER BY loaded_at DESC LIMIT 5;"
   ```
3. **Preuve d'absence de doublons** en base :
   ```bash
   docker compose exec -T postgres psql -U lab -d payments -c \
     "SELECT count(*) AS lignes, count(DISTINCT rrn) AS rrn_distincts,
             count(*) - count(DISTINCT rrn) AS doublons FROM settlement_rows;"
   ```
   `doublons` doit valoir **0**.

## Résolution

Aucune correction technique. Actions :
- conserver le fichier rejeté (`archive/rejected/`) comme pièce justificative ;
- vérifier si le renvoi était **identique** (même SHA-256 → simple renvoi) ou **différent sous le
  même nom** (contenu corrigé par le partenaire ?) → dans ce cas, ce n'est **pas** un doublon : escalader.

## Critères d'escalade

- **N2 Batch Paiements** : si un fichier portant le nom d'un fichier déjà chargé a un **contenu
  différent** (rectificatif possible du partenaire : ne jamais le charger à la main), ou si les
  renvois se répètent (cause à corriger en amont).
- Sinon : pas d'escalade, simple trace dans la main courante.

Exemple de message (cas rectificatif) :
> **[INFO] Fichier de règlement renvoyé avec un contenu différent**
> 05:02 — `SETTLEMENT_20261024_041500_9c2e.csv` redéposé ; nom déjà chargé à 04:15 mais SHA-256
> différent. Le fichier a été rejeté automatiquement (`archive/rejected/`), rien n'a été chargé.
> Demande : confirmation du partenaire sur la nature du renvoi (rectificatif ?) et procédure de
> chargement à appliquer.

## Vérification après correction

1. Requête de diagnostic (3) : `doublons = 0`.
2. Le nombre de lignes du fichier d'origine est inchangé :
   ```bash
   docker compose exec -T postgres psql -U lab -d payments -c \
     "SELECT f.file_name, count(r.id) FROM settlement_files f JOIN settlement_rows r ON r.file_id = f.id
      WHERE f.file_name = '<fichier>' GROUP BY 1;"
   ```
3. L'inbox est vide (le doublon a bien été déplacé) : `ls inbox/`.
4. Le job a terminé avec le code retour 0 (`run finished`) : un doublon n'est pas un échec.
