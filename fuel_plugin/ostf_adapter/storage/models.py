#    Copyright 2013 Mirantis, Inc.
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

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import desc
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import joinedload, relationship, object_mapper
from fuel_plugin.ostf_adapter import nose_plugin
from fuel_plugin.ostf_adapter.storage import fields, engine


BASE = declarative_base()


class TestRun(BASE):

    __tablename__ = 'test_runs'

    STATES = (
        'running',
        'finished'
    )

    id = sa.Column(sa.Integer(), primary_key=True)
    cluster_id = sa.Column(sa.Integer(), nullable=False)
    status = sa.Column(sa.Enum(*STATES, name='test_run_states'),
                       nullable=False)
    meta = sa.Column(fields.JsonField())
    started_at = sa.Column(sa.DateTime, default=datetime.utcnow)
    ended_at = sa.Column(sa.DateTime)
    test_set_id = sa.Column(sa.String(128), sa.ForeignKey('test_sets.id'))

    test_set = relationship('TestSet', backref='test_runs')
    tests = relationship('Test', backref='test_run', order_by='Test.name')

    def update(self, session, status):
        self.status = status
        if status == 'finished':
            self.ended_at = datetime.utcnow()
        session.add(self)

    @property
    def enabled_tests(self):
        return [test.name for test in self.tests if test.status != 'disabled']

    def is_finished(self):
        return self.status == 'finished'

    @property
    def frontend(self):
        test_run_data = {
            'id': self.id,
            'testset': self.test_set_id,
            'meta': self.meta,
            'cluster_id': self.cluster_id,
            'status': self.status,
            'started_at': self.started_at,
            'ended_at': self.ended_at,
            'tests': []
        }
        if self.tests:
            test_run_data['tests'] = [test.frontend for test in self.tests]
        return test_run_data

    @classmethod
    def add_test_run(cls, session, test_set, cluster_id, status='running',
                     tests=None):
        predefined_tests = tests or []
        tests = session.query(Test).filter_by(
            test_set_id=test_set, test_run_id=None)
        test_run = cls(test_set_id=test_set, cluster_id=cluster_id,
                       status=status)
        session.add(test_run)
        for test in tests:
            session.add(test.copy_test(test_run, predefined_tests))
        return test_run

    @classmethod
    def get_last_test_run(cls, session, test_set, cluster_id):
        test_run = session.query(cls). \
            filter_by(cluster_id=cluster_id, test_set_id=test_set). \
            order_by(desc(cls.id)).first()
        return test_run

    @classmethod
    def get_test_results(cls):
        session = engine.get_session()
        test_runs = session.query(cls). \
            options(joinedload('tests')). \
            order_by(desc(cls.id))
        session.commit()
        session.close()
        return test_runs

    @classmethod
    def get_test_run(cls, session, test_run_id, joined=False):
        if not joined:
            test_run = session.query(cls). \
                filter_by(id=test_run_id).first()
        else:
            test_run = session.query(cls). \
                options(joinedload('tests')). \
                filter_by(id=test_run_id).first()
        return test_run

    @classmethod
    def update_test_run(cls, session, test_run_id, status=None):
        updated_data = {}
        if status:
            updated_data['status'] = status
        if status in ['finished']:
            updated_data['ended_at'] = datetime.utcnow()
        session.query(cls). \
            filter(cls.id == test_run_id). \
            update(updated_data, synchronize_session=False)

    @classmethod
    def is_last_running(cls, session, test_set, cluster_id):
        test_run = cls.get_last_test_run(session, test_set, cluster_id)
        return not bool(test_run) or test_run.is_finished()

    @classmethod
    def start(cls, session, test_set, metadata, tests):
        plugin = nose_plugin.get_plugin(test_set.driver)
        if cls.is_last_running(session, test_set.id,
                               metadata['cluster_id']):
            test_run = cls.add_test_run(
                session, test_set.id,
                metadata['cluster_id'], tests=tests)
            plugin.run(test_run, test_set)
            return test_run.frontend
        return {}

    def restart(self, session, tests=None):
        """Restart test run with
            if tests given they will be enabled
        """
        if TestRun.is_last_running(session,
                                   self.test_set_id,
                                   self.cluster_id):
            plugin = nose_plugin.get_plugin(self.test_set.driver)
            self.update(session, 'running')
            if tests:
                Test.update_test_run_tests(
                    session, self.id, tests)
            plugin.run(self, self.test_set, tests)
            return self.frontend
        return {}

    def stop(self, session):
        """Stop test run if running
        """
        plugin = nose_plugin.get_plugin(self.test_set.driver)
        killed = plugin.kill(
            self.id, self.cluster_id,
            cleanup=self.test_set.cleanup_path)
        if killed:
            Test.update_running_tests(
                session, self.id, status='stopped')
        return self.frontend


class TestSet(BASE):

    __tablename__ = 'test_sets'

    id = sa.Column(sa.String(128), primary_key=True)
    description = sa.Column(sa.String(256))
    test_path = sa.Column(sa.String(256))
    driver = sa.Column(sa.String(128))
    additional_arguments = sa.Column(fields.ListField())
    cleanup_path = sa.Column(sa.String(128))
    meta = sa.Column(fields.JsonField())

    tests = relationship('Test',
                         backref='test_set', order_by='Test.name')

    @property
    def frontend(self):
        return {'id': self.id, 'name': self.description}

    @classmethod
    def get_test_set(cls, session, test_set):
        return session.query(cls).filter_by(id=test_set).first()


class Test(BASE):

    __tablename__ = 'tests'

    STATES = (
        'wait_running',
        'running',
        'failure',
        'success',
        'error',
        'stopped'
    )

    id = sa.Column(sa.Integer(), primary_key=True)
    name = sa.Column(sa.String(512))
    title = sa.Column(sa.String(512))
    description = sa.Column(sa.Text())
    duration = sa.Column(sa.String(512))
    message = sa.Column(sa.Text())
    traceback = sa.Column(sa.Text())
    status = sa.Column(sa.Enum(*STATES, name='test_states'))
    step = sa.Column(sa.Integer())
    time_taken = sa.Column(sa.Float())
    meta = sa.Column(fields.JsonField())

    test_set_id = sa.Column(sa.String(128), sa.ForeignKey('test_sets.id'))
    test_run_id = sa.Column(sa.Integer(), sa.ForeignKey('test_runs.id'))

    @property
    def frontend(self):
        return {
            'id': self.name,
            'testset': self.test_set_id,
            'name': self.title,
            'description': self.description,
            'duration': self.duration,
            'message': self.message,
            'step': self.step,
            'status': self.status,
            'taken': self.time_taken
        }

    @classmethod
    def add_result(cls, session, test_run_id, test_name, data):
        session.query(cls).\
            filter_by(name=test_name, test_run_id=test_run_id).\
            update(data, synchronize_session=False)

    @classmethod
    def update_running_tests(cls, session, test_run_id, status='stopped'):
        session.query(cls). \
            filter(cls.test_run_id == test_run_id,
                   cls.status.in_(('running', 'wait_running'))). \
            update({'status': status}, synchronize_session=False)

    @classmethod
    def update_test_run_tests(cls, session, test_run_id,
                              tests_names, status='wait_running'):
        session.query(cls). \
            filter(cls.name.in_(tests_names),
                   cls.test_run_id == test_run_id). \
            update({'status': status}, synchronize_session=False)

    def copy_test(self, test_run, predefined_tests):
        new_test = self.__class__()
        mapper = object_mapper(self)
        primary_keys = set([col.key for col in mapper.primary_key])
        for column in mapper.iterate_properties:
            if column.key not in primary_keys:
                setattr(new_test, column.key, getattr(self, column.key))
        new_test.test_run_id = test_run.id
        if predefined_tests and new_test.name not in predefined_tests:
            new_test.status = 'disabled'
        else:
            new_test.status = 'wait_running'
        return new_test
