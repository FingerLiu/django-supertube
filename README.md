# django-supertube
A powerful django migration tool to migrate from latency database to new databse using awesome django ORM


# 例子

## settings.py
```python
DATABASES = {
    'default': config('DATABASE_URL', cast=db_url),
    'latency': config('LATENCY_DATABASE_URL', cast=db_url)
}

```

## management/commands/mig_01_user.py
```python
from django.utils import timezone
from si.tools.supertube import SuperTube, TubeSet
"""
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

例子从 latency 数据库的 LatencyUser 取数据迁移到 default 数据库的 User 中：
  - 新加 username 字段，数据值从原 email 字段取
  - 修改 age 字段变为原来的 age+1
  - 新加 create_datetime 字段
  - 新加 is_admin 字段，默认值为 False

"""
class Command(BaseCommand):
    def handle(self, *args, **options):
        kwargs = {
            'mapping': {
                'username': 'email',
                'age': lambda obj: obj.age + 1, 
                'create_datetime': timezone.now()},
            'defaults': {'is_admin': False}
            'source_db': 'whistler'
        }
        st = SuperTube(LatencyUser, User, **kwargs)
        st.run(stop_on_error=True)
```

迁移工具 SuperTube 和 TubeSet 更多说明和例子参考[这个文档](https://github.com/FingerLiu/django-supertube/blob/master/supertube.py)

# 一个为 latency 中的旧数据建表的例子：
``` python


class Order(models.Model):
    sn = models.CharField(u'领用单编号', max_length=100)
    created = models.DateTimeField(u'创建时间', auto_now_add=True)
    apply_qty = models.IntegerField(u'计划领用数量', blank=True, null=True)
    # TODO 1 将原 model 中的外键字段名改为 原字段名+_id ，类型改为 IntegerField
    # batch = models.ForeignKey('stock.Batch', blank=True, null=True)
    batch_id = models.IntegerField('stock.Batch', blank=True, null=True)
    purpose = models.PositiveIntegerField(u'领用用途', choices=PURPOSES, blank=True, null=True)
    # platform = models.ForeignKey('si.Platform', blank=True, null=True, related_name='+')
    platform_id = models.IntegerField('si.Platform', blank=True, null=True)

    def __unicode__(self):
        return self.sn

    class Meta:
        verbose_name = u'Order'
        # TODO 2 注释掉原表中的 unique_together
        # unique_together = (
        #     ('platform', 'request_id'),
        #     ('platform', 'outer_id'),
        # )

        # TODO 3 managed 设为 False
        managed = False
        # TODO 4 指定 db table
        db_table = 'cardbox_applyvoucher'
```
