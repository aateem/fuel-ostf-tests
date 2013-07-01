from fuel_health.test import attr
from fuel_health.tests.sanity import base


class NetworksTest(base.BaseNetworkTest):
    """
    TestClass contains tests check base networking functionality
    """

    @attr(type=['sanity', 'fuel'])
    def test_list_networks(self):
        """
        Test checks list of networks is available.
        Target component: Neutron or Nova

        Scenario:
            1. Request list of networks.
            2. Check response status is positive.
            3. Check response contains "networks" section.
        """
        resp, body = self.client.list_networks()
        self.verify_response_status(resp.status, u'Network (Neutron or Nova)')
        self.verify_response_body(body, u'networks',
                                  "Network list is unavailable. "
                                  "Looks like something broken in Network "
                                  "(Neutron or Nova).")

    @attr(type=['sanity', 'fuel'])
    def test_list_ports(self):
        """
        Test checks list of ports is available.
        Target component: Neutron or Nova

        Scenario:
            1. Request list of ports.
            2. Check response status is positive.
            3. Check response contains "ports" section.
        """
        resp, body = self.client.list_ports()
        self.verify_response_status(resp.status, u'Network (Neutron or Nova)')
        self.verify_response_body(body, u'ports',
                                  'Ports list is unavailable. '
                                  'Looks like something broken in Network '
                                  '(Neutron or Nova).')