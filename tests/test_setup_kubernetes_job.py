from typing import Sequence

import mock
from kubernetes.client import V1Deployment
from kubernetes.client import V1DeploymentSpec
from kubernetes.client import V1LabelSelector
from kubernetes.client import V1ObjectMeta
from kubernetes.client import V1PodTemplateSpec
from pytest import raises

from paasta_tools.kubernetes_tools import InvalidKubernetesConfig
from paasta_tools.kubernetes_tools import KubeDeployment
from paasta_tools.setup_kubernetes_job import main
from paasta_tools.setup_kubernetes_job import parse_args
from paasta_tools.setup_kubernetes_job import reconcile_kubernetes_deployment
from paasta_tools.setup_kubernetes_job import setup_kube_deployments
from paasta_tools.utils import NoConfigurationForServiceError
from paasta_tools.utils import NoDeploymentsAvailable


def test_parse_args():
    with mock.patch(
        'paasta_tools.setup_kubernetes_job.argparse', autospec=True,
    ) as mock_argparse:
        assert parse_args() == mock_argparse.ArgumentParser.return_value.parse_args()


def test_main():
    with mock.patch(
        'paasta_tools.setup_kubernetes_job.parse_args', autospec=True,
    ) as mock_parse_args, mock.patch(
        'paasta_tools.setup_kubernetes_job.KubeClient', autospec=True,
    ) as mock_kube_client, mock.patch(
        'paasta_tools.setup_kubernetes_job.ensure_paasta_namespace', autospec=True,
    ) as mock_ensure_paasta_namespace, mock.patch(
        'paasta_tools.setup_kubernetes_job.setup_kube_deployments', autospec=True,
    ) as mock_setup_kube_deployments:
        mock_setup_kube_deployments.return_value = True
        with raises(SystemExit) as e:
            main()
        assert e.value.code == 0
        assert mock_ensure_paasta_namespace.called
        mock_setup_kube_deployments.assert_called_with(
            kube_client=mock_kube_client.return_value,
            service_instances=mock_parse_args.return_value.service_instance_list,
            soa_dir=mock_parse_args.return_value.soa_dir,
        )

        mock_setup_kube_deployments.return_value = False
        with raises(SystemExit) as e:
            main()
        assert e.value.code == 1


def test_setup_kube_deployment():
    with mock.patch(
        'paasta_tools.setup_kubernetes_job.reconcile_kubernetes_deployment', autospec=True,
    ) as mock_reconcile_kubernetes_deployment, mock.patch(
        'paasta_tools.setup_kubernetes_job.list_all_deployments', autospec=True,
    ) as mock_list_all_deployments:
        mock_client = mock.Mock()
        mock_service_instances: Sequence[str] = []
        assert setup_kube_deployments(
            kube_client=mock_client,
            service_instances=mock_service_instances,
            soa_dir='/nail/blah',
        ) is True

        mock_reconcile_kubernetes_deployment.return_value = (0, 0)
        mock_service_instances = ['kurupt.fm', 'kurupt.garage']
        assert setup_kube_deployments(
            kube_client=mock_client,
            service_instances=mock_service_instances,
            soa_dir='/nail/blah',
        ) is True
        mock_reconcile_kubernetes_deployment.assert_has_calls([
            mock.call(
                kube_client=mock_client,
                service='kurupt',
                instance='fm',
                kube_deployments=mock_list_all_deployments.return_value,
                soa_dir='/nail/blah',
            ),
            mock.call(
                kube_client=mock_client,
                service='kurupt',
                instance='garage',
                kube_deployments=mock_list_all_deployments.return_value,
                soa_dir='/nail/blah',
            ),
        ])

        mock_reconcile_kubernetes_deployment.return_value = (1, 0)
        assert setup_kube_deployments(
            kube_client=mock_client,
            service_instances=mock_service_instances,
            soa_dir='/nail/blah',
        ) is False


def test_reconcile_kubernetes_deployment():
    with mock.patch(
        'paasta_tools.setup_kubernetes_job.load_kubernetes_service_config_no_cache', autospec=True,
    ) as mock_load_kubernetes_service_config_no_cache, mock.patch(
        'paasta_tools.setup_kubernetes_job.load_system_paasta_config', autospec=True,
    ), mock.patch(
        'paasta_tools.setup_kubernetes_job.create_deployment', autospec=True,
    ) as mock_create_deployment, mock.patch(
        'paasta_tools.setup_kubernetes_job.update_deployment', autospec=True,
    ) as mock_update_deployment:
        mock_kube_client = mock.Mock()
        mock_deployments: Sequence[KubeDeployment] = []

        # no deployments so should create
        ret = reconcile_kubernetes_deployment(
            kube_client=mock_kube_client,
            service='kurupt',
            instance='fm',
            kube_deployments=mock_deployments,
            soa_dir='/nail/blah',
        )
        assert ret == (0, None)
        mock_deploy = mock_load_kubernetes_service_config_no_cache.return_value.format_kubernetes_app()
        mock_create_deployment.assert_called_with(
            kube_client=mock_kube_client,
            formatted_deployment=mock_deploy,
        )

        # different instance so should create
        mock_deployments = [KubeDeployment(
            service='kurupt',
            instance='garage',
            git_sha='a12345',
            config_sha='b12345',
            replicas=3,
        )]
        ret = reconcile_kubernetes_deployment(
            kube_client=mock_kube_client,
            service='kurupt',
            instance='fm',
            kube_deployments=mock_deployments,
            soa_dir='/nail/blah',
        )
        assert ret == (0, None)
        mock_create_deployment.assert_called_with(
            kube_client=mock_kube_client,
            formatted_deployment=mock_deploy,
        )

        # instance correc so do nothing
        mock_create_deployment.reset_mock()
        mock_load_kubernetes_service_config_no_cache.return_value = mock.Mock(format_kubernetes_app=mock.Mock(
            return_value=V1Deployment(
                metadata=V1ObjectMeta(
                    labels={
                        'git_sha': 'a12345',
                        'config_sha': 'b12345',
                    },
                ),
                spec=V1DeploymentSpec(
                    selector=V1LabelSelector(),
                    template=V1PodTemplateSpec(),
                    replicas=3,
                ),
            ),
        ))
        mock_deployments = [KubeDeployment(
            service='kurupt',
            instance='fm',
            git_sha='a12345',
            config_sha='b12345',
            replicas=3,
        )]
        ret = reconcile_kubernetes_deployment(
            kube_client=mock_kube_client,
            service='kurupt',
            instance='fm',
            kube_deployments=mock_deployments,
            soa_dir='/nail/blah',
        )
        assert ret == (0, None)
        assert not mock_create_deployment.called
        assert not mock_update_deployment.called

        # changed gitsha so update
        mock_create_deployment.reset_mock()
        mock_load_kubernetes_service_config_no_cache.return_value = mock.Mock(format_kubernetes_app=mock.Mock(
            return_value=V1Deployment(
                metadata=V1ObjectMeta(
                    labels={
                        'git_sha': 'new_image',
                        'config_sha': 'b12345',
                    },
                ),
                spec=V1DeploymentSpec(
                    selector=V1LabelSelector(),
                    template=V1PodTemplateSpec(),
                    replicas=3,
                ),
            ),
        ))
        mock_deployments = [KubeDeployment(
            service='kurupt',
            instance='fm',
            git_sha='a12345',
            config_sha='b12345',
            replicas=3,
        )]
        ret = reconcile_kubernetes_deployment(
            kube_client=mock_kube_client,
            service='kurupt',
            instance='fm',
            kube_deployments=mock_deployments,
            soa_dir='/nail/blah',
        )
        assert ret == (0, None)
        assert not mock_create_deployment.called
        mock_deploy = mock_load_kubernetes_service_config_no_cache.return_value.format_kubernetes_app()
        mock_update_deployment.assert_called_with(
            kube_client=mock_kube_client,
            formatted_deployment=mock_deploy,
        )

        # changed configsha so update
        mock_create_deployment.reset_mock()
        mock_update_deployment.reset_mock()
        mock_load_kubernetes_service_config_no_cache.return_value = mock.Mock(format_kubernetes_app=mock.Mock(
            return_value=V1Deployment(
                metadata=V1ObjectMeta(
                    labels={
                        'git_sha': 'a12345',
                        'config_sha': 'newconfig',
                    },
                ),
                spec=V1DeploymentSpec(
                    selector=V1LabelSelector(),
                    template=V1PodTemplateSpec(),
                    replicas=3,
                ),
            ),
        ))
        mock_deployments = [KubeDeployment(
            service='kurupt',
            instance='fm',
            git_sha='a12345',
            config_sha='b12345',
            replicas=3,
        )]
        ret = reconcile_kubernetes_deployment(
            kube_client=mock_kube_client,
            service='kurupt',
            instance='fm',
            kube_deployments=mock_deployments,
            soa_dir='/nail/blah',
        )
        assert ret == (0, None)
        assert not mock_create_deployment.called
        mock_deploy = mock_load_kubernetes_service_config_no_cache.return_value.format_kubernetes_app()
        mock_update_deployment.assert_called_with(
            kube_client=mock_kube_client,
            formatted_deployment=mock_deploy,
        )

        # changed number of replicas so update
        mock_create_deployment.reset_mock()
        mock_update_deployment.reset_mock()
        mock_load_kubernetes_service_config_no_cache.return_value = mock.Mock(format_kubernetes_app=mock.Mock(
            return_value=V1Deployment(
                metadata=V1ObjectMeta(
                    labels={
                        'git_sha': 'a12345',
                        'config_sha': 'b12345',
                    },
                ),
                spec=V1DeploymentSpec(
                    selector=V1LabelSelector(),
                    template=V1PodTemplateSpec(),
                    replicas=2,
                ),
            ),
        ))
        mock_deployments = [KubeDeployment(
            service='kurupt',
            instance='fm',
            git_sha='a12345',
            config_sha='b12345',
            replicas=3,
        )]
        ret = reconcile_kubernetes_deployment(
            kube_client=mock_kube_client,
            service='kurupt',
            instance='fm',
            kube_deployments=mock_deployments,
            soa_dir='/nail/blah',
        )
        assert ret == (0, None)
        assert not mock_create_deployment.called
        mock_deploy = mock_load_kubernetes_service_config_no_cache.return_value.format_kubernetes_app()
        mock_update_deployment.assert_called_with(
            kube_client=mock_kube_client,
            formatted_deployment=mock_deploy,
        )

        # error cases...
        mock_create_deployment.reset_mock()
        mock_update_deployment.reset_mock()
        mock_load_kubernetes_service_config_no_cache.side_effect = NoDeploymentsAvailable
        ret = reconcile_kubernetes_deployment(
            kube_client=mock_kube_client,
            service='kurupt',
            instance='fm',
            kube_deployments=mock_deployments,
            soa_dir='/nail/blah',
        )
        assert ret == (0, None)
        assert not mock_create_deployment.called
        assert not mock_update_deployment.called
        mock_load_kubernetes_service_config_no_cache.side_effect = NoConfigurationForServiceError
        ret = reconcile_kubernetes_deployment(
            kube_client=mock_kube_client,
            service='kurupt',
            instance='fm',
            kube_deployments=mock_deployments,
            soa_dir='/nail/blah',
        )
        assert ret == (1, None)
        assert not mock_create_deployment.called
        assert not mock_update_deployment.called

        mock_load_kubernetes_service_config_no_cache.side_effect = None
        mock_load_kubernetes_service_config_no_cache.return_value = mock.Mock(
            format_kubernetes_app=mock.Mock(side_effect=InvalidKubernetesConfig(Exception("Oh no!"), 'kurupt', 'fm')),
        )
        ret = reconcile_kubernetes_deployment(
            kube_client=mock_kube_client,
            service='kurupt',
            instance='fm',
            kube_deployments=mock_deployments,
            soa_dir='/nail/blah',
        )
        assert ret == (1, None)
        assert not mock_create_deployment.called
        assert not mock_update_deployment.called
