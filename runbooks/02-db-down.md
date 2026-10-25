# 02 — Base de données indisponible

> Scénario du lab : `make inject SCENARIO=db_down` / `make recover SCENARIO=db_down`

PostgreSQL ne répond plus. Tous les jobs échouent avec une erreur de connexion, le générateur
n'enregistre plus de transactions et la page de statut affiche **KO**.

## Symptômes / Détection

- **Alertes** :
  - `PostgresDown` (critique) — l'exporter n'arrive plus à joindre la base (`pg_up == 0`) ;
  - `BatchJobFailed{job="import_settlement_file"}` puis les autres jobs à leur prochaine exécution ;
  - `SyntheticCheckFailed` — la page de statut affiche `KO` (« database unreachable »).
- **Grafana** : panneau *PostgreSQL* = **DOWN** ; *Last run status per job* = **FAILED** ;
  *Active alerts* liste les trois alertes.
- **Kibana** : `error_type : "db_connection"` → une ligne ERROR par job et par exécution, plus
  les erreurs du générateur. Le texte de l'erreur oriente le diagnostic :
  - `[Errno -5] No address associated with hostname` : le conteneur `postgres` n'existe plus sur
    le réseau (arrêté) ;
  - `Connection refused` : le conteneur tourne mais PostgreSQL n'écoute pas (démarrage, crash) ;
  - `timeout expired` : la base est joignable mais ne répond pas (saturation).

## Diagnostic

1. État du conteneur et derniers logs :
   ```bash
   docker compose ps postgres
   docker compose logs --tail 50 postgres
   ```
2. La base accepte-t-elle les connexions ?
   ```bash
   docker compose exec postgres pg_isready -U lab -d payments
   ```
3. Si le conteneur tourne mais refuse les connexions — ressources et sessions :
   ```bash
   docker stats --no-stream postgres
   docker compose exec -T postgres psql -U lab -d payments -c \
     "SELECT count(*) AS sessions, max(now() - backend_start) AS plus_ancienne FROM pg_stat_activity;"
   docker compose exec postgres df -h /var/lib/postgresql/data
   ```
4. Confirmer côté jobs que c'est bien la connexion qui échoue (pas une requête) :
   ```bash
   docker compose logs --since 15m jobs | grep '"error_type": "db_connection"' | tail -n 3
   ```

**Arbre de décision**
- Conteneur arrêté (`exited`) sans erreur dans les logs → redémarrage (résolution ci-dessous).
- Conteneur arrêté avec erreur (`PANIC`, `could not write`, disque plein) → **ne pas redémarrer
  en boucle** : escalade DBA immédiate.
- Conteneur actif, `pg_isready` KO, sessions saturées → escalade DBA.

## Résolution

```bash
docker compose start postgres
until docker compose exec -T postgres pg_isready -U lab -d payments; do sleep 2; done
# rattrapage dans l'ordre de la chaîne : import → rapprochement → extraction
docker compose exec -T jobs run-job import_settlement_file
docker compose exec -T jobs run-job reconcile_transactions
docker compose exec -T jobs run-job daily_extract
```
(équivalent : `make recover SCENARIO=db_down`)

Les jobs sont idempotents : les fichiers restés dans l'inbox pendant la panne sont chargés une
seule fois, et le rapprochement ne crée pas de doublons. Le générateur reprend tout seul.

## Critères d'escalade

- **DBA d'astreinte** : immédiatement si la base ne redémarre pas, redémarre puis retombe,
  ou si les logs montrent une corruption / un disque plein.
- **Responsable de production** : si l'indisponibilité dépasse 30 minutes ou menace l'heure de
  l'extraction du matin.

Exemple de message :
> **[INC] PostgreSQL `payments` indisponible depuis 02:14 — batchs en échec**
> Alertes `PostgresDown`, `BatchJobFailed` (import, rapprochement), `SyntheticCheckFailed` depuis 02:14.
> `pg_isready` : no response. Conteneur arrêté, dernier log : `<copier la ligne>`.
> Un redémarrage a été tenté à 02:20 : la base retombe après 1 min (log joint).
> Impact : aucun fichier chargé ni rapproché depuis 02:14. Demande : intervention DBA.
> Les jobs sont idempotents et seront relancés dans l'ordre dès la base disponible.

## Vérification après correction

1. `docker compose exec postgres pg_isready -U lab -d payments` → *accepting connections*.
2. Les trois jobs relancés terminent avec le code retour 0 (`run finished` dans les logs).
3. Pas de doublons :
   ```bash
   docker compose exec -T postgres psql -U lab -d payments -c \
     "SELECT count(*) - count(DISTINCT rrn) AS doublons FROM settlement_rows;"
   ```
4. Grafana : *PostgreSQL* = UP, *Last run status per job* = OK pour les trois jobs.
5. `make alerts` : plus de `PostgresDown`, `BatchJobFailed`, `SyntheticCheckFailed`.
6. Page de statut : **OK**.
