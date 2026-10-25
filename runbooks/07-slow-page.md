# 07 — Page de statut lente (supervision synthétique, scénario bonus)

> Scénario du lab : `make inject SCENARIO=slow_page` / `make recover SCENARIO=slow_page`

Le contrôle synthétique (Playwright, à la manière d'EKARA) ouvre la page de statut comme un
utilisateur, vérifie qu'elle affiche **OK** et mesure le temps de réponse. Ici, la page répond
mais lentement (> 2 s).

## Symptômes / Détection

- **Alerte** : `SyntheticCheckSlow` (avertissement) ; `SyntheticCheckFailed` si la page dépasse
  le délai de 15 s du navigateur.
- **Grafana** : *Synthetic response time* au-dessus de la ligne à 2 s.
- **Kibana** : `job : "synthetic_status_check"` → champ `duration_ms`.

## Diagnostic

1. Reproduire la mesure depuis le réseau Docker et depuis le poste :
   ```bash
   docker compose exec -T synthetic python check.py --once
   curl -s -o /dev/null -w 'HTTP %{http_code} en %{time_total}s\n' http://localhost:8088/
   ```
2. Est-ce l'application ou sa base ? `/healthz` ne touche pas la base :
   ```bash
   curl -s -o /dev/null -w '%{time_total}s\n' http://localhost:8088/healthz
   ```
   `/healthz` rapide + `/` lent → la lenteur vient des requêtes en base.
3. Ressources et interrupteurs de panne :
   ```bash
   docker stats --no-stream status postgres
   docker compose exec -T postgres psql -U lab -d payments -c "SELECT * FROM lab_faults;"
   ```

## Résolution

```bash
docker compose exec -T postgres psql -U lab -d payments -c "DELETE FROM lab_faults WHERE name = 'slow_page';"
docker compose exec -T synthetic python check.py --once
```
(équivalent : `make recover SCENARIO=slow_page`). Si la cause est la ressource :
`docker compose restart status`, puis escalade si la lenteur revient.

## Critères d'escalade

- **N2** si la lenteur persiste plus de 3 contrôles consécutifs (15 min) ou s'aggrave
  jusqu'à l'échec (`SyntheticCheckFailed`).

Exemple de message :
> **[INC] Page de statut lente — 4,1 s (seuil 2 s) depuis 01:10**
> `/healthz` répond en 5 ms, `/` en 4,1 s : la lenteur vient des requêtes de la page en base.
> Pas d'alerte batch associée. Demande : analyse applicative N2.

## Vérification après correction

1. `docker compose exec -T synthetic python check.py --once` : « status page OK in 0.xx s ».
2. `make alerts` : plus de `SyntheticCheckSlow`.
3. Grafana : *Synthetic response time* revenu sous 2 s.
