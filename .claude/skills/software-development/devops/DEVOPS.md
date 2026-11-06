# DevOps (sub-skill of software-development)

Knowledge base: https://github.com/soroushdeimi/DevOps_Certification (fork of AhmadRafiee/DevOps_Certification, Apache-2.0). It is a ~36 MB tutorial repo, so it is NOT vendored. Fetch only the file you need:

    gh api repos/soroushdeimi/DevOps_Certification/contents/<path> -q .content | base64 -d
    # or list a folder:  gh api repos/soroushdeimi/DevOps_Certification/contents/<dir> -q '.[].path'

For work inside the user's own infra repo, Graphify-first still applies (see parent SKILL.md). Use this file for conventions and to locate reference examples.

## Repo map (where to look)

| Topic | Path | Notes |
|---|---|---|
| Linux | `linux/` | ssh_config, SSH port-knocking, proxy setup, zsh |
| Nginx / Traefik / HAProxy / Keepalived | `web-service/`, `keepalived/` | reverse proxy, LB, VIP HA (active-passive / active-active diagrams in `images/`) |
| Bash | `bash/` | automation scripts |
| Docker | `docker/Dockerfile/` (best-practice, multistage, flask/static samples), `docker/compose-file/` (~485 stack files), `docker/scenario/`, `docker/swarm/` | |
| Ansible | `ansible/` | playbooks, roles, variable precedence, templates, lookups/filters/loops, nginx practices, semaphore GUI |
| Kubernetes | `kubernetes/cluster-setup` (kubeadm, kubespray), `manifests/`, `helm/`, `add-ons/`, `scenario/` (auto-scaling HPA/KEDA, etc.), `security/` | Rancher, networking/ingress, Velero backup |
| Observability | `observability/` | ELK single/multi node, Elastic Beats, Prometheus, Graylog, Loki, Mimir, Tempo, Jaeger |
| GitLab CI/CD | `gitlab/` (`sample-gitlab-ci/.gitlab-ci.yml`, mono/multi-repo voting-app, runner images, runner server, repository server, ci pipelines exporter), `doc/` design drawings | |
| GitOps | `argocd/` | app-of-apps, ApplicationSet, helm/kustomize guestbook, k8s-addons-app, voting-app |
| IaC | Terraform sections (providers: AWS, Azure, OpenStack, Docker, Kubernetes+Helm, Cloudflare, MinIO) | diagrams in `images/terraform-*.png` |
| Backup / DR | Velero, GitLab backup, DB backups (MySQL/Postgres/Mongo), rsync/Rclone/Bacula, DRP, Ceph | |
| Storage / cloud | `ceph/`, `minio/`, OpenStack (Nova/Neutron/Cinder/Horizon) | single vs multi node |
| Workshops | `rahbia-workshop/` | kubeadm / kubespray sessions |

## Working conventions (distilled from the repo)

**Docker**
- Multi-stage builds; small base images; one process per container; non-root user.
- Combine `apt-get update && apt-get install -y ... && rm -rf /var/lib/apt/lists/*` in one `RUN`; sort and pin packages.
- Keep a `.dockerignore`; avoid sending the whole context.
- Compose for multi-container apps; scan images (Trivy) before push; tag images with the commit SHA (`$CI_COMMIT_SHORT_SHA`), not only `latest`.

**Kubernetes**
- Provision with kubeadm, or kubespray (Ansible-driven) for production-like clusters; Rancher for multi-cluster management.
- Security baseline: audit logging (apiserver `--audit-policy-file`, `--audit-log-path`, maxsize/maxbackup/maxage; policy drops noisy get/list/watch and system users, keeps `RequestResponse` for the rest), CIS checks with kube-bench, image/cluster scanning with Trivy (+ Trivy Operator), least-privilege RBAC (namespace-scoped read-only users before cluster-wide), NetworkPolicies for workload isolation, secrets managed properly.
- Scaling: HPA for pods, cluster autoscaler for nodes, KEDA for event-driven (HTTP, RabbitMQ examples in `kubernetes/scenario/auto-scaling/keda`).
- Back up with Velero (resources + PVs) and test restores.

**GitLab CI/CD**
- Stages `build -> test -> deploy`; runner `tags` to route jobs to build/test/deploy runners; include Trivy container-scanning template and publish its report as a `container_scanning` artifact.
- Deploy to dev automatically, production behind a manual/protected gate; use `environment:` blocks.
- Improve on the sample: never inline secrets or `docker login -p` in script (use masked/protected CI variables or `--password-stdin`); do not `StrictHostKeyChecking=no` in production; pin job images instead of floating `docker:dind`.

**GitOps (Argo CD)**
- Git is the source of truth; app-of-apps or ApplicationSet to manage many apps/clusters; helm values and kustomize overlays per environment; auto-sync with self-heal for non-prod, reviewed sync for prod.

**Terraform**
- Reusable modules, remote encrypted state with locking, no secrets in state-visible variables where avoidable, `plan` reviewed before `apply`.

**Ansible**
- Roles + inventories (dynamic for large fleets); idempotent tasks; know variable precedence (`ansible/Ansible-Variable-Precedence`); templates over sed; vault for secrets.

**Observability**
- Metrics: Prometheus + Alertmanager + Grafana (Mimir for long-term). Logs: Loki (cheap, label-based) or ELK/Graylog (full-text). Traces: Tempo/Jaeger. Correlate through Grafana. Production ELK needs multi-node with index lifecycle management.

**Backup / DR**
- Backups are not real until a restore is tested. Cover cluster (Velero), databases (logical + physical), files (rsync/Rclone), GitLab (repos, CI data, config), and write a DRP with defined failover steps.

**HA edge**
- HAProxy/Nginx behind Keepalived VIP (active-passive or active-active) for L4/L7 load balancing without a single point of failure.

## Security tie-in
For infra/IaC/CI/container/deployment changes also consult the backend security workflow: `../backend/security-audit/CLOUD-AND-DEPLOYMENT.md` and `SUPPLY-CHAIN-AND-RELEASE.md`.

## Safety
Never run destructive or production-affecting commands (terraform apply/destroy, kubectl delete, docker rm on shared hosts, ansible against live inventory, restores) without explicit user confirmation. Use dry-run/plan/`--check`/`--diff` first.
