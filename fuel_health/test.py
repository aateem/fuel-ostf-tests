# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 OpenStack, LLC
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.


import time
import signal
import traceback

import nose.plugins.attrib
import testresources
import testtools

from fuel_health import config
from fuel_health import manager
from fuel_health.common import log as logging
from fuel_health.common.test_mixins import FuelTestAssertMixin


LOG = logging.getLogger(__name__)


class TimeOutError(Exception):
    def __init__(self):
        Exception.__init__(self)


def _raise_TimeOut(sig, stack):
    raise TimeOutError()


class ExecutionTimeout(object):
    """
    Timeout context that will stop code running within context
    if timeout (sec) is reached

    >>with timeout(2):
    ...     requests.get("http://msdn.com")
    """
    def __init__(self, timeout):
        self.timeout = timeout

    def __enter__(self):
        signal.signal(signal.SIGALRM, _raise_TimeOut)
        signal.alarm(self.timeout)

    def __exit__(self, exc_type, exc_val, exc_tb):
        signal.alarm(0)  # disable the alarm
        if exc_type is not TimeOutError:
            return False  # never swallow other exceptions
        else:
            call_that_caused_timeout = traceback.extract_tb(exc_tb)[0][-1]
            msg = '''
                {call} terminated with the timeout of {timeout} seconds.
                Please check that this service timeout meets your expectation.
                '''.format(call=call_that_caused_timeout, timeout=self.timeout)
            raise AssertionError(msg)


def attr(*args, **kwargs):
    """A decorator which applies the nose and testtools attr decorator

    This decorator applies the nose attr decorator as well as the
    the testtools.testcase.attr if it is in the list of attributes
    to testtools we want to apply.
    """

    def decorator(f):
        if 'type' in kwargs and isinstance(kwargs['type'], str):
            f = testtools.testcase.attr(kwargs['type'])(f)
            if kwargs['type'] == 'smoke':
                f = testtools.testcase.attr('smoke')(f)
        elif 'type' in kwargs and isinstance(kwargs['type'], str):
            f = testtools.testcase.attr(kwargs['type'])(f)
            if kwargs['type'] == 'sanity':
                f = testtools.testcase.attr('sanity')(f)
        elif 'type' in kwargs and isinstance(kwargs['type'], list):
            for attr in kwargs['type']:
                f = testtools.testcase.attr(attr)(f)
                if attr == 'sanity':
                    f = testtools.testcase.attr('sanity')(f)
                elif attr == 'smoke':
                    f = testtools.testcase.attr('smoke')(f)
        return nose.plugins.attrib.attr(*args, **kwargs)(f)

    return decorator


class BaseTestCase(testtools.TestCase,
                   testtools.testcase.WithAttributes,
                   testresources.ResourcedTestCase,
                   FuelTestAssertMixin):

    config = config.FuelConfig()

    def __init__(self, *args, **kwargs):
        super(BaseTestCase, self).__init__(*args, **kwargs)

    @classmethod
    def setUpClass(cls):
        if hasattr(super(BaseTestCase, cls), 'setUpClass'):
            super(BaseTestCase, cls).setUpClass()


def call_until_true(func, duration, sleep_for):
    """
    Call the given function until it returns True (and return True) or
    until the specified duration (in seconds) elapses (and return
    False).

    :param func: A zero argument callable that returns True on success.
    :param duration: The number of seconds for which to attempt a
        successful call of the function.
    :param sleep_for: The number of seconds to sleep after an unsuccessful
                      invocation of the function.
    """
    now = time.time()
    timeout = now + duration
    while now < timeout:
        if func():
            return True
        LOG.debug("Sleeping for %d seconds", sleep_for)
        time.sleep(sleep_for)
        now = time.time()
    return False


class TestCase(BaseTestCase):
    """Base test case class for all tests

    Contains basic setup and convenience methods
    """

    manager_class = None

    @classmethod
    def setUpClass(cls):
        cls.manager = cls.manager_class()
        for attr_name in cls.manager.client_attr_names:
            # Ensure that pre-existing class attributes won't be
            # accidentally overriden.
            assert not hasattr(cls, attr_name)
            client = getattr(cls.manager, attr_name)
            setattr(cls, attr_name, client)
        cls.resource_keys = {}
        cls.os_resources = []

    def set_resource(self, key, thing):
        LOG.debug("Adding %r to shared resources of %s" %
                  (thing, self.__class__.__name__))
        self.resource_keys[key] = thing
        self.os_resources.append(thing)

    def get_resource(self, key):
        return self.resource_keys[key]

    def remove_resource(self, key):
        thing = self.resource_keys[key]
        self.os_resources.remove(thing)
        del self.resource_keys[key]

    def status_timeout(self, things, thing_id, expected_status):
        """
        Given a thing and an expected status, do a loop, sleeping
        for a configurable amount of time, checking for the
        expected status to show. At any time, if the returned
        status of the thing is ERROR, fail out.
        """
        def check_status():
            # python-novaclient has resources available to its client
            # that all implement a get() method taking an identifier
            # for the singular resource to retrieve.
            thing = things.get(thing_id)
            new_status = thing.status
            if new_status == 'ERROR':
                self.fail("%s failed to get to expected status."
                          "In ERROR state."
                          % thing)
            elif new_status == expected_status:
                return True  # All good.
            LOG.debug("Waiting for %s to get to %s status. "
                      "Currently in %s status",
                      thing, expected_status, new_status)
        conf = config.FuelConfig()
        if not call_until_true(check_status,
                               conf.compute.build_timeout,
                               conf.compute.build_interval):
            self.fail("Timed out waiting for thing %s to become %s"
                      % (thing_id, expected_status))


class ComputeFuzzClientTest(TestCase):

    """
    Base test case class for OpenStack Compute API (Nova)
    that uses the REST fuzz client libs for calling the API.
    """

    manager_class = manager.ComputeFuzzClientManager
