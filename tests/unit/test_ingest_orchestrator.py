from unittest.mock import MagicMock

import pytest


@pytest.fixture()
def orchestrator(monkeypatch):
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:19092")
    import black_ice_common.config as config
    import black_ice_common.ingest_orchestrator as orch

    return config, orch


def test_none_backend_deploys_nothing(orchestrator, monkeypatch):
    config, orch = orchestrator
    monkeypatch.setattr(config.settings, "orchestrator_backend", "none")

    # No docker/kubernetes import should even be attempted for the default backend.
    orch.deploy_ingest("cam-1")
    orch.remove_ingest("cam-1")


def test_docker_backend_deploys_new_container(orchestrator, monkeypatch):
    config, orch = orchestrator
    monkeypatch.setattr(config.settings, "orchestrator_backend", "docker")
    monkeypatch.setattr(config.settings, "orchestrator_docker_network", "infra_default")

    import docker
    import docker.errors

    fake_client = MagicMock()
    fake_client.containers.get.side_effect = docker.errors.NotFound("no such container")
    monkeypatch.setattr(docker, "from_env", lambda: fake_client)

    orch.deploy_ingest("cam-1")

    fake_client.containers.run.assert_called_once()
    _, kwargs = fake_client.containers.run.call_args
    assert kwargs["name"] == "black-ice-ingest-cam-1"
    assert kwargs["network"] == "infra_default"
    assert kwargs["environment"]["CAMERA_ID"] == "cam-1"
    assert kwargs["environment"]["SOURCE"] != "demo"


def test_docker_backend_skips_existing_container(orchestrator, monkeypatch):
    config, orch = orchestrator
    monkeypatch.setattr(config.settings, "orchestrator_backend", "docker")

    import docker

    fake_client = MagicMock()
    fake_client.containers.get.return_value = MagicMock()  # found, no NotFound raised
    monkeypatch.setattr(docker, "from_env", lambda: fake_client)

    orch.deploy_ingest("cam-1")

    fake_client.containers.run.assert_not_called()


def test_docker_backend_remove_is_idempotent(orchestrator, monkeypatch):
    config, orch = orchestrator
    monkeypatch.setattr(config.settings, "orchestrator_backend", "docker")

    import docker
    import docker.errors

    fake_client = MagicMock()
    fake_client.containers.get.side_effect = docker.errors.NotFound("no such container")
    monkeypatch.setattr(docker, "from_env", lambda: fake_client)

    orch.remove_ingest("cam-1")  # must not raise when nothing to remove


def test_kubernetes_backend_creates_deployment(orchestrator, monkeypatch):
    config, orch = orchestrator
    monkeypatch.setattr(config.settings, "orchestrator_backend", "kubernetes")
    monkeypatch.setattr(config.settings, "k8s_namespace", "black-ice")

    from kubernetes import config as k8s_config

    monkeypatch.setattr(k8s_config, "load_incluster_config", lambda: None)

    fake_apps_api = MagicMock()
    import kubernetes.client as k8s_client_module

    monkeypatch.setattr(k8s_client_module, "AppsV1Api", lambda: fake_apps_api)

    orch.deploy_ingest("cam-1")

    fake_apps_api.create_namespaced_deployment.assert_called_once()
    args, _ = fake_apps_api.create_namespaced_deployment.call_args
    assert args[0] == "black-ice"
    body = args[1]
    assert body.metadata.name == "black-ice-ingest-cam-1"


def test_kubernetes_backend_create_is_idempotent_on_conflict(orchestrator, monkeypatch):
    config, orch = orchestrator
    monkeypatch.setattr(config.settings, "orchestrator_backend", "kubernetes")

    from kubernetes import config as k8s_config
    from kubernetes.client.rest import ApiException

    monkeypatch.setattr(k8s_config, "load_incluster_config", lambda: None)

    fake_apps_api = MagicMock()
    fake_apps_api.create_namespaced_deployment.side_effect = ApiException(status=409)
    import kubernetes.client as k8s_client_module

    monkeypatch.setattr(k8s_client_module, "AppsV1Api", lambda: fake_apps_api)

    orch.deploy_ingest("cam-1")  # must not raise on a 409 "already exists"


def test_kubernetes_backend_remove_is_idempotent_on_missing(orchestrator, monkeypatch):
    config, orch = orchestrator
    monkeypatch.setattr(config.settings, "orchestrator_backend", "kubernetes")

    from kubernetes import config as k8s_config
    from kubernetes.client.rest import ApiException

    monkeypatch.setattr(k8s_config, "load_incluster_config", lambda: None)

    fake_apps_api = MagicMock()
    fake_apps_api.delete_namespaced_deployment.side_effect = ApiException(status=404)
    import kubernetes.client as k8s_client_module

    monkeypatch.setattr(k8s_client_module, "AppsV1Api", lambda: fake_apps_api)

    orch.remove_ingest("cam-1")  # must not raise when the deployment is already gone
