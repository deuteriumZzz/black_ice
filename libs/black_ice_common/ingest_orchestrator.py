"""Deploys/removes one ingest process per camera — the remaining Milestone 2
gap: the camera registry configured a camera but never deployed anything for
it, leaving process<->camera assignment a manual deploy step. Two backends
behind the same two functions, picked via settings.orchestrator_backend:

- "none" (default): no-op, logs only. Keeps the original manual-deploy
  workflow (new compose service / ingest.cameras Helm entry) for anyone who
  doesn't want match reaching into Docker/Kubernetes on its own.
- "docker": local dev — talks to the Docker Engine API (needs
  /var/run/docker.sock mounted into match's own container).
- "kubernetes": the real deploy target — creates/deletes a Deployment shaped
  exactly like infra/k8s/black-ice/templates/ingest-deployment.yaml's static
  per-camera entries, just triggered at runtime instead of at `helm install`
  time. Requires match's ServiceAccount to have deployments RBAC (see
  ingest-orchestrator-rbac.yaml, gated behind orchestratorBackend=kubernetes).

Deliberately no reconciliation loop, no health-checking, no restart-on-crash
beyond what the backend itself already provides (Docker's own restart
policy / Kubernetes' Deployment controller) — this only handles the two
moments that matter: a camera is registered/enabled, or removed/disabled.

SOURCE is force-set to a non-"demo" sentinel in both backends: ingest only
resolves its real capture source from the camera registry (via CAMERA_ID)
when SOURCE isn't "demo" — see services/ingest/main.py's _resolve_config.
"""
import logging

from black_ice_common.config import settings

log = logging.getLogger("ingest_orchestrator")

_NAME_PREFIX = "black-ice-ingest-"


def _name(camera_id: str) -> str:
    return f"{_NAME_PREFIX}{camera_id}"


def _deploy_docker(camera_id: str) -> None:
    import socket

    import docker
    import docker.errors

    client = docker.from_env()
    name = _name(camera_id)
    try:
        client.containers.get(name)
        log.info("ingest container %s already running, skipping", name)
        return
    except docker.errors.NotFound:
        pass

    network = settings.orchestrator_docker_network
    if network is None:
        self_container = client.containers.get(socket.gethostname())
        network = next(iter(self_container.attrs["NetworkSettings"]["Networks"]))

    client.containers.run(
        settings.ingest_image,
        name=name,
        detach=True,
        network=network,
        environment={
            "CAMERA_ID": camera_id,
            "SOURCE": "camera-registry",  # sentinel: routes ingest to the registry lookup, see module docstring
            "KAFKA_BOOTSTRAP_SERVERS": settings.kafka_bootstrap_servers,
            "MATCH_API_URL": settings.match_api_url,
        },
    )
    log.info("deployed ingest container %s on network %s", name, network)


def _remove_docker(camera_id: str) -> None:
    import docker
    import docker.errors

    client = docker.from_env()
    name = _name(camera_id)
    try:
        container = client.containers.get(name)
    except docker.errors.NotFound:
        log.info("ingest container %s not running, nothing to remove", name)
        return
    container.remove(force=True)
    log.info("removed ingest container %s", name)


def _deploy_kubernetes(camera_id: str) -> None:
    from kubernetes import client as k8s, config as k8s_config
    from kubernetes.client.rest import ApiException

    k8s_config.load_incluster_config()
    apps = k8s.AppsV1Api()
    name = _name(camera_id)

    body = k8s.V1Deployment(
        metadata=k8s.V1ObjectMeta(name=name, labels={"app": name, "camera-id": camera_id}),
        spec=k8s.V1DeploymentSpec(
            replicas=1,
            selector=k8s.V1LabelSelector(match_labels={"app": name}),
            template=k8s.V1PodTemplateSpec(
                metadata=k8s.V1ObjectMeta(labels={"app": name, "camera-id": camera_id}),
                spec=k8s.V1PodSpec(
                    containers=[
                        k8s.V1Container(
                            name="ingest",
                            image=settings.ingest_image,
                            env_from=[k8s.V1EnvFromSource(config_map_ref=k8s.V1ConfigMapEnvSource(name="black-ice-config"))],
                            env=[
                                k8s.V1EnvVar(name="CAMERA_ID", value=camera_id),
                                k8s.V1EnvVar(name="SOURCE", value="camera-registry"),
                            ],
                        )
                    ]
                ),
            ),
        ),
    )
    try:
        apps.create_namespaced_deployment(settings.k8s_namespace, body)
        log.info("created ingest deployment %s", name)
    except ApiException as exc:
        if exc.status == 409:
            log.info("ingest deployment %s already exists, skipping", name)
        else:
            raise


def _remove_kubernetes(camera_id: str) -> None:
    from kubernetes import client as k8s, config as k8s_config
    from kubernetes.client.rest import ApiException

    k8s_config.load_incluster_config()
    apps = k8s.AppsV1Api()
    name = _name(camera_id)
    try:
        apps.delete_namespaced_deployment(name, settings.k8s_namespace)
        log.info("removed ingest deployment %s", name)
    except ApiException as exc:
        if exc.status == 404:
            log.info("ingest deployment %s not found, nothing to remove", name)
        else:
            raise


def deploy_ingest(camera_id: str) -> None:
    if settings.orchestrator_backend == "docker":
        _deploy_docker(camera_id)
    elif settings.orchestrator_backend == "kubernetes":
        _deploy_kubernetes(camera_id)
    else:
        log.info("orchestrator_backend=none — not deploying an ingest process for %s (manual deploy still required)", camera_id)


def remove_ingest(camera_id: str) -> None:
    if settings.orchestrator_backend == "docker":
        _remove_docker(camera_id)
    elif settings.orchestrator_backend == "kubernetes":
        _remove_kubernetes(camera_id)
    else:
        log.info("orchestrator_backend=none — not removing any ingest process for %s (manual teardown still required)", camera_id)
