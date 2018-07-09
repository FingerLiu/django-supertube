#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
SuperTube:
一个神奇的数据迁移工具
"""

import sys
import os
import logging

from django.db import transaction
from django.core.management.color import no_style
from django.db import connection
from django.db.models import Model, ForeignKey


logger = logging.getLogger(__name__)


def progress(count, total, status=''):
    """
    模拟进度条

    >> import time

    >> total = 1000
    >> i = 0
    >> while i < total:
    >>     progress(i, total, status='Doing very long job')
    >>     time.sleep(0.05)  # emulating long-playing job
    >>     i += 10
    [===========================================================-] 99.0% ...Doing very long job
    """
    bar_len = 60
    filled_len = int(round(bar_len * count / float(total)))

    percents = round(100.0 * count / float(total), 1)
    bar = '=' * filled_len + '-' * (bar_len - filled_len)

    sys.stdout.write('%s:[%s] %s%s\r' % (status, bar, percents, '%'))
    sys.stdout.flush()


class SuperTube(object):
    """
    将 source model 对应的数据全部迁移到 dest 中。

    class LatencyUser:
        email
        password
        age

    class User:
        email
        age
        username
        password
        is_admin
        create_datetime

    >> from django.utils import timezone
    >> kwargs = {
    >>    'mapping': {'username': 'email', 'age': lambda x: x.age+1, 'create_datetime': timezone.now()},
    >>    'defaults': {'is_admin': False}
    >>    'source_db': 'latency_db'
    >>}
    >> st = SuperTube(LatencyUser, User, **kwargs)
    >> st.run(stop_on_error=False)
    '10 of 10 succeed in 0.001 ms.'

    >> st.result
    True
    """
    def __init__(self, source, dest, filter=None, **kwargs):
        """

        :param source: django model
        :param dest: django model
        :param kwargs: set default, custom mapping
        """
        if not (issubclass(source, Model) and issubclass(dest, Model)):
            raise ValueError('source and dest must be subclass of django.db.models.Model')
        if filter and not (isinstance(filter, dict)):
            raise ValueError('filter should be a key-value dict representing queries.')

        self.source = source
        self.dest = dest
        self.custom_mapping = kwargs.get('mapping', {})
        self.defaults = kwargs.get('defaults', {})
        self.source_db = kwargs.get('source_db', 'default')

        if filter:
            self.source_qs = source.objects.using(self.source_db).filter(**filter)
        else:
            self.source_qs = source.objects.using(self.source_db).all()

        self.total_cnt = self.source_qs.count()
        self.source_qs = self.source_qs.iterator()
        self.succeed_cnt = 0
        self.__setup_fields()
        self.__setup_mapping()

    @staticmethod
    def get_field_name(field):
        if isinstance(field, ForeignKey):
            return field.name + '_id'
        else:
            return field.name

    def __setup_fields(self):
        sf = self.source_fields = set([SuperTube.get_field_name(field) for field in self.source._meta.fields])
        df = self.dest_fields = set([SuperTube.get_field_name(field) for field in self.dest._meta.fields])
        self.intersection_fields = sf & df

    def __setup_mapping(self):
        mapping = {}
        for field in self.intersection_fields:
            mapping[field] = field
        for k, v in self.custom_mapping.items():
            mapping[k] = v

        self.mapping = mapping

    def build_obj(self, old_obj):
        obj_data = {}
        for field, old_field in self.mapping.items():
            if callable(old_field):
                func = old_field
                obj_data[field] = func(old_obj)
            else:
                obj_data[field] = getattr(old_obj, old_field)
        obj = self.dest(**obj_data)

        for field, value in self.defaults.items():
            if not (hasattr(obj, field) and getattr(obj, field)):
                setattr(obj, field, value)

        return obj

    @transaction.atomic()
    def run(self, batch_size=1000, check_foreignkey=True, stop_on_error=True, dry_run=False, skip=True):
        """
        :param batch_size: integer bulk size.
        :param check_foreignkey: A boolean flag.
        :param stop_on_error: A boolean flag.
        :return:
        """
        # TODO check_foreignkey
        # TODO stop_on_error

        if not self.total_cnt:
            print('\n\nmigrate to %s finished: %s of %s succeed.' %
                  (self.source._meta.object_name, self.succeed_cnt, self.total_cnt))
            return
        buffer = []
        qs = self.source_qs
        for old_obj in qs:
            try:
                obj = self.build_obj(old_obj)
            except Exception as e:
                logger.warning('skip obj %s due to %s', old_obj, str(e))
                if skip:
                    continue
                else:
                    raise

            buffer.append(obj)
            if len(buffer) >= batch_size:
                if not dry_run:
                    created = self.dest.objects.bulk_create(buffer, batch_size=batch_size)
                else:
                    created = buffer
                self.succeed_cnt += len(created)
                buffer.clear()
                progress(
                    self.succeed_cnt, self.total_cnt,
                    status='migrating from %s to %s(%s/%s)' %
                           (self.source._meta.object_name, self.dest._meta.object_name, self.succeed_cnt, self.total_cnt)
                )

        if len(buffer):
            if not dry_run:
                created = self.dest.objects.bulk_create(buffer, batch_size=batch_size)
            else:
                created = buffer
            self.succeed_cnt += len(created)
            buffer.clear()
        progress(self.succeed_cnt, self.total_cnt,
                 status='migrating from %s to %s(%s/%s)' %
                        (self.source._meta.object_name, self.dest._meta.object_name, self.succeed_cnt, self.total_cnt)
        )

        print('\n\nmigrate to %s finished: %s of %s succeed.' %
              (self.source._meta.object_name, self.succeed_cnt, self.total_cnt))
        logger.info('\n\nmigrate to %s finished: %s of %s succeed.',
                    self.source._meta.object_name, self.succeed_cnt, self.total_cnt)


class TubeSet(object):
    def __init__(self, source_db=None):
        self.source_db = source_db
        self._tubes = []

    def add_tube(self, source, dest, **kwargs):
        if self.source_db and 'source_db' not in kwargs:
            kwargs['source_db'] = self.source_db
        self._tubes.append(SuperTube(source, dest, **kwargs))

    def update_sequence(self):
        """
        https://stackoverflow.com/questions/14589634/how-to-reset-the-sequence-for-ids-on-postgresql-tables
        :return: sequence val
        """
        models = [tube.dest for tube in self._tubes]
        sequence_sql = connection.ops.sequence_reset_sql(no_style(), models)
        with connection.cursor() as cursor:
            for sql in sequence_sql:
                cursor.execute(sql)
        print('reset sequence finished for ', models)

    def run(self, **kwargs):
        if 'dry_run' in kwargs and kwargs['dry_run']:
            print('*'*90+'\n'
            +'\nFBI Warning: Start run tubeset in dry-run mode, no data will be written to dest database.\n\n'
            +'*'*90+'\n')
        for tube in self._tubes:
            tube.run(**kwargs)
        print('reset sequence start.')
        self.update_sequence()

        print('%s tables migrated.' % len(self._tubes))
        logger.info('%s tables migrated.' % len(self._tubes))


if __name__ == '__main__':
    """test case"""

    import django
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tether.settings")
    django.setup()

    # from generator.supertube import SuperTube, TubeSet
    from si.tools.supertube import SuperTube, TubeSet
    from latency.models import ContractxContractx, ContractxItem
    from contract.models import Contract, ContractItem
    from django.utils import timezone
    from si.models import Company, Product
    now = timezone.now()
    company = Company.objects.first().id
    product = Product.objects.first().id

    tubeset = TubeSet(source_db='tubeground')
    contract_settings = {
        'mapping': {
            'principal_a': 'principal_a_id',
            'principal_b': 'principal_b_id',
            'source_id': 'id',
            'create_user_id': lambda obj: obj.create_user.id,
            'update_user_id': 'creator_id'
        },
        'defaults': {
            'group_a_id': company,
            'group_b_id': company,
            'party_a_id': company,
            'party_b_id': company,
        }
    }

    tubeset.add_tube(ContractxContractx, Contract, **contract_settings)
    contractitem_settings = {
        'mapping': {
            'contract_id': 'contractx_id',
        },
        'defaults': {
            'product_a_id': product,
            'product_b_id': product,
        }
    }
    tubeset.add_tube(ContractxItem, ContractItem, **contractitem_settings)

    tubeset.run()
